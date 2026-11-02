from __future__ import annotations

import argparse
import platform

from claude_sync import __version__
from claude_sync.context import Context
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command


def configure(parser: argparse.ArgumentParser) -> None:
    pass


def run(args: argparse.Namespace, ctx: Context) -> int:
    ctx.emit(
        {"version": __version__, "python": platform.python_version()},
        f"claude-sync {__version__}",
    )
    return int(ExitCode.OK)


COMMAND = Command(
    name="version",
    summary="print the installed version",
    description="Print the installed claude-sync version.",
    examples=[
        ("claude-sync version", "print `claude-sync <version>`"),
        ("claude-sync version --json", "print the version and the Python version as JSON"),
    ],
    exit_codes=[ExitCode.OK],
    kind="read",
    configure=configure,
    run=run,
)
