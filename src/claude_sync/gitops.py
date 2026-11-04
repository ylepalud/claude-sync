"""A thin layer over the `git` command, for skill source clones."""

import re
import subprocess
from pathlib import Path

from claude_sync.errors import ClaudeSyncError

_GITHUB_URL = re.compile(r"https://github\.com/([A-Za-z0-9._-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?")


def run(*args: str, cwd: Path | None = None) -> str:
    """Run `git <args>` and return its stripped stdout; raise on failure."""
    command = ["git", *args]
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as error:
        raise ClaudeSyncError(f"{' '.join(command)}: cannot run: {error}") from error
    if done.returncode != 0:
        raise ClaudeSyncError(f"{' '.join(command)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def clone(url: str, dest: Path, ref: str | None) -> None:
    branch = ["--branch", ref] if ref is not None else []
    run("clone", "--quiet", *branch, url, str(dest))


def fetch(dest: Path) -> None:
    run("fetch", "--quiet", "--tags", "origin", cwd=dest)


def checkout(dest: Path, commit: str) -> None:
    run("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", commit, cwd=dest)


def head(dest: Path) -> str:
    return run("rev-parse", "HEAD", cwd=dest)


def dirty(dest: Path) -> bool:
    return bool(run("status", "--porcelain", cwd=dest))


def remote_url(dest: Path) -> str | None:
    """The URL of `origin`, or None without one."""
    try:
        return run("remote", "get-url", "origin", cwd=dest) or None
    except ClaudeSyncError:
        return None


def toplevel(path: Path) -> Path | None:
    """The root of the repository holding `path`, or None outside any."""
    path = Path(path)
    if not path.is_dir():
        return None
    try:
        return Path(run("rev-parse", "--show-toplevel", cwd=path))
    except ClaudeSyncError:
        return None


def tree_at(dest: Path, commit: str, path: str) -> str | None:
    """The tree (or blob) hash of `path` at `commit`, or None when absent."""
    try:
        return run("rev-parse", "--verify", "--quiet", f"{commit}:{path}", cwd=dest)
    except ClaudeSyncError:
        return None


def resolve_ref(dest: Path, ref: str | None) -> str:
    """The revision for `ref` that is current after a fetch.

    `origin/<ref>` when that remote-tracking branch exists, else `refs/tags/<ref>`;
    `origin/HEAD` (the remote default branch) for None. Raises when nothing matches.
    """
    if ref is None:
        return "origin/HEAD"
    for candidate in (f"origin/{ref}", f"refs/tags/{ref}"):
        if _exists(dest, candidate):
            return candidate
    raise ClaudeSyncError(f"unknown ref {ref!r} in {dest}")


def _exists(dest: Path, revision: str) -> bool:
    try:
        run("rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}", cwd=dest)
    except ClaudeSyncError:
        return False
    return True


def commits(dest: Path, ref: str | None) -> list[str]:
    """Every commit reachable from `ref` (see `resolve_ref`), newest first."""
    return run("rev-list", resolve_ref(dest, ref), cwd=dest).splitlines()


def is_ancestor(dest: Path, commit: str, ref: str | None) -> bool:
    """Whether `commit` is reachable from `ref` (see `resolve_ref`)."""
    revision = resolve_ref(dest, ref)
    try:
        run("merge-base", "--is-ancestor", commit, revision, cwd=dest)
    except ClaudeSyncError:
        return False
    return True


def current_ref(dest: Path) -> str | None:
    """The checked-out branch, or None when HEAD is detached."""
    try:
        return run("symbolic-ref", "--short", "--quiet", "HEAD", cwd=dest) or None
    except ClaudeSyncError:
        return None


def url_of(source: str) -> str:
    kind, _, rest = source.partition(":")
    if kind == "github":
        return f"https://github.com/{rest}.git"
    return rest


def source_of(url: str) -> str:
    match = _GITHUB_URL.fullmatch(url)
    if match:
        return f"github:{match.group(1)}"
    return f"git:{url}"
