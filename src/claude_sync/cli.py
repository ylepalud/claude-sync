from __future__ import annotations

import argparse
import os
import sys
import traceback

from claude_sync import __version__, registry
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError, ConfirmationRequired
from claude_sync.exit_codes import ExitCode

DESCRIPTION = "Isolate and switch between several Claude Code user profiles."
EXAMPLES = [
    ("claude-sync --version", "print the installed version"),
    ("claude-sync help --all", "print the help of every command"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-sync",
        description=DESCRIPTION,
        epilog=registry.render_epilog(EXAMPLES, list(ExitCode)),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"claude-sync {__version__}")
    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    for command in registry.COMMANDS:
        registry.add_command_parser(subparsers, command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    if args.command is None:
        parser.print_help()
        return int(ExitCode.OK)
    ctx = Context(
        json=getattr(args, "json", False),
        dry_run=getattr(args, "dry_run", False),
        yes=getattr(args, "yes", False),
        stdin_is_tty=sys.stdin.isatty(),
    )
    try:
        return int(args.command_spec.run(args, ctx))
    except ConfirmationRequired as e:
        _report(e)
        print("rerun with --yes", file=sys.stderr)
        return int(ExitCode.CONFIRMATION_REQUIRED)
    except ClaudeSyncError as e:
        _report(e)
        return int(ExitCode.ERROR)
    except Exception:
        _report("internal error, rerun with CLAUDE_SYNC_DEBUG=1 for details")
        return int(ExitCode.ERROR)


def _report(error: ClaudeSyncError | str) -> None:
    if os.environ.get("CLAUDE_SYNC_DEBUG") == "1":
        traceback.print_exc()
    print(f"claude-sync: error: {error}", file=sys.stderr)


def entry() -> None:
    sys.exit(main())
