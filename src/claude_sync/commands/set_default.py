from __future__ import annotations

import argparse
import sys

from claude_sync import config
from claude_sync.commands.map import RELOAD_REMINDER
from claude_sync.config import Config
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("profile", metavar="PROFILE", help="profile name ([a-z0-9][a-z0-9-]*)")


def run(args: argparse.Namespace, ctx: Context) -> int:
    if not config.PROFILE_NAME.fullmatch(args.profile):
        raise ClaudeSyncError(
            f"invalid profile name {args.profile!r} (expected [a-z0-9][a-z0-9-]*)"
        )
    cfg = config.load()
    if ctx.dry_run:
        print(f"would set default to {args.profile}")
        return int(ExitCode.OK)
    config.save(Config(args.profile, cfg.matches))
    print(RELOAD_REMINDER, file=sys.stderr)
    return int(ExitCode.OK)


COMMAND = Command(
    name="set-default",
    summary="set the profile used outside every mapped directory",
    description=(
        "Set the default profile in the configuration file, creating the file when\n"
        "needed. Mappings are kept."
    ),
    examples=[
        ("claude-sync set-default perso", "use perso outside mapped directories"),
        ("claude-sync set-default work --dry-run", "print the change, write nothing"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE],
    kind="mutate",
    configure=configure,
    run=run,
)
