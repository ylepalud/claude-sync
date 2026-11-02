from __future__ import annotations

import argparse

from claude_sync import config, zsh
from claude_sync.context import Context
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("shell", metavar="SHELL", choices=["zsh"], help="shell name (only: zsh)")


def run(args: argparse.Namespace, ctx: Context) -> int:
    print(zsh.render(config.load()), end="")
    return int(ExitCode.OK)


COMMAND = Command(
    name="shell-init",
    summary="print the shell code that applies the profile on every directory change",
    description=(
        "Print a zsh snippet that sets CLAUDE_SYNC_PROFILE, and CLAUDE_CONFIG_DIR when\n"
        "the profile directory exists, on start and after every directory change. The\n"
        "mappings are embedded, so a directory change runs no external process. Add\n"
        "the eval line to ~/.zshrc after oh-my-zsh and the theme are loaded.\n"
        "\n"
        "The snippet shows claude:<profile> at the start of RPROMPT (with ? when the\n"
        "profile is not initialized); set CLAUDE_SYNC_PROMPT=0 before it to disable\n"
        "that. It also defines claude-sync-use PROFILE (override in this shell),\n"
        "claude-sync-use --auto (back to the mappings) and claude-sync-reload (apply\n"
        "configuration changes). Only zsh is supported; there is no --json form."
    ),
    examples=[
        ('eval "$(claude-sync shell-init zsh)"', "line to add to ~/.zshrc"),
        ("claude-sync shell-init zsh", "print the snippet to review it"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE],
    kind="doc",
    configure=configure,
    run=run,
)
