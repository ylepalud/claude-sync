"""`claude-sync init`: move `~/.claude` into the default profile."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from claude_sync import config, converge, manifest, migration, paths, sync, system
from claude_sync.claude_cli import ClaudeCli
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command

STATE_FILE = ".claude.json"
MANIFEST = manifest.MANIFEST_FILE
INTERRUPTED = 130  # 128 + SIGINT, as a shell reports an interrupted command


def configure(parser: argparse.ArgumentParser) -> None:
    """init has no options of its own: --dry-run and --yes come with its kind."""


def _size(old: Path, old_json: Path) -> int:
    """Bytes of the files under `old` and of `old_json`, links not followed."""
    total = old_json.lstat().st_size
    for directory, _, filenames in os.walk(old):
        total += sum(os.lstat(os.path.join(directory, n)).st_size for n in filenames)
    return total


def _check_files(old: Path, name: str, profile: Path) -> None:
    if old.is_symlink():
        raise ClaudeSyncError(f"{paths.display(old)} is a symbolic link: move its target by hand")
    if not old.is_dir():
        raise ClaudeSyncError(f"{paths.display(old)} does not exist: nothing to migrate")
    old_json = Path.home() / STATE_FILE
    if not os.path.lexists(old_json):
        raise ClaudeSyncError(
            f"{paths.display(old_json)} does not exist: start Claude Code once to create it"
        )
    inner = old / STATE_FILE
    if os.path.lexists(inner):
        raise ClaudeSyncError(
            f"{paths.display(inner)} exists and would clash with ~/.claude.json: "
            "merge or remove it by hand"
        )
    if os.path.lexists(profile):
        raise ClaudeSyncError(f"profile {name!r} already exists ({paths.display(profile)})")
    root = paths.profiles_root()
    if system.device(old) != system.device(root):
        raise ClaudeSyncError(
            f"{paths.display(old)} and {paths.display(root)} are not on the same file system: "
            "init moves the configuration with a rename"
        )
    size, free = _size(old, old_json), system.free_bytes(paths.backups_dir())
    if free < size:
        raise ClaudeSyncError(
            f"not enough free space for the backup: {size} bytes needed, {free} free"
        )


def _check_plugins(old: Path) -> None:
    cli = ClaudeCli(None)  # CLAUDE_CONFIG_DIR unset: never creates ~/.claude/.claude.json
    try:
        listed = json.loads(cli.run(["plugin", "list", "--json"]))
    except ValueError as error:
        raise ClaudeSyncError(
            f"`claude plugin list --json` printed invalid JSON: {error}"
        ) from error
    blocked = migration.unrebuildable(sync.observe(cli, old), listed)
    if blocked:
        raise ClaudeSyncError(
            "these plugins cannot be rebuilt from a manifest; uninstall them first: "
            + ", ".join(blocked)
        )


def _plan(old: Path, old_json: Path, name: str, profile: Path) -> list[str]:
    show = paths.display
    return [
        f"back up {show(old)} and {show(old_json)} to {show(paths.backups_dir())}/",
        f"read the plugins and marketplaces of {show(old)} for {MANIFEST}",
        f"rename {show(old)} to {show(profile)}",
        f"write the migration record {migration.RECORD_FILE} in the profile",
        f"rename {show(old_json)} to {show(profile / STATE_FILE)}",
        f"make the relative symbolic links that point outside {show(old)} absolute",
        f"replace {show(old)} by {show(profile)} in the profile's settings.json",
        f"append {migration.MANIFEST_RULE} to the profile's .gitignore when it ignores {MANIFEST}",
        f"add the claude-sync block to {show(Path.home() / '.zshrc')} unless present",
        f"write and load {show(migration.launch_agent_path())}, which sets "
        f"CLAUDE_CONFIG_DIR to {show(profile)} at login",
        f"remove the plugin caches and lists, write {MANIFEST} and run claude-sync apply (network)",
        f"list the Markdown files that still name {show(old)}",
    ]


def _print_plan(steps: list[str], name: str, verb: str) -> None:
    print(f"init {verb} migrate the configuration into the profile {name!r}:")
    for number, step in enumerate(steps, 1):
        print(f"  {number:>2}. {step}")


def run(args: argparse.Namespace, ctx: Context) -> int:
    old, old_json = Path.home() / ".claude", Path.home() / STATE_FILE
    name = config.load().default
    profile = paths.profile_dir(name)
    steps = _plan(old, old_json, name, profile)
    if ctx.dry_run:
        _check_files(old, name, profile)
        _print_plan(steps, name, "would")
        print("a real run also checks that Claude is not running and that every plugin")
        print("can be rebuilt from the manifest")
        return int(ExitCode.OK)
    system.refuse_if_claude_runs()
    _check_files(old, name, profile)
    _check_plugins(old)
    _print_plan(steps, name, "will")
    if not ctx.confirm("Migrate now?"):
        print("cancelled", file=sys.stderr)
        return int(ExitCode.OK)
    try:
        record = _migrate(old, old_json, profile)
    except KeyboardInterrupt:
        return INTERRUPTED  # _migrate printed the recovery
    return _rebuild(old, profile, record, ctx)


def _save(record: migration.Record, profile: Path, step: str) -> None:
    record.steps.append(step)
    record.save(profile)


def _migrate(old: Path, old_json: Path, profile: Path) -> migration.Record:
    """Every step up to the plugin rebuild; a failure carries the recovery for its point."""
    phase = "before"
    try:
        archive = migration.backup([old, old_json], paths.backups_dir())
        print(f"backup written: {paths.display(archive)}")
        imported = converge.build_manifest(old, None, ClaudeCli(None))
        paths.profiles_root().mkdir(mode=0o700, parents=True, exist_ok=True)
        os.rename(old, profile)
        phase = "unrecorded"
        record = migration.Record(str(old), steps=["backup", "import", "rename-claude"])
        record.save(profile)
        phase = "recorded"
        os.rename(old_json, profile / STATE_FILE)
        _save(record, profile, "rename-claude-json")

        def record_link(relative: Path, text: str) -> None:
            record.links.append((relative, text))
            record.save(profile)

        migration.absolutize_symlinks(profile, old, record_link)
        _save(record, profile, "symlinks")
        record.settings_keys = migration.rewrite_settings(profile, str(old), str(profile))
        _save(record, profile, "settings")
        if migration.allow_manifest(profile):
            _save(record, profile, "gitignore")  # only a rule init added is init's to remove
        if migration.zshrc_block_add(Path.home() / ".zshrc"):
            _save(record, profile, "zshrc")  # only a block init added is init's to remove
        plist = migration.launch_agent_path()
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(migration.launch_agent_plist(profile), encoding="utf-8")
        record.plist = str(plist)
        record.save(profile)
        _load_agent(plist)
        _save(record, profile, "launch-agent")
        migration.remove_plugin_caches(profile)
        _save(record, profile, "plugin-caches")
        manifest.save(profile / MANIFEST, imported)
        _save(record, profile, "manifest")
        return record
    except BaseException as error:
        if phase == "unrecorded":
            phase = _move_back(profile, old)
        recovery = _recovery(phase, old, old_json, profile)
        if isinstance(error, Exception):
            raise ClaudeSyncError(f"{error}\n{recovery}") from error
        print(f"claude-sync: interrupted\n{recovery}", file=sys.stderr)
        raise


def _move_back(profile: Path, old: Path) -> str:
    """Undo the first rename when no record names it yet; the phase it leaves."""
    try:
        os.rename(profile, old)
    except OSError:
        return "unrecorded"
    return "before"


def _recovery(phase: str, old: Path, old_json: Path, profile: Path) -> str:
    if phase == "recorded":
        return (
            "init stopped after moving the configuration: run `claude-sync uninstall` to move "
            "it back, or `claude-sync uninstall --from-backup` to restore the backup"
        )
    if phase == "unrecorded":
        return (
            f"init stopped after renaming {paths.display(old)} to {paths.display(profile)}, "
            "before writing the migration record, and could not rename it back: rename it "
            "back by hand, or run `claude-sync uninstall --from-backup`"
        )
    return (
        f"init stopped before moving anything: {paths.display(old)} and "
        f"{paths.display(old_json)} are unchanged"
    )


def _load_agent(plist: Path) -> None:
    domain = f"gui/{system.uid()}"
    try:
        system.launchctl("bootout", f"{domain}/{migration.LAUNCH_AGENT_LABEL}")
    except ClaudeSyncError:
        pass  # not loaded yet
    system.launchctl("bootstrap", domain, str(plist))


def _rebuild(old: Path, profile: Path, record: migration.Record, ctx: Context) -> int:
    """Run apply, then list what is left to the user; a failing apply is a warning (exit 4)."""
    try:
        code = converge.converge(profile, ctx, skills=False, mcp=False)
    except KeyboardInterrupt:
        print(
            "claude-sync: interrupted; the profile is migrated: run claude-sync apply",
            file=sys.stderr,
        )
        return INTERRUPTED
    except Exception as error:
        print(f"claude-sync: warning: rebuilding the plugins failed: {error}", file=sys.stderr)
        print("the profile is migrated; run claude-sync apply", file=sys.stderr)
        code = int(ExitCode.DRIFT)
    else:
        _save(record, profile, "apply")
    mentions = migration.markdown_mentions(profile, old)
    if mentions:
        print(f"these Markdown files still name {paths.display(old)}; fix them by hand:")
        for path in mentions:
            print(f"  {paths.display(path)}")
    print(f"migrated {paths.display(old)} into {paths.display(profile)}")
    print("sign in again with /login in each profile: the login follows the config dir")
    return code


COMMAND = Command(
    name="init",
    summary="move ~/.claude into the default profile",
    description=(
        "Migrate the existing Claude Code configuration into the default profile.\n"
        "init checks first and refuses, changing nothing, while the Claude Code CLI\n"
        "(claude) or the desktop app (Claude) runs, when ~/.claude is missing or a\n"
        "symbolic link, when ~/.claude.json is missing, when ~/.claude/.claude.json\n"
        "exists, when the default profile directory exists, when ~/.claude and the\n"
        "profiles directory are on different file systems, when the free space is\n"
        "smaller than the configuration, or when a plugin cannot be rebuilt from a\n"
        "manifest (installed at another scope than user, or from a marketplace\n"
        "claude-sync does not manage).\n"
        "\n"
        "It then prints every step and asks one confirmation. In order: a gzip tar\n"
        "backup of ~/.claude and ~/.claude.json in the backups directory next to\n"
        "the configuration file; the manifest of the installed plugins; the rename\n"
        "of ~/.claude to the profile directory and of ~/.claude.json into it; a\n"
        "migration record (.claude-sync-migration.json, untracked) updated after\n"
        "each later step; relative symbolic links pointing outside ~/.claude made\n"
        "absolute; the old path replaced in settings.json; profile.toml allowed in\n"
        "the profile's .gitignore; a marked block in ~/.zshrc; a LaunchAgent that\n"
        "sets CLAUDE_CONFIG_DIR at login; then the plugin caches are removed and\n"
        "rebuilt with apply (network). Markdown files still naming ~/.claude are\n"
        "listed, never changed. Sign in again with /login in each profile.\n"
        "\n"
        "The claude CLI runs with CLAUDE_CONFIG_DIR unset while ~/.claude is read.\n"
        "\n"
        "A failure stops init and says how to recover: before the migration record\n"
        "is written nothing changed (the first rename is undone); after it,\n"
        "claude-sync uninstall moves the configuration back (or uninstall\n"
        "--from-backup restores the backup). A failing plugin\n"
        "rebuild is a warning: the profile is migrated, run claude-sync apply.\n"
        "\n"
        "An interrupt (Ctrl-C) is handled like a failure at that point and exits 130.\n"
        "\n"
        "--dry-run checks the file conditions only: it runs neither pgrep nor claude."
    ),
    examples=[
        ("claude-sync init --dry-run", "print the steps, change nothing"),
        ("claude-sync init", "check, print the steps and ask before migrating"),
        ("claude-sync init --yes", "migrate without asking"),
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
