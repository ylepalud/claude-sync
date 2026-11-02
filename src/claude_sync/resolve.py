"""Decide which profile applies to a directory."""

from dataclasses import dataclass
from pathlib import Path

from claude_sync import paths
from claude_sync.config import PROFILE_NAME, Config
from claude_sync.errors import ClaudeSyncError


@dataclass(frozen=True)
class Resolution:
    profile: str
    source: str  # "override", "match" or "default"
    match: str | None  # the matching configured path, as stored
    config_dir: Path
    initialized: bool


def resolve(directory: str | Path, config: Config, override: str | None) -> Resolution:
    if override is not None:
        if not PROFILE_NAME.fullmatch(override):
            raise ClaudeSyncError(
                f"invalid CLAUDE_SYNC_OVERRIDE {override!r} (expected [a-z0-9][a-z0-9-]*)"
            )
        return _build(override, "override", None)
    target = paths.normalize(directory)
    best = None
    best_length = -1
    for match in config.matches:
        candidate = paths.normalize(match.path)
        length = len(candidate.parts)
        applies = target == candidate or candidate in target.parents
        if applies and length > best_length:
            best, best_length = match, length
    if best is None:
        return _build(config.default, "default", None)
    return _build(best.profile, "match", best.path)


def _build(profile: str, source: str, match: str | None) -> Resolution:
    config_dir = paths.profile_dir(profile)
    return Resolution(profile, source, match, config_dir, config_dir.is_dir())
