from __future__ import annotations

import argparse
import shlex
import sys

from claude_sync import manifest, settings, sync, target
from claude_sync.claude_cli import ClaudeCli
from claude_sync.context import Context
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command

ACCEPT_HINT = "accept with: claude-sync import"
UPSTREAM_KINDS = ("version", "commit")


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile", metavar="NAME", help="profile to converge (default: current directory)"
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="also remove the plugins and marketplaces the manifest does not list",
    )


def _command_line(action: sync.Action) -> str:
    return "claude " + shlex.join(action.args)


def _question(actions: list[sync.Action]) -> str:
    listing = "\n".join(f"  {_command_line(a)}" for a in actions if a.confirm)
    return (
        "Removing a marketplace uninstalls its plugins and deletes their data. "
        f"These commands will run:\n{listing}\nContinue?"
    )


def run(args: argparse.Namespace, ctx: Context) -> int:
    profile = target.resolve_target(args.profile)
    declared = manifest.load(profile.directory / manifest.MANIFEST_FILE)
    cli = ClaudeCli(profile.directory)
    observed = sync.observe(cli, profile.directory)
    actions = sync.plan(declared, observed, args.prune)
    org = declared.account.org_uuid if declared.account else None
    write_guide = org is not None and observed.guide != org
    if ctx.dry_run:
        for action in actions:
            print(f"would run: {_command_line(action)}")
        if write_guide:
            print(f"would write forceLoginMethod and forceLoginOrgUUID to {profile.directory}")
        return int(ExitCode.OK)
    if any(a.confirm for a in actions) and not ctx.confirm(_question(actions)):
        print("cancelled", file=sys.stderr)
        return int(ExitCode.OK)
    for action in actions:
        cli.run(action.args)
    if write_guide:
        settings.apply_guide(profile.directory, org)
    moved = [
        d
        for d in sync.diff(declared, sync.observe(cli, profile.directory))
        if d.kind in UPSTREAM_KINDS
    ]
    if moved:
        for d in moved:
            print(f"{d.kind} {d.subject}: expected {d.expected!r}, found {d.actual!r}")
        print(ACCEPT_HINT)
        return int(ExitCode.DRIFT)
    return int(ExitCode.OK)


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
        "The profile is --profile NAME, else the profile of the current directory;\n"
        "its directory must exist (claude-sync profile create NAME)."
    ),
    examples=[
        ("claude-sync apply --profile work", "converge the work profile"),
        ("claude-sync apply --profile work --dry-run", "print the claude commands, run none"),
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
