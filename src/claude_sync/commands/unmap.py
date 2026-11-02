from __future__ import annotations

import argparse
import sys

from claude_sync import config, paths
from claude_sync.commands.map import RELOAD_REMINDER
from claude_sync.config import Config
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("dir", metavar="DIR", help="mapped directory to remove")


def run(args: argparse.Namespace, ctx: Context) -> int:
    cfg = config.load()
    target = paths.normalize(args.dir)
    stored = paths.display(target)
    kept = tuple(m for m in cfg.matches if paths.normalize(m.path) != target)
    if len(kept) == len(cfg.matches):
        raise ClaudeSyncError(f"no mapping for {stored}")
    if ctx.dry_run:
        print(f"would unmap {stored}")
        return int(ExitCode.OK)
    config.save(Config(cfg.default, kept))
    print(RELOAD_REMINDER, file=sys.stderr)
    return int(ExitCode.OK)


COMMAND = Command(
    name="unmap",
    summary="remove the mapping of a directory",
    description=(
        "Remove the mapping whose path is DIR from the configuration file.\n"
        "It fails when DIR has no mapping."
    ),
    examples=[
        ("claude-sync unmap ~/Dev/work", "stop mapping ~/Dev/work"),
        ("claude-sync unmap ~/Dev/work --dry-run", "print the change, write nothing"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE],
    kind="mutate",
    configure=configure,
    run=run,
)
