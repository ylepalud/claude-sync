from __future__ import annotations

import argparse
import sys
from pathlib import Path

from claude_sync import config, paths
from claude_sync.config import Config, Match
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command

RELOAD_REMINDER = "run claude-sync-reload in open shells to apply"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("dir", metavar="DIR", help="directory to map")
    parser.add_argument("profile", metavar="PROFILE", help="profile name ([a-z0-9][a-z0-9-]*)")


def run(args: argparse.Namespace, ctx: Context) -> int:
    if not config.PROFILE_NAME.fullmatch(args.profile):
        raise ClaudeSyncError(
            f"invalid profile name {args.profile!r} (expected [a-z0-9][a-z0-9-]*)"
        )
    cfg = config.load()
    target = paths.normalize(args.dir)
    if target == Path("/"):
        raise ClaudeSyncError("cannot map the root directory /")
    if not target.is_dir():
        raise ClaudeSyncError(f"{args.dir}: not an existing directory")
    target = paths.key(args.dir)
    stored = paths.display(target)
    existing = next((m for m in cfg.matches if paths.key(m.path) == target), None)
    if existing is not None and existing.profile == args.profile:
        print(f"already mapped: {stored} -> {args.profile}")
        return int(ExitCode.OK)
    verb = "map" if existing is None else "replace"
    if ctx.dry_run:
        print(f"would {verb} {stored} -> {args.profile}")
        return int(ExitCode.OK)
    if existing is not None and not ctx.confirm(
        f"{stored} is already mapped to {existing.profile}; replace it with {args.profile}?"
    ):
        return int(ExitCode.OK)
    match = Match(stored, args.profile)
    if existing is None:
        matches = (*cfg.matches, match)
    else:
        matches = tuple(match if m is existing else m for m in cfg.matches)
    config.save(Config(cfg.default, matches))
    print(RELOAD_REMINDER, file=sys.stderr)
    return int(ExitCode.OK)


COMMAND = Command(
    name="map",
    summary="map a directory to a profile",
    description=(
        "Map DIR (and everything below it) to PROFILE in the configuration file,\n"
        "creating the file when needed. DIR must be an existing directory other\n"
        "than /; it is stored with its on-disk spelling (letter case included).\n"
        "Mapping a directory to the profile it already has prints\n"
        "'already mapped' and writes nothing. Replacing the profile of an already\n"
        "mapped directory needs a confirmation."
    ),
    examples=[
        ("claude-sync map ~/Dev/work work", "use the work profile under ~/Dev/work"),
        ("claude-sync map ~/dev/work work", "stored as ~/Dev/work on a case-insensitive disk"),
        ("claude-sync map ~/Dev/work other --yes", "replace an existing mapping"),
        ("claude-sync map ~/Dev/work work --dry-run", "print the change, write nothing"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE, ExitCode.CONFIRMATION_REQUIRED],
    kind="mutate",
    configure=configure,
    run=run,
)
