from __future__ import annotations

import argparse

from claude_sync import converge, target
from claude_sync.context import Context
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile", metavar="NAME", help="profile to converge (default: current directory)"
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="also remove the plugins, marketplaces and skill links the manifest does not list",
    )


# Kept as a module attribute for callers and tests that format the confirmation.
_question = converge.question


def run(args: argparse.Namespace, ctx: Context) -> int:
    profile = target.resolve_target(args.profile)
    return converge.converge(profile.directory, ctx, args.prune)


COMMAND = Command(
    name="apply",
    summary="converge a profile to its manifest",
    description=(
        "Make a profile match its profile.toml as far as the claude CLI allows: add\n"
        "missing marketplaces (with #REF when a ref is declared), install missing\n"
        "plugins, enable or disable plugins to match, and write the account guide\n"
        "keys (forceLoginMethod, forceLoginOrgUUID) when the manifest has an\n"
        "[account]. A marketplace installed with another source or ref is removed\n"
        "and added again, and its plugins reinstalled with their declared enabled\n"
        "state. Removing a marketplace uninstalls its plugins and deletes their\n"
        "data, so every such step is listed in one confirmation. Plugins and\n"
        "marketplaces the manifest does not list are removed only with --prune,\n"
        "after the same confirmation.\n"
        "\n"
        "apply never approves a marketplace-declared command for you: when the CLI\n"
        "asks for that, apply stops and shows the CLI message. The first failing\n"
        "claude command stops apply and is shown with its error output. When a\n"
        "plugin version or a marketplace commit still differs from the manifest\n"
        "afterwards (the upstream moved), apply reports it and exits 4; accept it\n"
        "with claude-sync import.\n"
        "\n"
        "Skills are converged after the plugins: apply clones each skill source\n"
        "once into ~/.config/claude-sync/sources/<name>, checks out its recorded\n"
        "commit (detached) and links skills/<skill> to the clone. A link pointing\n"
        "elsewhere is replaced after the confirmation; with --prune, links into\n"
        "the sources directory that the manifest does not list are removed, and\n"
        "nothing else. A real file or directory in the way, a clone with local\n"
        "changes, or another profile declaring the same source name differently\n"
        "stops apply with exit 1 before any change. A skill whose directory has\n"
        "another tree than recorded is reported like a moved plugin (exit 4).\n"
        "\n"
        "The profile is --profile NAME, else the profile of the current directory;\n"
        "its directory must exist (claude-sync profile create NAME)."
    ),
    examples=[
        ("claude-sync apply --profile work", "converge the work profile"),
        (
            "claude-sync apply --profile work --dry-run",
            "print the claude and git commands and skill links, run none",
        ),
        ("claude-sync apply --profile work --prune", "also unlink skills the manifest dropped"),
        ("claude-sync apply --profile work --prune --yes", "also remove unlisted items, no prompt"),
    ],
    exit_codes=[
        ExitCode.OK,
        ExitCode.ERROR,
        ExitCode.USAGE,
        ExitCode.CONFIRMATION_REQUIRED,
        ExitCode.DRIFT,
    ],
    kind="mutate",
    configure=configure,
    run=run,
)
