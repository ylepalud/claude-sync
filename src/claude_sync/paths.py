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


def display(path: str | Path) -> str:
    """`~/...` when under the home directory, the absolute path otherwise."""
    p = Path(path)
    home = Path.home().resolve()
    try:
        relative = p.relative_to(home)
    except ValueError:
        return str(p)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"
