from __future__ import annotations

import argparse
import os

from claude_sync import config
from claude_sync.context import Context
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command
from claude_sync.resolve import resolve


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("dir", nargs="?", default=".", metavar="DIR", help="directory (default: .)")


def run(args: argparse.Namespace, ctx: Context) -> int:
    resolution = resolve(args.dir, config.load(), os.environ.get("CLAUDE_SYNC_OVERRIDE"))
    ctx.emit(
        {
            "profile": resolution.profile,
            "source": resolution.source,
            "match": resolution.match,
            "config_dir": str(resolution.config_dir),
            "initialized": resolution.initialized,
        },
        resolution.profile,
    )
    return int(ExitCode.OK)


COMMAND = Command(
    name="which",
    summary="print the profile that applies to a directory",
    description=(
        "Print the profile that applies to DIR (default: the current directory): the\n"
        "longest configured path equal to DIR or a parent of it, else the default.\n"
        "CLAUDE_SYNC_OVERRIDE, when set to a valid profile name, wins."
    ),
    examples=[
        ("claude-sync which", "print the profile of the current directory"),
        ("claude-sync which ~/Dev/work/api --json", "print the resolution as JSON"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE],
    kind="read",
    configure=configure,
    run=run,
)
