"""The profile a command acts on."""

import os
from dataclasses import dataclass
from pathlib import Path

from claude_sync import config, paths
from claude_sync.errors import ClaudeSyncError
from claude_sync.resolve import resolve


@dataclass(frozen=True)
class Target:
    name: str
    directory: Path


def resolve_target(profile: str | None) -> Target:
    """`--profile` when given, else the profile of the current directory.

    The profile directory must exist; the error suggests `profile create`.
    """
    if profile is not None:
        if not config.PROFILE_NAME.fullmatch(profile):
            raise ClaudeSyncError(f"invalid profile name {profile!r} (expected [a-z0-9][a-z0-9-]*)")
        name, directory = profile, paths.profile_dir(profile)
    else:
        resolution = resolve(".", config.load(), os.environ.get("CLAUDE_SYNC_OVERRIDE"))
        name, directory = resolution.profile, resolution.config_dir
    if not directory.is_dir():
        raise ClaudeSyncError(
            f"profile {name!r} does not exist ({directory}): "
            f"run `claude-sync profile create {name}`"
        )
    return Target(name, directory)
