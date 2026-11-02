"""Command registry: one `Command` per CLI command, and the parser builder."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from claude_sync.exit_codes import ExitCode

if TYPE_CHECKING:
    from claude_sync.context import Context

COMMAND_MODULES = ("version", "help")


@dataclass(frozen=True)
class Command:
    name: str
    summary: str
    description: str
    examples: list[tuple[str, str]]
    exit_codes: list[ExitCode]
    kind: Literal["read", "mutate", "doc"]
    configure: Callable[[argparse.ArgumentParser], None]
    run: Callable[[argparse.Namespace, Context], int]


def render_epilog(examples: Sequence[tuple[str, str]], exit_codes: Sequence[ExitCode]) -> str:
    lines = ["Examples:"]
    for command_line, explanation in examples:
        lines.append(f"  $ {command_line}")
        lines.append(f"      {explanation}")
    lines.append("")
    lines.append("Exit codes:")
    for code in exit_codes:
        lines.append(f"  {int(code)}  {code.description}")
    return "\n".join(lines)


def add_command_parser(subparsers: Any, command: Command) -> argparse.ArgumentParser:
    """Create the subparser of `command`, adding the flags its kind requires."""
    parser = subparsers.add_parser(
        command.name,
        help=command.summary,
        description=command.description,
        epilog=render_epilog(command.examples, command.exit_codes),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    command.configure(parser)
    if command.kind == "read":
        parser.add_argument("--json", action="store_true", help="print one JSON document")
    elif command.kind == "mutate":
        parser.add_argument(
            "--dry-run", action="store_true", help="print the planned actions, change nothing"
        )
        parser.add_argument("--yes", action="store_true", help="answer every confirmation")
    parser.set_defaults(command_spec=command)
    return parser


def __getattr__(name: str) -> list[Command]:
    # Lazy so that command modules can import `Command` from here without a cycle.
    if name == "COMMANDS":
        from importlib import import_module

        commands = [
            import_module(f"claude_sync.commands.{module}").COMMAND for module in COMMAND_MODULES
        ]
        globals()["COMMANDS"] = commands
        return commands
    raise AttributeError(name)
