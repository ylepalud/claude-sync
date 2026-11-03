"""`claude-sync adopt`: move a recreated `~/.claude` into a profile."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from claude_sync import config, paths, system, target
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command

STATE_FILE = ".claude.json"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile", metavar="NAME", help="profile to move into (default: the default profile)"
    )


def _real_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def _sort(source: Path, dest: Path, moves: list, conflicts: list) -> None:
    """Sort the entries of `source` into moves to `dest` and conflicts, descending into
    the directories both sides have."""
    for name in sorted(os.listdir(source)):
        entry, there = source / name, dest / name
        if not os.path.lexists(there):
            moves.append((entry, there))
        elif _real_dir(entry) and _real_dir(there):
            _sort(entry, there, moves, conflicts)
        else:
            conflicts.append((entry, there))


def _left_empty(directory: Path, moved: set[Path], found: list[Path]) -> bool:
    """Whether `directory` ends empty once `moved` is gone; appends each such directory
    to `found`, children before their parent."""
    empty = True
    for name in sorted(os.listdir(directory)):
        child = directory / name
        if child in moved or (_real_dir(child) and _left_empty(child, moved, found)):
            continue
        empty = False
    if empty:
        found.append(directory)
    return empty


def run(args: argparse.Namespace, ctx: Context) -> int:
    stray = Path.home() / ".claude"
    stray_json = Path.home() / STATE_FILE
    profile = target.resolve_target(args.profile or config.load().default)
    if not ctx.dry_run:
        system.refuse_if_claude_runs()
    if not os.path.lexists(stray) and not os.path.lexists(stray_json):
        print("nothing to adopt: neither ~/.claude nor ~/.claude.json exists")
        return int(ExitCode.OK)
    if stray.is_symlink():
        raise ClaudeSyncError(
            f"{paths.display(stray)} is a symbolic link: adopt moves no link target"
        )
    if os.path.lexists(stray) and not stray.is_dir():
        raise ClaudeSyncError(f"{paths.display(stray)} is not a directory: move it aside by hand")
    moves: list[tuple[Path, Path]] = []
    conflicts: list[tuple[Path, Path]] = []
    if os.path.lexists(stray):
        _sort(stray, profile.directory, moves, conflicts)
    if os.path.lexists(stray_json):
        there = profile.directory / STATE_FILE
        # ~/.claude/.claude.json may be moving there too: never let one replace the other.
        taken = os.path.lexists(there) or any(dest == there for _, dest in moves)
        (conflicts if taken else moves).append((stray_json, there))
    show = paths.display
    for entry, there in moves:
        print(f"move {show(entry)} to {show(there)}")
    for entry, there in conflicts:
        print(f"conflict: {show(entry)} stays, {show(there)} exists")
    removals: list[Path] = []
    if os.path.lexists(stray):
        _left_empty(stray, {entry for entry, _ in moves}, removals)
    for directory in removals:
        print(f"remove the empty directory {show(directory)}")
    if ctx.dry_run:
        return int(ExitCode.OK)
    if not (moves or removals):
        kept = f"{show(stray)} is kept" if os.path.lexists(stray) else "nothing moved"
        print(f"{kept}: merge or remove the conflicting entries by hand")
        return int(ExitCode.OK)
    if not ctx.confirm("Move and remove these entries now?"):
        print("cancelled", file=sys.stderr)
        return int(ExitCode.OK)
    try:
        for entry, there in moves:
            os.rename(entry, there)
        for directory in removals:
            directory.rmdir()  # refuses a directory something wrote to meanwhile
    except OSError as error:
        raise ClaudeSyncError(
            f"{error}\nadopt stopped part way: what moved is in {show(profile.directory)}; "
            "rerun claude-sync adopt for the rest"
        ) from error
    if os.path.lexists(stray):
        print(f"{show(stray)} is kept: merge or remove the conflicting entries by hand")
    elif moves:
        print(f"adopted into {show(profile.directory)}")
    return int(ExitCode.OK)


COMMAND = Command(
    name="adopt",
    summary="move a recreated ~/.claude into a profile",
    description=(
        "Bring back what a tool wrote to ~/.claude (and ~/.claude.json) after the\n"
        "migration. adopt refuses, changing nothing, while the Claude Code CLI\n"
        "(claude) or the desktop app (Claude) runs, when the profile does not exist,\n"
        "or when ~/.claude is a symbolic link or not a directory.\n"
        "\n"
        "It lists every entry of ~/.claude: an entry whose name the profile does not\n"
        "have is moved into it; a directory both have is searched the same way; any\n"
        "other entry is a conflict, reported and left in place. ~/.claude.json\n"
        "becomes the profile's .claude.json when the profile has none. Directories\n"
        "of ~/.claude left empty are removed, and ~/.claude too when it ends empty.\n"
        "One confirmation covers the moves and the removals; when only conflicts\n"
        "remain nothing changes and nothing is asked.\n"
        "When neither ~/.claude nor ~/.claude.json exists, adopt says so and exits 0.\n"
        "\n"
        "The shell integration warns once per shell when ~/.claude exists again.\n"
        "\n"
        "The profile is --profile NAME, else the default profile.\n"
        "--dry-run lists the moves and conflicts only: it does not run pgrep."
    ),
    examples=[
        ("claude-sync adopt --dry-run", "list the moves and conflicts, change nothing"),
        ("claude-sync adopt", "list them and ask before moving"),
        ("claude-sync adopt --profile work --yes", "move into the work profile, no prompt"),
    ],
    exit_codes=[
        ExitCode.OK,
        ExitCode.ERROR,
        ExitCode.USAGE,
        ExitCode.CONFIRMATION_REQUIRED,
    ],
    kind="mutate",
    configure=configure,
    run=run,
)
