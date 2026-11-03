"""External skills: observe a profile's skill links and the shared clones, and converge them."""

import json
import os
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

from claude_sync import gitops, manifest, paths
from claude_sync.errors import ClaudeSyncError
from claude_sync.manifest import Manifest, Skill, SkillSource
from claude_sync.sync import Difference

SKILLS_DIR = "skills"
LOCK_VERSION = 3


def sources_dir() -> Path:
    """Where every skill source is cloned once per machine, in `<name>/`."""
    return paths.config_home() / "sources"


@dataclass(frozen=True)
class Entry:
    """An entry of the profile's `skills/` directory."""

    name: str
    path: Path
    target: Path | None
    """The resolved target of a link; None for a real file or directory."""


@dataclass(frozen=True)
class Clone:
    """The state of a declared source's clone in `sources/<name>/`."""

    name: str
    path: Path
    exists: bool
    head: str | None = None
    dirty: bool = False
    remote: str | None = None
    """The URL of `origin`."""
    on_ref: bool = True
    """Whether the head is reachable from the declared ref (without one, the default branch)."""
    trees: dict[str, str | None] = field(default_factory=dict)
    """The tree at the head of each declared skill of this source that records one, by id."""

    @property
    def source(self) -> str | None:
        """The remote in manifest form."""
        return gitops.source_of(self.remote) if self.remote is not None else None


@dataclass(frozen=True)
class SkillsObserved:
    profile_dir: Path
    entries: dict[str, Entry]
    clones: dict[str, Clone]


def skill_name(skill: Skill) -> str:
    return skill.id.partition("@")[0]


def source_name(skill: Skill) -> str:
    return skill.id.partition("@")[2]


def link_target(skill: Skill) -> Path:
    """Where the link `skills/<skill>` points: the skill's directory in its clone."""
    return sources_dir() / source_name(skill) / skill.path


def _resolve(path: Path) -> Path:
    return Path(os.path.realpath(path))


def observe(profile_dir: Path, declared: Manifest) -> SkillsObserved:
    """The entries of `skills/` and the clone of every source `declared` lists."""
    entries = {}
    directory = profile_dir / SKILLS_DIR
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            target = _resolve(path) if path.is_symlink() else None
            entries[path.name] = Entry(path.name, path, target)
    clones = {}
    for source in declared.skill_sources:
        mine = [s for s in declared.skills if source_name(s) == source.name]
        clones[source.name] = _observe_clone(source, mine)
    return SkillsObserved(profile_dir, entries, clones)


def _observe_clone(source: SkillSource, skills: list[Skill]) -> Clone:
    path = sources_dir() / source.name
    if not (path / ".git").exists():
        return Clone(source.name, path, exists=False)
    head = gitops.head(path)
    try:
        on_ref = gitops.is_ancestor(path, head, source.ref)
    except ClaudeSyncError:
        on_ref = False
    trees = {s.id: gitops.tree_at(path, head, s.path) for s in skills if s.tree is not None}
    return Clone(
        source.name, path, True, head, gitops.dirty(path), gitops.remote_url(path), on_ref, trees
    )


def diff(declared: Manifest, observed: SkillsObserved) -> list[Difference]:
    differences = []
    for source in declared.skill_sources:
        clone = observed.clones[source.name]
        if source.commit is None:
            differences.append(Difference("skill-unpinned", source.name, None, clone.head))
        if not clone.exists:
            differences.append(Difference("clone-missing", source.name, source.source, None))
            continue
        if clone.source != source.source:
            differences.append(Difference("source", source.name, source.source, clone.source))
        if source.commit is not None and clone.head != source.commit:
            differences.append(Difference("clone-commit", source.name, source.commit, clone.head))
        if not clone.on_ref:
            differences.append(Difference("skill-ref", source.name, source.ref, clone.head))
        if clone.dirty:
            differences.append(Difference("clone-dirty", source.name, False, True))
    for skill in declared.skills:
        entry = observed.entries.get(skill_name(skill))
        expected = str(link_target(skill))
        if entry is None:
            differences.append(Difference("skill-missing", skill.id, expected, None))
        elif entry.target is None:
            differences.append(Difference("skill-conflict", skill.id, expected, str(entry.path)))
        elif entry.target != _resolve(link_target(skill)):
            differences.append(Difference("skill-elsewhere", skill.id, expected, str(entry.target)))
        clone = observed.clones[source_name(skill)]
        if skill.tree is not None and clone.exists and clone.trees[skill.id] != skill.tree:
            differences.append(
                Difference("skill-tree", skill.id, skill.tree, clone.trees[skill.id])
            )
    for entry in _unlisted(declared, observed):
        differences.append(Difference("skill-unlisted", entry.name, None, str(entry.target)))
    return differences


def _unlisted(declared: Manifest, observed: SkillsObserved) -> list[Entry]:
    """The links of `skills/` into the sources directory that no declared skill names."""
    names = {skill_name(s) for s in declared.skills}
    root = _resolve(sources_dir())
    return [
        entry
        for entry in observed.entries.values()
        if entry.name not in names
        and entry.target is not None
        and entry.target.is_relative_to(root)
    ]


def pin_from_trees(dest: Path, ref: str | None, skills: Iterable[Skill]) -> tuple[str, list[str]]:
    """The commit of `ref` in clone `dest` matching the recorded trees of `skills` best.

    The newest commit where every skill with a `tree` has it; else the newest
    matching the most of them, with the ids of the others (changed since install).
    """
    recorded = [s for s in skills if s.tree is not None]
    best: tuple[str, list[str]] | None = None
    for commit in gitops.commits(dest, ref):
        unmatched = [s.id for s in recorded if gitops.tree_at(dest, commit, s.path) != s.tree]
        if not unmatched:
            return commit, []
        if best is None or len(unmatched) < len(best[1]):
            best = (commit, unmatched)
    return best


def other_profiles_conflict(name: str, source: str, commit: str | None, profile_dir: Path) -> None:
    """Raise when another profile declares source `name` with another source or commit.

    Every profile shares the clone `sources/<name>/`. Recorded commits must be
    equal; a profile without a commit cannot use a source another one pins.
    Reads `profile.toml` of every other profile; an invalid one raises its
    ManifestError.
    """
    root = paths.profiles_root()
    if not root.is_dir():
        return
    mine = _resolve(profile_dir)
    for directory in sorted(root.iterdir()):
        file = directory / manifest.MANIFEST_FILE
        if _resolve(directory) == mine or not file.is_file():
            continue
        for other in manifest.load(file).skill_sources:
            if other.name != name:
                continue
            if other.source == source and commit is None and other.commit is not None:
                raise ClaudeSyncError(
                    f"skill source {name!r}: profile {profile_dir.name!r} declares {source} "
                    f"without a commit, profile {directory.name!r} pins it at {other.commit}; "
                    f"they would share {paths.display(sources_dir() / name)}: declare the same "
                    f"commit, or use another source name"
                )
            if other.source != source or (
                commit is not None and other.commit is not None and other.commit != commit
            ):
                raise ClaudeSyncError(
                    f"skill source {name!r}: profile {profile_dir.name!r} declares "
                    f"{source} at {commit or 'no commit'}, profile {directory.name!r} "
                    f"declares {other.source} at {other.commit or 'no commit'}; they would "
                    f"share {paths.display(sources_dir() / name)}: align them, or rename "
                    f"the source in one profile"
                )


@dataclass(frozen=True)
class SkillAction:
    description: str
    """What the action does, to print after `would ` in a dry run: `run: git ...`,
    `link <path> -> <target>`, `replace <path> -> <target>` or `remove <path> -> <target>`."""
    confirm: bool
    """True when the action replaces or removes a link, which needs a confirmation."""
    run: Callable[[], None]


def _git_description(dest: Path | None, *args: str) -> str:
    where = ["-C", paths.display(dest)] if dest is not None else []
    return "run: " + " ".join(["git", *where, *args])


def _clone_action(source: SkillSource, dest: Path) -> SkillAction:
    url = gitops.url_of(source.source)
    branch = ["--branch", source.ref] if source.ref is not None else []
    return SkillAction(
        _git_description(None, "clone", *branch, url, paths.display(dest)),
        False,
        lambda: gitops.clone(url, dest, source.ref),
    )


def _refuse_dirty(clone: Clone) -> None:
    if clone.dirty:
        raise ClaudeSyncError(
            f"{paths.display(clone.path)} has local changes: commit or discard them, "
            f"then apply again"
        )


def _has_commit(dest: Path, commit: str) -> bool:
    try:
        gitops.run("cat-file", "-e", f"{commit}^{{commit}}", cwd=dest)
    except ClaudeSyncError:
        return False
    return True


def _fetch_action(dest: Path) -> SkillAction:
    return SkillAction(
        _git_description(dest, "fetch", "--tags", "origin"), False, lambda: gitops.fetch(dest)
    )


def _checkout_action(dest: Path, commit: str) -> SkillAction:
    return SkillAction(
        _git_description(dest, "checkout", "--detach", commit),
        False,
        lambda: gitops.checkout(dest, commit),
    )


def _late_checkout(clone: Clone, ref: str | None, recorded: list[Skill]) -> SkillAction:
    """Check out, once cloned or fetched, the commit matching the recorded trees
    best, or without trees the head of `ref`; a dirty clone that would move raises."""
    dest = clone.path

    def run() -> None:
        if recorded:
            commit, _ = pin_from_trees(dest, ref, recorded)
        else:
            commit = gitops.run("rev-parse", gitops.resolve_ref(dest, ref), cwd=dest)
        if commit != gitops.head(dest):
            _refuse_dirty(replace(clone, dirty=gitops.dirty(dest)))
            gitops.checkout(dest, commit)

    what = "newest commit matching the recorded trees" if recorded else f"head of {ref}"
    return SkillAction(_git_description(dest, "checkout", "--detach", f"<{what}>"), False, run)


def _resolves(dest: Path, ref: str) -> bool:
    try:
        gitops.resolve_ref(dest, ref)
    except ClaudeSyncError:
        return False
    return True


def _link_action(verb: str, link: Path, target: Path, confirm: bool) -> SkillAction:
    def run() -> None:
        if verb == "replace":
            link.unlink()
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

    return SkillAction(f"{verb} {paths.display(link)} -> {paths.display(target)}", confirm, run)


def plan(declared: Manifest, observed: SkillsObserved, prune: bool) -> list[SkillAction]:
    """The git commands and link changes converging the profile's skills, in order.

    Per source (manifest order): clone when missing (at `ref`), fetch when the
    commit to check out or the declared ref is absent (an unknown ref still
    absent after the fetch then fails as the actions run), then check out (detached) the recorded
    commit, else the commit pinned from the recorded trees, else, for a clone
    off its declared ref, the head of that ref. Then one link per missing
    skill, a confirmed replace per link pointing elsewhere, and with `prune` a
    confirmed removal per undeclared link into the sources directory.

    Raises, before any action and without changing anything:
    - ClaudeSyncError for a real file or directory at a declared skill's link path;
    - ClaudeSyncError when another profile declares a source of the same name
      with another source or commit (see `other_profiles_conflict`), and the
      ManifestError of another profile's invalid manifest;
    - ClaudeSyncError for an existing clone of another source than declared;
    - ClaudeSyncError for a clone with local changes that needs a checkout.
    """
    for skill in declared.skills:
        entry = observed.entries.get(skill_name(skill))
        if entry is not None and entry.target is None:
            raise ClaudeSyncError(
                f"{paths.display(entry.path)} is not a link: move it away to install "
                f"{skill.id}, or remove the skill from the manifest"
            )
    for source in declared.skill_sources:
        other_profiles_conflict(source.name, source.source, source.commit, observed.profile_dir)
        clone = observed.clones[source.name]
        if clone.exists and clone.source != source.source:
            raise ClaudeSyncError(
                f"{paths.display(clone.path)} is a clone of {clone.source}, not of "
                f"{source.source}: remove it, or rename the source"
            )
    actions: list[SkillAction] = []
    for source in declared.skill_sources:
        clone = observed.clones[source.name]
        recorded = [
            s for s in declared.skills if source_name(s) == source.name and s.tree is not None
        ]
        if not clone.exists:
            actions.append(_clone_action(source, clone.path))
            if source.commit is not None:
                actions.append(_checkout_action(clone.path, source.commit))
            elif recorded:
                actions.append(_late_checkout(clone, source.ref, recorded))
            continue
        if source.ref is not None and not _resolves(clone.path, source.ref):
            # A ref created upstream after the clone: fetch, then resolve it.
            actions.append(_fetch_action(clone.path))
            if source.commit is None:
                actions.append(_late_checkout(clone, source.ref, recorded))
            elif clone.head != source.commit:
                _refuse_dirty(clone)
                actions.append(_checkout_action(clone.path, source.commit))
            continue
        commit = source.commit
        if commit is None and recorded:
            commit, _ = pin_from_trees(clone.path, source.ref, recorded)
        elif commit is None and not clone.on_ref:
            commit = gitops.run(
                "rev-parse", gitops.resolve_ref(clone.path, source.ref), cwd=clone.path
            )
        if commit is not None and clone.head != commit:
            _refuse_dirty(clone)
            if not _has_commit(clone.path, commit):
                actions.append(_fetch_action(clone.path))
            actions.append(_checkout_action(clone.path, commit))
    links = observed.profile_dir / SKILLS_DIR
    for skill in declared.skills:
        entry = observed.entries.get(skill_name(skill))
        link, target = links / skill_name(skill), link_target(skill)
        if entry is None:
            actions.append(_link_action("link", link, target, False))
        elif entry.target != _resolve(target):
            actions.append(_link_action("replace", link, target, True))
    if prune:
        for entry in _unlisted(declared, observed):
            actions.append(
                SkillAction(
                    f"remove {paths.display(entry.path)} -> {paths.display(entry.target)}",
                    True,
                    entry.path.unlink,
                )
            )
    return actions


class _Imported:
    """The sources and skills found so far."""

    def __init__(self, previous: Manifest | None) -> None:
        self.sources: dict[str, SkillSource] = {}
        self.skills: list[Skill] = []
        self.previous = previous or Manifest((), (), None)

    def declared_tree(self, id_: str, path: str) -> bool:
        """Whether the previous manifest records a tree for this skill id and path."""
        return any(
            (s.id, s.path) == (id_, path) and s.tree is not None for s in self.previous.skills
        )

    def result(self) -> tuple[tuple[SkillSource, ...], tuple[Skill, ...]]:
        """The sources, each keeping the ref of the same name and source previously declared."""
        refs = {(s.name, s.source): s.ref for s in self.previous.skill_sources}
        sources = tuple(replace(s, ref=refs.get((s.name, s.source))) for s in self.sources.values())
        return sources, tuple(self.skills)

    def name_for(self, preferred: str, source: str, commit: str | None) -> str:
        """The name of the source already found as `source` at `commit`, else a free name.

        A `commit` of None (a lock entry) matches `source` at any commit.
        """
        for found in self.sources.values():
            if found.source == source and commit in (None, found.commit):
                return found.name
        name, n = preferred, 2
        while name in self.sources:
            name, n = f"{preferred}-{n}", n + 1
        return name

    def add(self, link: Path, source: SkillSource, path: str, tree: str | None = None) -> None:
        """Record the skill `link` shows, unless the manifest would reject it (a warning)."""
        source = self.sources.get(source.name, source)
        skill = Skill(f"{link.name}@{source.name}", path, tree)
        try:
            _validate(Manifest((), (), None, (source,), (skill,)))
        except manifest.ManifestError as error:
            _warn(f"skipped {paths.display(link)}: {error}")
            return
        self.sources.setdefault(source.name, source)
        self.skills.append(skill)


def _validate(tables: Manifest) -> None:
    """Raise ManifestError when `tables` would not load back (the manifest's own rules)."""
    manifest._parse(tomllib.loads(manifest.render(tables)), Path("imported"))


def _warn(message: str) -> None:
    print(f"claude-sync: warning: {message}", file=sys.stderr)


def import_skills(
    profile_dir: Path, previous: Manifest | None = None
) -> tuple[tuple[SkillSource, ...], tuple[Skill, ...]]:
    """The skill sources and skills the links of `profile_dir/skills/` show.

    Three kinds of links are recorded:
    - into `sources/<name>/`: source `<name>`, the clone's remote in manifest
      form (`gitops.source_of`) and its checked-out commit;
    - into `~/.agents/skills/<skill>` with a `github` entry in the version-3
      lock file: `github:<owner>/<repo>`, no commit, the directory of
      `skillPath` and `tree` = `skillFolderHash`;
    - into another git checkout with a remote: as for `sources/`, the source
      named after the checkout's directory.
    Links into `sources/` are read first and keep their names. Other names:
    a source already found for the same repository is reused (at the same
    commit for a checkout, at any commit for a lock entry); else a lock entry
    takes the first `pluginName` of its repository in file order, or
    `<owner>-<repo>`; a name already taken gets `-2`, `-3`, ...

    Real files and directories are left out silently. Left out with a warning
    on stderr: links to anything else, into a checkout without a remote, into
    the profile's own repository, to the root of a checkout, into
    `~/.agents/skills` without a usable lock entry, and any skill or source
    the manifest rules would reject. A lock of another version or shape is
    ignored with a warning.

    `previous`, the manifest being replaced, gives what a clone cannot show:
    the `ref` of a source of the same name and source, and whether a skill of
    the same id and path records a `tree` (then read again from the clone).
    """
    found = _Imported(previous)
    directory = profile_dir / SKILLS_DIR
    links = sorted(p for p in directory.iterdir() if p.is_symlink()) if directory.is_dir() else []
    sources = _resolve(sources_dir())
    in_sources, others = [], []
    for link in links:
        target = _resolve(link)
        if target.is_relative_to(sources) and len(target.relative_to(sources).parts) > 1:
            in_sources.append((link, target, sources / target.relative_to(sources).parts[0]))
        else:
            others.append((link, target))
    # Clones in `sources/` first: they keep their names.
    for link, target, clone in in_sources:
        _import_checkout(found, link, target, clone, clone.name)
    agents = _resolve(Path.home() / ".agents" / "skills")
    own = gitops.toplevel(profile_dir)
    own = _resolve(own) if own is not None else None
    lock = None
    for link, target in others:
        if target.parent == agents:
            if lock is None:
                lock = _read_lock()
            entry = lock.get(target.name)
            if (
                entry is None
                or entry.get("sourceType") != "github"
                or not isinstance(entry.get("source"), str)
                or not isinstance(entry.get("skillPath"), str)
            ):
                lock_name = paths.display(lock_file())
                _warn(
                    f"skipped {paths.display(link)}: no github entry {target.name!r} in {lock_name}"
                )
                continue
            source = f"github:{entry['source']}"
            name = found.name_for(_lock_source_name(lock, entry["source"]), source, None)
            path = PurePosixPath(entry["skillPath"]).parent.as_posix()
            found.add(
                link, SkillSource(name, source, None, None), path, entry.get("skillFolderHash")
            )
            continue
        top = gitops.toplevel(target)
        if top is None or _resolve(top) == own:
            _warn(f"skipped {paths.display(link)}: {paths.display(target)} is not a skill source")
            continue
        _import_checkout(found, link, target, _resolve(top), None)
    return found.result()


def lock_file() -> Path:
    """The lock file of the third-party skills CLI."""
    return Path.home() / ".agents" / ".skill-lock.json"


def _read_lock() -> dict[str, dict]:
    """The skill entries of the lock file: empty without one, and empty with a
    warning when it is unreadable, of another version or of another shape."""
    file = lock_file()
    if not file.is_file():
        return {}
    try:
        data = json.loads(file.read_text())
    except (OSError, ValueError) as error:
        _warn(f"ignored {paths.display(file)}: cannot read it: {error}")
        return {}
    version = data.get("version") if isinstance(data, dict) else None
    if version != LOCK_VERSION:
        _warn(f"ignored {paths.display(file)}: version {version}, not {LOCK_VERSION}")
        return {}
    entries = data.get("skills")
    if not isinstance(entries, dict) or not all(isinstance(e, dict) for e in entries.values()):
        _warn(f"ignored {paths.display(file)}: 'skills' is not a table of entries")
        return {}
    return entries


def _lock_source_name(lock: dict[str, dict], repo: str) -> str:
    """The first `pluginName` of the entries of `repo`, in file order, else `<owner>-<repo>`."""
    for entry in lock.values():
        if entry.get("source") == repo and entry.get("pluginName"):
            return entry["pluginName"]
    return repo.replace("/", "-")


def _import_checkout(
    found: _Imported, link: Path, target: Path, top: Path, name: str | None
) -> None:
    """Record the skill `link` points to in checkout `top`; `name` None derives one."""
    remote = gitops.remote_url(top)
    if remote is None:
        _warn(f"skipped {paths.display(link)}: {paths.display(top)} has no remote")
        return
    if target == top:
        _warn(f"skipped {paths.display(link)}: it links to the root of {paths.display(top)}")
        return
    source, commit = gitops.source_of(remote), gitops.head(top)
    name = name or found.name_for(top.name, source, commit)
    path = target.relative_to(top).as_posix()
    tree = (
        gitops.tree_at(top, commit, path)
        if found.declared_tree(f"{link.name}@{name}", path)
        else None
    )
    found.add(link, SkillSource(name, source, None, commit), path, tree)
