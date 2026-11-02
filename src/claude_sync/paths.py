"""Filesystem locations and path normalization."""

import os
from pathlib import Path


def config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "claude-sync"


def config_file() -> Path:
    return config_home() / "config.toml"


def profiles_root() -> Path:
    return config_home() / "profiles"


def profile_dir(name: str) -> Path:
    return profiles_root() / name


def normalize(path: str | Path) -> Path:
    """Expand `~`, make absolute against the cwd and resolve symlinks."""
    return (Path.cwd() / Path(path).expanduser()).resolve(strict=False)


def key(path: str | Path) -> Path:
    """The identity of a path: normalized, in its on-disk spelling."""
    return on_disk(normalize(path))


def display(path: str | Path) -> str:
    """`~/...` when under the home directory, the absolute path otherwise."""
    p = Path(path)
    home = Path.home().resolve()
    try:
        relative = p.relative_to(home)
    except ValueError:
        return str(p)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


def on_disk(path: Path) -> Path:
    """Rebuild `path` with the spelling each directory entry has on disk.

    Per component: the entry equal to it, else the one equal under `casefold()`,
    else the component as given (and the rest of the path unchanged).
    """
    result = Path(path.anchor)
    for part in path.parts[1:]:
        try:
            names = os.listdir(result)
        except OSError:
            names = []
        if part in names:
            found = part
        else:
            found = next((n for n in names if n.casefold() == part.casefold()), part)
        result = result / found
    return result
