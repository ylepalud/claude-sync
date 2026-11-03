"""The operating system facts and programs the migration depends on.

`pgrep` and `launchctl` are found on PATH, so tests can put stubs first.
"""

import os
import shutil
import subprocess
from pathlib import Path

from claude_sync.errors import ClaudeSyncError

# The Claude Code CLI and the Claude desktop app.
CLAUDE_PROCESSES = ("claude", "Claude")


def _run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise ClaudeSyncError(f"{command[0]} not found on PATH") from error


def running_claude() -> list[tuple[str, int]]:
    """The (name, pid) of every running `claude` and `Claude` process.

    `pgrep` exits 1 when nothing matches; any other failure raises, so an
    error is never taken for "nothing runs".
    """
    found = []
    for name in CLAUDE_PROCESSES:
        command = ["pgrep", "-x", name]
        result = _run(command)
        if result.returncode == 1:
            continue
        if result.returncode != 0:
            raise ClaudeSyncError(f"`{' '.join(command)}` failed: {result.stderr.strip()}")
        found += [(name, int(pid)) for pid in result.stdout.split()]
    return found


def refuse_if_claude_runs() -> None:
    """Raise, listing them, when a `claude` or `Claude` process runs."""
    running = running_claude()
    if running:
        listing = ", ".join(f"{name} {pid}" for name, pid in running)
        raise ClaudeSyncError(f"Claude is running ({listing}): quit it first")


def launchctl(*args: str) -> str:
    """Run `launchctl <args>`; its standard output. A failure raises with its stderr."""
    command = ["launchctl", *args]
    result = _run(command)
    if result.returncode != 0:
        raise ClaudeSyncError(f"`{' '.join(command)}` failed: {result.stderr.strip()}")
    return result.stdout


def uid() -> int:
    return os.getuid()


def _existing(path: Path) -> Path:
    """The nearest existing ancestor of `path` (itself when it exists), resolved."""
    path = Path(path).absolute()
    while not path.exists():
        path = path.parent
    return path.resolve()


def free_bytes(path: Path) -> int:
    """Free bytes on the file system holding `path` or its nearest existing ancestor."""
    return shutil.disk_usage(_existing(path)).free


def device(path: Path) -> int:
    """`st_dev` of `path` or of its nearest existing ancestor, resolved."""
    return os.stat(_existing(path)).st_dev
