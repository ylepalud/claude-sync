"""`claude-sync uninstall`: move the default profile back to `~/.claude`."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from claude_sync import config, converge, manifest, migration, paths, system
from claude_sync.claude_cli import ClaudeCli
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command

STATE_FILE = ".claude.json"
MANIFEST = manifest.MANIFEST_FILE
# ~/.claude is no profile any more: there is nothing to accept the moved versions into.
DRIFT_HINT = "the plugins were rebuilt with the upstream versions"
INTERRUPTED = 130  # 128 + SIGINT, as init exits


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--from-backup",
        nargs="?",
        const="",
        metavar="FILE",
        help="restore a backup instead (default FILE: the latest backup)",
    )


def _finish_by_hand(old: Path, old_json: Path) -> str:
    show = paths.display
    return (
        f"move {show(old / STATE_FILE)} to {show(old_json)} if it is still there, "
        f"then delete {show(old / migration.RECORD_FILE)}"
    )


def _check(old: Path, old_json: Path, name: str, profile: Path) -> migration.Record:
    """The profile's migration record, once uninstall can move the profile back safely."""
    record = migration.Record.load(profile)
    if record is None:
        if not os.path.lexists(profile) and os.path.lexists(old / migration.RECORD_FILE):
            raise ClaudeSyncError(
                f"profile {name!r} was already moved back to {paths.display(old)}: "
                + _finish_by_hand(old, old_json)
            )
        raise ClaudeSyncError(
            f"profile {name!r} has no migration record ({paths.display(profile)}): "
            "nothing to uninstall"
        )
    _check_absent(old, old_json, profile, record)
    return record


def _check_absent(old: Path, old_json: Path, profile: Path, record: migration.Record) -> None:
    """Refuse when a rename back would replace an entry; run before the prompt and after it."""
    if os.path.lexists(old):
        raise ClaudeSyncError(
            f"{paths.display(old)} exists: move it aside, or bring it into the profile "
            "with claude-sync adopt"
        )
    # The record alone is not trusted: an interrupt can leave the second rename unrecorded.
    moved = "rename-claude-json" in record.steps or os.path.lexists(profile / STATE_FILE)
    if moved and os.path.lexists(old_json):
        raise ClaudeSyncError(
            f"{paths.display(old_json)} exists, and the profile's own state file would "
            "replace it: move it aside first"
        )


def _plan(old: Path, old_json: Path, profile: Path, record: migration.Record) -> list[str]:
    show = paths.display
    steps = [
        f"unload and delete {show(migration.launch_agent_path())}, then run "
        "launchctl unsetenv CLAUDE_CONFIG_DIR",
    ]
    if "zshrc" in record.steps:
        steps.append(f"remove the claude-sync block from {show(Path.home() / '.zshrc')}")
    steps += [
        f"replace {show(profile)} by {show(old)} in the profile's settings.json",
        f"give the symbolic links init made absolute ({len(record.links)}) "
        "their relative text back",
    ]
    if "gitignore" in record.steps:
        steps.append(f"remove {migration.MANIFEST_RULE} from the profile's .gitignore")
    steps.append(f"rename {show(profile)} to {show(old)}")
    if os.path.lexists(profile / STATE_FILE):
        steps.append(f"rename {show(profile / STATE_FILE)} to {show(old_json)}")
    steps.append(f"delete the migration record {migration.RECORD_FILE}")
    if "plugin-caches" in record.steps:
        steps.append(
            f"remove the plugin caches and lists of {show(old)}, rebuild them from "
            f"{MANIFEST} with CLAUDE_CONFIG_DIR unset (network), then delete {MANIFEST}"
        )
    return steps


def _print_plan(steps: list[str], verb: str) -> None:
    print(f"uninstall {verb} move the default profile back:")
    for number, step in enumerate(steps, 1):
        print(f"  {number:>2}. {step}")
    print("other profiles and the backups stay in place")


def _unload_agent() -> None:
    try:
        system.launchctl("bootout", f"gui/{system.uid()}/{migration.LAUNCH_AGENT_LABEL}")
    except ClaudeSyncError:
        pass  # not loaded
    migration.launch_agent_path().unlink(missing_ok=True)
    system.launchctl("unsetenv", "CLAUDE_CONFIG_DIR")


def _stopped(error: BaseException, recovery: str) -> ClaudeSyncError | None:
    """Report `recovery` for `error`: the error to raise, or None after printing it for Ctrl-C."""
    if isinstance(error, Exception):
        return ClaudeSyncError(f"{error}\n{recovery}")
    print(f"claude-sync: interrupted\n{recovery}", file=sys.stderr)
    return None


@contextmanager
def _guarded(recovery: str) -> Iterator[None]:
    """Turn a failure or Ctrl-C inside the `with` block into `recovery`."""
    try:
        yield
    except BaseException as error:
        raised = _stopped(error, recovery)
        if raised is None:
            raise
        raise raised from error


def _move_back(old: Path, old_json: Path, profile: Path, record: migration.Record) -> None:
    """Every step up to the plugin rebuild; each one before the first rename can run again."""
    with _guarded(
        "uninstall stopped before moving the profile back: rerun `claude-sync uninstall` "
        f"(move aside, or adopt, a {paths.display(old)} recreated meanwhile), or run "
        "`claude-sync uninstall --from-backup`"
    ):
        _unload_agent()
        if "zshrc" in record.steps:  # init records only a block it added
            migration.zshrc_block_remove(Path.home() / ".zshrc")
        migration.rewrite_settings(profile, str(profile), str(old))
        migration.relativize_symlinks(record.links, profile)
        if "gitignore" in record.steps:  # init records only a rule it added
            migration.remove_manifest_rule(profile)
        _check_absent(old, old_json, profile, record)  # something may have appeared meanwhile
        os.rename(profile, old)
    with _guarded(
        f"uninstall stopped after moving the profile back to {paths.display(old)}: "
        + _finish_by_hand(old, old_json)
    ):
        if os.path.lexists(old / STATE_FILE):
            os.rename(old / STATE_FILE, old_json)
        (old / migration.RECORD_FILE).unlink()


def _rebuild(old: Path, ctx: Context) -> int:
    """Rebuild the plugin caches of `old`, then delete its manifest; a failure is a warning."""
    hint = (
        f"{paths.display(old)} is back; install the plugins listed in "
        f"{paths.display(old / MANIFEST)} again with claude plugin install"
    )
    migration.remove_plugin_caches(old)
    try:
        code = converge.converge(old, ctx, cli=ClaudeCli(None), drift_hint=DRIFT_HINT)
    except KeyboardInterrupt:
        print(f"claude-sync: interrupted\n{hint}", file=sys.stderr)
        raise
    except Exception as error:
        print(f"claude-sync: warning: rebuilding the plugins failed: {error}", file=sys.stderr)
        print(hint, file=sys.stderr)
        return int(ExitCode.DRIFT)
    (old / MANIFEST).unlink(missing_ok=True)  # kept on failure: the hint points to it
    return code


def _archive(given: str) -> Path:
    """The backup to restore, checked whole: `given`, or the latest one when empty."""
    if given:
        archive = Path(given).expanduser()
    else:
        found = sorted(paths.backups_dir().glob("*.tar.gz"))
        if not found:
            raise ClaudeSyncError(f"no backup in {paths.display(paths.backups_dir())}")
        archive = found[-1]
    migration.check_backup(archive)  # before anything is moved aside
    return archive


def _failed_suffix() -> str:
    return ".failed-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _readable_record(profile: Path) -> migration.Record | None:
    """The profile's record, None when it has none or it is damaged (the backup is the way out)."""
    try:
        return migration.Record.load(profile)
    except ClaudeSyncError:
        return None


def _aside_recovery(moved: list[Path], suffix: str) -> str:
    listing = ", ".join(f"{paths.display(path)}{suffix}" for path in moved) or "nothing"
    return (
        f"uninstall --from-backup stopped; moved aside: {listing}; nothing was deleted: "
        "rerun `claude-sync uninstall --from-backup`, or rename them back by hand"
    )


def _from_backup(given: str, old: Path, old_json: Path, profile: Path, ctx: Context) -> int:
    if not ctx.dry_run:
        system.refuse_if_claude_runs()
    archive = _archive(given)
    record = _readable_record(profile)
    remove_block = record is not None and "zshrc" in record.steps  # else the block is the user's
    suffix = _failed_suffix()
    aside = [path for path in (old, old_json, profile) if os.path.lexists(path)]
    show = paths.display
    for path in aside:
        if os.path.lexists(f"{path}{suffix}"):
            raise ClaudeSyncError(f"{show(path)}{suffix} exists: rerun in a moment")
    steps = [
        f"unload and delete {show(migration.launch_agent_path())}, then run "
        "launchctl unsetenv CLAUDE_CONFIG_DIR",
    ]
    if remove_block:
        steps.append(f"remove the claude-sync block from {show(Path.home() / '.zshrc')}")
    steps += [
        *(f"rename {show(path)} to {show(path)}{suffix}" for path in aside),
        f"extract {show(archive)} into {show(Path.home())}",
    ]
    verb = "would" if ctx.dry_run else "will"
    print(f"uninstall {verb} restore a backup:")
    for number, step in enumerate(steps, 1):
        print(f"  {number:>2}. {step}")
    if ctx.dry_run:
        print("a real run also checks that Claude is not running")
        return int(ExitCode.OK)
    if not ctx.confirm("Restore the backup now?"):
        print("cancelled", file=sys.stderr)
        return int(ExitCode.OK)
    _unload_agent()
    if remove_block:
        migration.zshrc_block_remove(Path.home() / ".zshrc")
    for path in aside:
        with _guarded(_aside_recovery(aside[: aside.index(path)], suffix)):
            os.rename(path, f"{path}{suffix}")
    with _guarded(_aside_recovery(aside, suffix)):
        migration.extract_backup(archive, Path.home())
    print(f"restored {show(old)} and {show(old_json)} from {show(archive)}")
    return int(ExitCode.OK)


def run(args: argparse.Namespace, ctx: Context) -> int:
    old, old_json = Path.home() / ".claude", Path.home() / STATE_FILE
    name = config.load().default
    profile = paths.profile_dir(name)
    try:
        if args.from_backup is not None:
            return _from_backup(args.from_backup, old, old_json, profile, ctx)
        if ctx.dry_run:
            record = _check(old, old_json, name, profile)
            _print_plan(_plan(old, old_json, profile, record), "would")
            print("a real run also checks that Claude is not running")
            return int(ExitCode.OK)
        system.refuse_if_claude_runs()
        record = _check(old, old_json, name, profile)
        _print_plan(_plan(old, old_json, profile, record), "will")
        if not ctx.confirm("Move the profile back now?"):
            print("cancelled", file=sys.stderr)
            return int(ExitCode.OK)
        _move_back(old, old_json, profile, record)
        code = _rebuild(old, ctx) if "plugin-caches" in record.steps else int(ExitCode.OK)
    except KeyboardInterrupt:
        return INTERRUPTED  # the recovery for that point is printed
    print(f"moved {paths.display(profile)} back to {paths.display(old)}")
    return code


COMMAND = Command(
    name="uninstall",
    summary="move the default profile back to ~/.claude",
    description=(
        "Reverse claude-sync init, working from the migration record it left in the\n"
        "default profile. uninstall refuses, changing nothing, while the Claude Code\n"
        "CLI (claude) or the desktop app (Claude) runs, when the profile has no\n"
        "migration record, when ~/.claude exists (claude-sync adopt moves it into\n"
        "the profile), or when ~/.claude.json exists although the profile has its own\n"
        "or the record says init moved it. A migration interrupted between its two\n"
        "renames is recovered: ~/.claude.json, still in place, stays.\n"
        "\n"
        "It prints every step and asks one confirmation. In order: unload and delete\n"
        "the LaunchAgent and run launchctl unsetenv CLAUDE_CONFIG_DIR; remove the\n"
        "~/.zshrc block init added; put ~/.claude back in settings.json and give the\n"
        "symbolic links init made absolute their relative text back; remove the\n"
        "!/profile.toml line init added to .gitignore; check again that ~/.claude\n"
        "and ~/.claude.json are absent; rename the profile to ~/.claude and its\n"
        ".claude.json to ~/.claude.json; delete the record (after the renames, so a\n"
        "failed rename can be retried); then, when init had removed the plugin\n"
        "caches, remove the plugin caches and lists and rebuild them from\n"
        "profile.toml (network), running the claude CLI with CLAUDE_CONFIG_DIR\n"
        "unset, and delete profile.toml. A failing rebuild is a warning (exit 4) and\n"
        "keeps profile.toml. Other profiles and the backups stay in place.\n"
        "\n"
        "--from-backup [FILE] restores a backup instead (default: the latest one in\n"
        "the backups directory next to the configuration file). The whole archive\n"
        "is checked first: absolute or escaping member names are refused. Then it\n"
        "unloads the LaunchAgent, unsets the variable, removes the ~/.zshrc block\n"
        "when the profile's record says init added it,\n"
        "renames whatever exists of ~/.claude, ~/.claude.json and the default\n"
        "profile directory with a .failed-<UTC timestamp, microseconds> suffix\n"
        "(never deleting them), and extracts the backup into the home directory.\n"
        "\n"
        "A failure or an interrupt (Ctrl-C, exit 130) stops uninstall and says how\n"
        "to recover at that point.\n"
        "\n"
        "--dry-run checks the file conditions only: it runs neither pgrep nor claude."
    ),
    examples=[
        ("claude-sync uninstall --dry-run", "print the steps, change nothing"),
        ("claude-sync uninstall", "check, print the steps and ask before moving back"),
        ("claude-sync uninstall --from-backup --yes", "restore the latest backup, no prompt"),
        (
            "claude-sync uninstall --from-backup ~/.config/claude-sync/backups/X.tar.gz",
            "restore that backup",
        ),
    ],
    exit_codes=[
        ExitCode.OK,
        ExitCode.ERROR,
        ExitCode.USAGE,
        ExitCode.CONFIRMATION_REQUIRED,
        ExitCode.DRIFT,
    ],
    kind="mutate",
    configure=configure,
    run=run,
)
