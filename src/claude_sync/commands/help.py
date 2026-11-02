from __future__ import annotations

import argparse

from claude_sync import registry
from claude_sync.context import Context
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command

RULE = "-" * 72


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "topic",
        nargs="?",
        metavar="COMMAND",
        choices=[c.name for c in registry.COMMANDS],
        help="command to describe (default: the top-level help)",
    )
    parser.add_argument("--all", action="store_true", help="print the help of every command")


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def run(args: argparse.Namespace, ctx: Context) -> int:
    from claude_sync.cli import build_parser

    parser = build_parser()
    subparsers = _subparsers(parser)
    if args.all:
        blocks = [parser.format_help()]
        blocks += [subparsers[c.name].format_help() for c in registry.COMMANDS]
        print(f"\n{RULE}\n\n".join(blocks), end="")
    elif args.topic:
        print(subparsers[args.topic].format_help(), end="")
    else:
        print(parser.format_help(), end="")
    return int(ExitCode.OK)


COMMAND = Command(
    name="help",
    summary="show the help of a command or of every command",
    description="Show the help of one command, or with --all the help of every command.",
    examples=[
        ("claude-sync help", "print the top-level help"),
        ("claude-sync help version", "same output as `claude-sync version --help`"),
        ("claude-sync help --all", "print the top-level help then each command's help"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.USAGE],
    kind="doc",
    configure=configure,
    run=run,
)
