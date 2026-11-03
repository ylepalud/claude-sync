from __future__ import annotations

import argparse
import sys
from pathlib import Path

from claude_sync import converge, manifest, paths, target
from claude_sync.context import Context
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source", metavar="DIR", help="read the configuration in DIR instead of the profile"
    )
    parser.add_argument(
        "--output", metavar="FILE", help="write to FILE, or to standard output with '-'"
    )
    parser.add_argument(
        "--profile", metavar="NAME", help="profile to read and write (default: current directory)"
    )


def run(args: argparse.Namespace, ctx: Context) -> int:
    to_stdout = args.output == "-"
    needs_profile = args.source is None or args.output is None
    profile = target.resolve_target(args.profile) if needs_profile else None
    source = paths.normalize(args.source) if args.source is not None else profile.directory
    destination = (
        None
        if to_stdout
        else Path(args.output)
        if args.output is not None
        else profile.directory / manifest.MANIFEST_FILE
    )
    account = None
    if destination is not None and destination.exists():
        account = manifest.load(destination).account
    imported = converge.build_manifest(source, account)
    if to_stdout:
        sys.stdout.write(manifest.render(imported))
        return int(ExitCode.OK)
    if ctx.dry_run:
        print(f"would write {destination}")
        return int(ExitCode.OK)
    if destination.exists() and not ctx.confirm(f"{destination} exists; overwrite it?"):
        print("cancelled", file=sys.stderr)
        return int(ExitCode.OK)
    manifest.save(destination, imported)
    print(f"wrote {destination}")
    return int(ExitCode.OK)


COMMAND = Command(
    name="import",
    summary="write a manifest from the installed marketplaces and plugins",
    description=(
        "Read the user-scope plugins and the marketplaces of a configuration with\n"
        "the claude CLI and write them as a profile manifest. A marketplace keeps\n"
        "the ref the CLI reports; when its local copy is a git repository of its\n"
        "own and the source is not a path, the current commit is recorded. A path\n"
        "source under the home directory is written with '~'. Marketplaces whose\n"
        "source is a file or claude.ai are skipped with a warning on standard\n"
        "error, with their plugins.\n"
        "\n"
        "--source DIR reads the configuration in DIR (for example ~/.claude)\n"
        "instead of the profile. The result goes to --output FILE, to standard\n"
        "output with '--output -' (only the manifest is printed there), or by\n"
        "default to profile.toml of the target profile: --profile NAME, else the\n"
        "profile of the current directory. That profile directory must exist\n"
        "(claude-sync profile create NAME). An [account] table already in the\n"
        "written file is kept; overwriting a file needs a confirmation."
    ),
    examples=[
        ("claude-sync import --source ~/.claude --output -", "print the manifest of ~/.claude"),
        ("claude-sync import --profile work", "refresh profile.toml of the work profile"),
        ("claude-sync import --profile work --yes", "overwrite without asking"),
        ("claude-sync import --output manifest.toml --dry-run", "print where it would write"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE, ExitCode.CONFIRMATION_REQUIRED],
    kind="mutate",
    configure=configure,
    run=run,
)
