"""Tool requirements: check them, merge them across profiles, build fix commands."""

import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass

from claude_sync import config, manifest, paths
from claude_sync.errors import ClaudeSyncError
from claude_sync.manifest import Manifest, Tool

CHECK_TIMEOUT = 10
BREW_LIST_TIMEOUT = 30
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)+")


@dataclass(frozen=True)
class ToolStatus:
    name: str
    status: str
    """`ok`, `missing` or `too-old`."""
    installed: str | None
    """The installed dotted version, when it could be read."""
    required: str | None


@dataclass(frozen=True)
class Requirement:
    """A tool merged across profiles, with the profiles (in name order) that declare it."""

    tool: Tool
    profiles: tuple[str, ...]


@dataclass(frozen=True)
class Conflict:
    """Different recipes for one tool, as (profile, recipe) in profile name order."""

    name: str
    recipes: tuple[tuple[str, str], ...]


def parse_version(text: str) -> tuple[int, ...] | None:
    """The first dotted number (two or more components) in `text`."""
    found = _VERSION.search(text)
    return tuple(int(part) for part in found.group().split(".")) if found else None


def _older(installed: tuple[int, ...], required: tuple[int, ...]) -> bool:
    width = max(len(installed), len(required))
    pad = lambda v: v + (0,) * (width - len(v))  # noqa: E731
    return pad(installed) < pad(required)


def check(tool: Tool) -> ToolStatus:
    """Run the tool's check command (no shell) and compare its version with the minimum."""
    argv = shlex.split(tool.check or f"{tool.name} --version")
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=CHECK_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ToolStatus(tool.name, "missing", None, tool.version)
    if result.returncode != 0:
        return ToolStatus(tool.name, "missing", None, tool.version)
    found = _VERSION.search(result.stdout)
    installed = found.group() if found else None
    if tool.version is not None:
        required = parse_version(tool.version)
        current = parse_version(installed) if installed else None
        if current is None or _older(current, required):
            return ToolStatus(tool.name, "too-old", installed, tool.version)
    return ToolStatus(tool.name, "ok", installed, tool.version)


def merge(
    manifests_by_profile: dict[str, Manifest],
) -> tuple[list[Requirement], list[Conflict]]:
    """Merge the tools of every profile by name.

    The highest minimum wins; the check command and the recipe come from the
    first profile, in name order, that declares them; other different recipes
    are conflicts.
    """
    declared: dict[str, list[tuple[str, Tool]]] = {}
    for profile in sorted(manifests_by_profile):
        for tool in manifests_by_profile[profile].tools:
            declared.setdefault(tool.name, []).append((profile, tool))
    requirements, conflicts = [], []
    for name in sorted(declared):
        entries = declared[name]
        versions = [t.version for _, t in entries if t.version is not None]
        highest = None
        for version in versions:
            if highest is None or _older(parse_version(highest), parse_version(version)):
                highest = version
        check_command = next((t.check for _, t in entries if t.check is not None), None)
        recipes = tuple((p, t.install) for p, t in entries if t.install is not None)
        install = recipes[0][1] if recipes else None
        requirements.append(
            Requirement(Tool(name, highest, check_command, install), tuple(p for p, _ in entries))
        )
        if len({recipe for _, recipe in recipes}) > 1:
            conflicts.append(Conflict(name, recipes))
    return requirements, conflicts


def fix_command(recipe: str) -> list[str]:
    """The command that installs or upgrades a tool whatever its current state.

    Managers are shown by absolute path; `brew` picks `install` or `upgrade`
    from `brew list <formula>`.
    """
    kind, _, package = recipe.partition(":")
    if kind == "script":
        return ["/bin/sh", "-c", package]
    manager = shutil.which(kind)
    if manager is None:
        raise ClaudeSyncError(f"{kind} not found on PATH, needed by {recipe}")
    if kind == "brew":
        return [manager, "upgrade" if _brew_lists(manager, package) else "install", package]
    if kind == "npm":
        return [manager, "install", "-g", f"{package}@latest"]
    if kind == "uv":
        return [manager, "tool", "install", "--upgrade", package]
    return [manager, "install", "--force", package]


def _brew_lists(brew: str, formula: str) -> bool:
    try:
        result = subprocess.run(
            [brew, "list", formula],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=BREW_LIST_TIMEOUT,
        )
    except subprocess.TimeoutExpired as error:
        raise ClaudeSyncError(
            f"brew list {formula} timed out after {BREW_LIST_TIMEOUT} seconds"
        ) from error
    if result.returncode not in (0, 1):
        raise ClaudeSyncError(
            f"brew list {formula} failed with exit code {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return result.returncode == 0


def resolved_path(name: str) -> str | None:
    """The absolute path of the binary found first on PATH (the one that shadows others)."""
    return shutil.which(name)


def all_profiles() -> list[str]:
    """The names of the profile directories holding a `profile.toml`, in order."""
    root = paths.profiles_root()
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if config.PROFILE_NAME.fullmatch(entry.name) and (entry / manifest.MANIFEST_FILE).is_file()
    )
