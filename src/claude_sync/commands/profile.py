from __future__ import annotations

import argparse
import shutil
import subprocess
import uuid

from claude_sync import config, fileio, manifest, paths
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command

GITIGNORE = "/*\n!/.gitignore\n!/profile.toml\n"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", metavar="ACTION", choices=["create"], help="create")
    parser.add_argument("name", metavar="NAME", help="profile name ([a-z0-9][a-z0-9-]*)")
    parser.add_argument("--org-uuid", metavar="UUID", help="organization to tie the profile to")


def _check_uuid(value: str) -> None:
    try:
        valid = str(uuid.UUID(value)) == value.lower()
    except ValueError:
        valid = False
    if not valid:
        raise ClaudeSyncError(f"invalid organization UUID {value!r}")


def run(args: argparse.Namespace, ctx: Context) -> int:
    name = args.name
    if not config.PROFILE_NAME.fullmatch(name):
        raise ClaudeSyncError(f"invalid profile name {name!r} (expected [a-z0-9][a-z0-9-]*)")
    if args.org_uuid is not None:
        _check_uuid(args.org_uuid)
    directory = paths.profile_dir(name)
    if directory.exists():
        raise ClaudeSyncError(f"profile {name!r} already exists ({directory})")
    account = None if args.org_uuid is None else manifest.Account(args.org_uuid)
    if ctx.dry_run:
        print(f"would create {directory} (git repository, {manifest.MANIFEST_FILE})")
        if account is not None:
            print(f"would set org_uuid {account.org_uuid}")
        return int(ExitCode.OK)
    root = paths.profiles_root()
    if not root.exists():
        root.mkdir(mode=0o700, parents=True)
        root.chmod(0o700)
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    try:
        _init_git(directory)
        fileio.write_private(directory / ".gitignore", GITIGNORE)
        manifest.save(directory / manifest.MANIFEST_FILE, manifest.Manifest((), (), account))
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    print(f"created {directory}")
    return int(ExitCode.OK)


def _init_git(directory) -> None:
    try:
        subprocess.run(
            ["git", "init", "-q", str(directory)], check=True, capture_output=True, text=True
        )
    except FileNotFoundError as error:
        raise ClaudeSyncError("git is required to create a profile but was not found") from error
    except subprocess.CalledProcessError as error:
        raise ClaudeSyncError(f"git init failed: {error.stderr.strip()}") from error


COMMAND = Command(
    name="profile",
    summary="create a profile",
    description=(
        "profile create NAME creates the profile directory under the claude-sync\n"
        "configuration directory (mode 700), with an empty profile.toml and a git\n"
        "repository that tracks only profile.toml (settings.json may hold tokens).\n"
        "No commit is made. With --org-uuid the manifest gets an [account] table,\n"
        "used by apply and status to steer and check the sign-in. An existing\n"
        "profile makes the command fail and changes nothing."
    ),
    examples=[
        ("claude-sync profile create perso", "create the perso profile"),
        (
            "claude-sync profile create work --org-uuid 00000000-0000-0000-0000-000000000000",
            "create work, tied to an organization",
        ),
        ("claude-sync profile create work --dry-run", "print what would be created"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE],
    kind="mutate",
    configure=configure,
    run=run,
)
