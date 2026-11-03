"""The file-system steps of moving `~/.claude` into a profile and back.

Each step is a small function; the `init` and `uninstall` commands order them.
"""

import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from claude_sync.errors import ClaudeSyncError
from claude_sync.fileio import write_private
from claude_sync.sync import Observed

_PROGRESS_EVERY = 1000


def _list(archive: Path) -> list[str]:
    with tarfile.open(archive) as tar:
        return tar.getnames()


def _storable(member: tarfile.TarInfo | None) -> bool:
    """Whether a member is a kind `extract_backup` restores."""
    return member is not None and (
        member.isreg() or member.isdir() or member.issym() or member.islnk()
    )


def backup(paths: Iterable[Path], dest: Path) -> Path:
    """Write a gzip tar of `paths` to `dest/<UTC timestamp>.tar.gz` and list it back.

    Members are named after each path's last component (`.claude/...`,
    `.claude.json`); symbolic links are stored as links, never followed.
    Sockets, FIFOs and devices are skipped, each named on stderr. The archive
    has mode 600 and `dest` mode 700 (also when it exists). One progress line
    per 1000 members goes to stderr. A failed write leaves no archive.
    """
    dest = Path(dest)
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    archive = dest / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".tar.gz")
    fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    count = 0

    def add(tar: tarfile.TarFile, path: str, arcname: str) -> None:
        nonlocal count
        member = tar.gettarinfo(path, arcname)
        if not _storable(member):
            print(f"backup: skipped special file {path}", file=sys.stderr)
            return
        if member.isreg():
            with open(path, "rb") as handle:
                tar.addfile(member, handle)
        else:
            tar.addfile(member)
        count += 1
        if count % _PROGRESS_EVERY == 0:
            print(f"backup: {count} entries", file=sys.stderr)
        if member.isdir():
            for name in sorted(os.listdir(path)):
                add(tar, os.path.join(path, name), f"{arcname}/{name}")

    try:
        with (
            os.fdopen(fd, "wb") as raw,
            tarfile.open(fileobj=raw, mode="w:gz", compresslevel=6, dereference=False) as tar,
        ):
            for path in paths:
                add(tar, str(path), Path(path).name)
    except BaseException:
        archive.unlink(missing_ok=True)
        raise
    try:
        _list(archive)
    except (tarfile.TarError, OSError, EOFError) as error:
        raise ClaudeSyncError(f"backup {archive} cannot be listed: {error}") from error
    return archive


def _refused(member: tarfile.TarInfo, reason: str) -> ClaudeSyncError:
    return ClaudeSyncError(f"backup member {member.name!r} refused: {reason}")


def _validate(members: list[tarfile.TarInfo]) -> None:
    """Refuse an archive holding anything a backup of claude-sync cannot hold.

    Names are relative without `..`, under `.claude` or equal to
    `.claude.json`, unique, of a regular file, directory, symbolic link or
    hard link; a hard link names an earlier regular file.
    """
    regular_files: set[str] = set()
    seen: set[str] = set()
    for member in members:
        name = member.name
        parts = PurePosixPath(name).parts
        if name.startswith("/") or ".." in parts:
            raise _refused(member, "absolute or escaping name")
        if not parts or (parts[0] != ".claude" and parts != (".claude.json",)):
            raise _refused(member, "not under .claude or .claude.json")
        if not _storable(member):
            raise _refused(member, "not a file, directory or link")
        key = str(PurePosixPath(name))
        if key in seen:
            raise _refused(member, "duplicate name")
        if member.islnk() and str(PurePosixPath(member.linkname)) not in regular_files:
            raise _refused(member, f"hard link to {member.linkname!r}, no earlier file")
        seen.add(key)
        if member.isreg():
            regular_files.add(key)


def _inside(path: str, root: str, member: tarfile.TarInfo) -> None:
    real = os.path.realpath(path)
    if real != root and not real.startswith(root + os.sep):
        raise _refused(member, f"it would be written outside the destination, at {real}")


def _extract_member(tar: tarfile.TarFile, member: tarfile.TarInfo, staging: str) -> None:
    path = os.path.join(staging, member.name)
    _inside(path, staging, member)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if member.isdir():
        os.makedirs(path, exist_ok=True)
    elif member.issym():
        os.symlink(member.linkname, path)
    elif member.islnk():
        target = os.path.join(staging, member.linkname)
        _inside(target, staging, member)
        os.link(target, path)
    else:
        source = tar.extractfile(member)
        with source, open(path, "xb") as out:
            shutil.copyfileobj(source, out)
        os.chmod(path, member.mode & 0o777)
        os.utime(path, (member.mtime, member.mtime))


def extract_backup(archive: Path, dest: Path) -> None:
    """Restore a backup's `.claude` and `.claude.json` into `dest`.

    The whole archive is checked first (see `_validate`), then extracted member
    by member into a fresh staging directory inside `dest`, each destination
    (and hard link target) checked to resolve inside it. Only when every member
    succeeded are the top-level entries renamed into `dest`; one that `dest`
    already has refuses the restore. A refusal raises `ClaudeSyncError` naming
    the member and leaves `dest` as it was. Symbolic link texts are kept as
    stored, absolute ones included.
    """
    dest = Path(dest)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        _validate(members)
        staging = os.path.realpath(tempfile.mkdtemp(prefix=".claude-sync-restore-", dir=dest))
        try:
            directories = []
            for member in members:
                try:
                    _extract_member(tar, member, staging)
                except OSError as error:
                    raise _refused(member, str(error)) from error
                if member.isdir():
                    directories.append(member)
            for member in reversed(directories):
                path = os.path.join(staging, member.name)
                os.chmod(path, member.mode & 0o777)
                os.utime(path, (member.mtime, member.mtime))
            entries = sorted(os.listdir(staging))
            present = [name for name in entries if os.path.lexists(dest / name)]
            if present:
                raise ClaudeSyncError(
                    f"cannot restore {', '.join(present)}: it exists in {dest}; move it aside"
                )
            for name in entries:
                os.rename(os.path.join(staging, name), dest / name)
        finally:
            _remove_tree(staging)


def _remove_tree(path: str) -> None:
    """Remove a staging tree, making each directory usable before descending into it.

    Symbolic links are neither followed nor changed.
    """
    os.chmod(path, 0o700)
    for directory, dirnames, _ in os.walk(path):
        for name in dirnames:
            child = os.path.join(directory, name)
            if not os.path.islink(child):
                os.chmod(child, 0o700)
    shutil.rmtree(path, ignore_errors=True)


# What `claude plugin` rebuilds: caches, marketplace copies and their lists.
PLUGIN_CACHES = (
    "plugins/cache",
    "plugins/marketplaces",
    "plugins/installed_plugins.json",
    "plugins/known_marketplaces.json",
)


def remove_plugin_caches(profile_dir: Path) -> None:
    """Remove the plugin caches and lists; `plugins/data` and the rest stay.

    A missing entry is skipped; a symbolic link is removed, never followed.
    """
    for name in PLUGIN_CACHES:
        path = Path(profile_dir) / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def _replace_link(path: Path, text: str) -> None:
    """Point the symbolic link `path` at `text`, atomically."""
    temp = path.with_name(f".{path.name}.claude-sync-tmp")
    temp.unlink(missing_ok=True)
    os.symlink(text, temp)
    os.replace(temp, path)


def absolutize_symlinks(root: Path, old_root: Path) -> list[tuple[Path, str]]:
    """Fix the relative links of `root` that the move from `old_root` broke.

    `root` is the tree after its move. Each relative link is resolved
    lexically (`os.path.normpath`) against its location before the move. A
    target outside `old_root` becomes the absolute target; a target inside
    becomes a relative text to the same entry in `root`, but only when the
    original text no longer reaches it (`../.claude/rules`): plain inside
    links (`../rules`) stay. Absolute and dangling links stay; `.git` is
    skipped and linked directories are not followed. Returns (path relative
    to `root`, original link text) of every rewritten link, for
    `relativize_symlinks`.
    """
    root, old_root = Path(root), Path(os.path.normpath(old_root))
    rewritten = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        for name in sorted(dirnames + filenames):
            path = Path(directory) / name
            if not path.is_symlink():
                continue
            text = os.readlink(path)
            if os.path.isabs(text):
                continue
            relative = path.relative_to(root)
            target = Path(os.path.normpath(old_root / relative.parent / text))
            if target.is_relative_to(old_root):
                expected = root / target.relative_to(old_root)
                if Path(os.path.normpath(path.parent / text)) == expected:
                    continue
                if not os.path.lexists(expected):
                    continue
                _replace_link(path, os.path.relpath(expected, path.parent))
            else:
                if not target.exists():
                    continue
                _replace_link(path, str(target))
            rewritten.append((relative, text))
    return sorted(rewritten)


def relativize_symlinks(links: Iterable[tuple[Path, str]], root: Path) -> None:
    """Give each recorded link of `root` its original text back; a link gone since is skipped."""
    for relative, text in links:
        path = Path(root) / relative
        if path.is_symlink():
            _replace_link(path, text)


def _write_in_place(path: Path, text: str) -> None:
    """Replace the content of `path` atomically, following a symbolic link and keeping the mode.

    A missing file is created with mode 644.
    """
    target = Path(os.path.realpath(path))
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = 0o644
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temp, mode)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _pointer_token(key: str | int) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")


def _path_forms(old: str, new: str) -> dict[str, str]:
    """Each spelling of `old` in a setting, mapped to the same spelling of `new`.

    The absolute path, and when `old` is under the home directory its `~/`,
    `$HOME/` and `${HOME}/` forms; those become the absolute `new` when `new`
    is outside the home directory.
    """
    forms = {old: new}
    home = Path.home()
    if Path(old).is_relative_to(home):
        old_rest = Path(old).relative_to(home).as_posix()
        new_under_home = Path(new).is_relative_to(home)
        new_rest = Path(new).relative_to(home).as_posix() if new_under_home else None
        for prefix in ("~", "$HOME", "${HOME}"):
            forms[f"{prefix}/{old_rest}"] = new if new_rest is None else f"{prefix}/{new_rest}"
    return forms


def rewrite_settings(profile_dir: Path, old: str, new: str) -> list[str]:
    """Replace the `old` path by `new` wherever it occurs in the strings of `settings.json`.

    The absolute path and its `~/`, `$HOME/` and `${HOME}/` forms are
    replaced (see `_path_forms`). An occurrence counts when it starts the
    value or follows a character that cannot be in a path component (not a
    name character, `.`, `-`, `/` or `~`), and when no name character, `.` or
    `-` follows it: `<old>.json` and `<old>-code-config` stay. Returns the
    JSON Pointer of every changed value; calling again with `old` and `new`
    swapped reverses it. The file is written only when something changed,
    with `indent=2`, non-ASCII kept and a trailing newline (Claude Code's own
    format). A missing file changes nothing.
    """
    file = Path(profile_dir) / "settings.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except ValueError as error:
        raise ClaudeSyncError(f"{file} is not valid JSON: {error}") from error
    changed: list[str] = []
    forms = _path_forms(old, new)
    spellings = "|".join(re.escape(form) for form in sorted(forms, key=len, reverse=True))
    pattern = re.compile(rf"(?<![\w/.~-])({spellings})(?![\w.-])")

    def walk(value, pointer: str):
        if isinstance(value, dict):
            return {k: walk(v, f"{pointer}/{_pointer_token(k)}") for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, f"{pointer}/{i}") for i, v in enumerate(value)]
        if isinstance(value, str):
            replaced = pattern.sub(lambda match: forms[match.group(1)], value)
            if replaced != value:
                changed.append(pointer)
            return replaced
        return value

    data = walk(data, "")
    if changed:
        _write_in_place(file, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return changed


MANIFEST_RULE = "!/profile.toml"


def allow_manifest(profile_dir: Path) -> bool:
    """Append `!/profile.toml` to the profile's `.gitignore` when git ignores the manifest.

    Returns whether it appended. A profile without its own `.git` changes nothing.
    """
    profile_dir = Path(profile_dir)
    if not (profile_dir / ".git").exists():
        return False
    command = ["git", "-C", str(profile_dir), "check-ignore", "-q", "profile.toml"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 1:
        return False
    if result.returncode != 0:
        raise ClaudeSyncError(f"`{' '.join(command)}` failed: {result.stderr.strip()}")
    gitignore = profile_dir / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    _write_in_place(gitignore, f"{text}{MANIFEST_RULE}\n")
    return True


# Top-level directories of tool data, not instructions: never searched.
_NOT_SEARCHED = frozenset({".git", "projects", "plugins"})


def markdown_mentions(root: Path, old: Path) -> list[Path]:
    """The `.md` files under `root` naming `old`, as an absolute or a `~/` path.

    A mention is the path followed by anything but a name character, so
    `~/.claude.json` is not one. `projects/`, `plugins/` and `.git` at the top
    level are skipped; linked directories are not followed. Nothing is changed.
    """
    root, old = Path(root), Path(old)
    needles = [re.escape(str(old))]
    if old.is_relative_to(Path.home()):
        needles.append(re.escape(f"~/{old.relative_to(Path.home()).as_posix()}"))
    pattern = re.compile(f"(?:{'|'.join(needles)})(?![\\w-]|\\.\\w)")
    found = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        if Path(directory) == root:
            dirnames[:] = [name for name in dirnames if name not in _NOT_SEARCHED]
        for name in filenames:
            path = Path(directory) / name
            if name.endswith(".md") and path.is_file():
                if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                    found.append(path)
    return sorted(found)


ZSHRC_BEGIN = "# >>> claude-sync >>>"
ZSHRC_END = "# <<< claude-sync <<<"
ZSHRC_BLOCK = (
    f"{ZSHRC_BEGIN}\n"
    'command -v claude-sync >/dev/null && eval "$(claude-sync shell-init zsh)"\n'
    f"{ZSHRC_END}\n"
)


def zshrc_block_add(path: Path) -> bool:
    """Append the marked block to `path` unless its begin marker is there; whether it added.

    Edits in place: follows a symbolic link, keeps the mode (644 for a new
    file), and adds a newline first when the file does not end with one.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if ZSHRC_BEGIN in text.splitlines():
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    _write_in_place(path, text + ZSHRC_BLOCK)
    return True


def zshrc_block_remove(path: Path) -> bool:
    """Remove the lines from the begin marker to the end marker; whether it removed.

    A begin marker without an end marker raises rather than cutting the rest.
    """
    path = Path(path)
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    stripped = [line.rstrip("\n") for line in lines]
    if ZSHRC_BEGIN not in stripped:
        return False
    begin = stripped.index(ZSHRC_BEGIN)
    if ZSHRC_END not in stripped[begin:]:
        raise ClaudeSyncError(f"{path}: {ZSHRC_BEGIN!r} without {ZSHRC_END!r}: edit it by hand")
    end = stripped.index(ZSHRC_END, begin)
    _write_in_place(path, "".join(lines[:begin] + lines[end + 1 :]))
    return True


LAUNCH_AGENT_LABEL = "io.github.ylepalud.claude-sync.env"


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def launch_agent_plist(directory: Path) -> str:
    """A LaunchAgent running `launchctl setenv CLAUDE_CONFIG_DIR <directory>` at login."""
    agent = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": ["/bin/launchctl", "setenv", "CLAUDE_CONFIG_DIR", str(directory)],
        "RunAtLoad": True,
    }
    return plistlib.dumps(agent).decode()


def unrebuildable(observed: Observed, listed: Iterable[dict]) -> list[str]:
    """The installed plugins apply cannot rebuild from a manifest, each with its reason.

    `listed` is the parsed `claude plugin list --json`, every scope included
    (`Observed.plugins` holds the user scope only). A plugin cannot be rebuilt
    when installed at another scope than user, or from a marketplace
    claude-sync does not manage.
    """
    unmanaged = {m.name: m.kind for m in observed.marketplaces if m.source is None}
    reasons = []
    for plugin in listed:
        plugin_id, scope = plugin.get("id"), plugin.get("scope")
        if not isinstance(plugin_id, str) or not isinstance(scope, str):
            raise ClaudeSyncError(
                f"unexpected entry in `claude plugin list --json`: {json.dumps(plugin)}"
            )
        market = plugin_id.rpartition("@")[2]
        if scope != "user":
            reasons.append(f"{plugin_id} (installed at {scope} scope)")
        elif market in unmanaged:
            reasons.append(
                f"{plugin_id} (marketplace {market} is not managed by claude-sync: "
                f"{unmanaged[market]})"
            )
    return reasons


RECORD_FILE = ".claude-sync-migration.json"


@dataclass
class Record:
    """What a migration did, kept in the profile (untracked) so uninstall can reverse it."""

    old_root: str
    steps: list[str] = field(default_factory=list)
    """The names of the steps done, in order."""
    settings_keys: list[str] = field(default_factory=list)
    """JSON Pointers of the `settings.json` values rewritten."""
    links: list[tuple[Path, str]] = field(default_factory=list)
    """(path relative to the profile, original text) of the links made absolute."""
    plist: str | None = None

    def save(self, profile_dir: Path) -> None:
        data = {
            "old_root": self.old_root,
            "steps": self.steps,
            "settings_keys": self.settings_keys,
            "links": [[str(path), text] for path, text in self.links],
            "plist": self.plist,
        }
        write_private(Path(profile_dir) / RECORD_FILE, json.dumps(data, indent=2) + "\n")

    @classmethod
    def load(cls, profile_dir: Path) -> "Record | None":
        """The profile's record; None when it has none."""
        file = Path(profile_dir) / RECORD_FILE
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            record = cls(
                old_root=_typed(data["old_root"], str),
                steps=[_typed(step, str) for step in data["steps"]],
                settings_keys=[_typed(key, str) for key in data["settings_keys"]],
                links=[(Path(_typed(p, str)), _typed(t, str)) for p, t in data["links"]],
                plist=None if data["plist"] is None else _typed(data["plist"], str),
            )
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError) as error:
            raise ClaudeSyncError(f"damaged migration record {file}: {error}") from error
        return record


def _typed(value, kind: type):
    if not isinstance(value, kind):
        raise TypeError(f"expected {kind.__name__}, got {value!r}")
    return value
