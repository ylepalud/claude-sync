## Context

Roadmap step 5a. Whole-project decisions:
`openspec/changes/archive/2026-11-02-add-cli-skeleton-and-leak-guardrails/design.md`;
manifest, import, status, apply from
`openspec/changes/archive/2026-11-02-add-plugin-manifest-and-apply/design.md`
(code: `manifest.py`, `sync.py`, `converge.py`, `commands/{import_cmd,status,apply}.py`).

Facts (2026-11-03, maintainer's machine): `~/.claude/skills` holds 36
relative links `../../.agents/skills/<name>` and 12 real skill directories
(own skills and OpenSpec's, versioned by the profile's git repository).
`~/.agents/skills/<name>` are plain copies, not git checkouts, written by a
third-party skills CLI whose lock `~/.agents/.skill-lock.json` (version 3)
maps each skill name to `source` (`owner/repo`), `sourceType` (`github`),
`sourceUrl`, `skillPath` (`.../<name>/SKILL.md`), `skillFolderHash`,
optional `pluginName`. Two repositories appear; one has entries with and
without a `pluginName`. The lock has 38 entries, 36 are linked. After step
4's migration the links are absolute (`<home>/.agents/skills/<name>`).

## Goals / Non-Goals

**Goals:** external skills declared per profile, pinned to a commit, shared
clones, import from today's links and lock, status and apply.

**Non-Goals:** MCP servers (5b), machine tools (5c), the profile's own
skills, modifying or removing `~/.agents`, updating sources to newer
commits (a later `update` command; today `import` after a manual fetch).

## Decisions

| Topic | Decision | Rejected |
|---|---|---|
| Scope | External sources only; own skills stay in git | Declaring every skill |
| Clones | One per source name per machine in `sources/<name>/`, detached at the recorded commit | One clone per profile (duplication); the `skills` CLI |
| Pinning | apply checks out `commit` (claude-sync runs git, unlike plugins) | Branch only |
| Links | Absolute links `skills/<skill>` -> `sources/<name>/<path>` | Copies (no update path); relative links (break on profile moves) |
| Source naming from the lock | One source per repository, named after the first `pluginName` found for it, else `<owner>-<repo>` | One source per lock entry |
| Conflicts | A real file or directory at a skill's link path stops apply (exit 1) | Replacing it |
| Two profiles, same name, other source or commit | apply reads the other profiles' manifests and refuses, naming both profiles and commits | Detecting from the clone (cannot name the other profile, cannot tell an update) |
| First pin | The lock's `skillFolderHash` is the git tree hash of the skill directory (verified on two skills with `git write-tree`): import records it as `tree`; apply pins the newest commit of the ref where every skill matches, else the one matching most and reports the rest | Upstream head (silent content change) |
| Migration | init and uninstall converge plugins only (`converge(..., skills=False)`) | Cloning and relinking during migration |

### Modules
- `manifest.py`: `SkillSource(name, source, ref, commit)`, `Skill(id, path, tree)`
  added to `Manifest` (`skill_sources`, `skills`, default empty); load,
  validate, render (after plugins, sorted).
- `gitops.py`: `run(*args, cwd=None) -> str` (raises `ClaudeSyncError`
  with the command and stderr), `clone(url, dest, ref)`, `fetch(dest)`,
  `checkout(dest, commit)` (`git -c advice.detachedHead=false checkout
  --detach`), `head(dest)`, `dirty(dest) -> bool` (`status --porcelain`),
  `remote_url(dest)`, `toplevel(path) -> Path | None`, `tree_at(dest,
  commit, path) -> str | None` (`git rev-parse <commit>:<path>`),
  `commits(dest, ref) -> list[str]` (newest first, `git rev-list`),
  `current_ref(dest)`. `url_of(source)`: `github:o/r` ->
  `https://github.com/o/r.git`, `git:<url>` -> `<url>`; `source_of(url)` is
  its inverse (`https://github.com/o/r(.git)` -> `github:o/r`, else
  `git:<url>`).
- `skills.py`: `sources_dir()` (`paths.config_home()/"sources"`),
  `observe(profile_dir) -> SkillsObserved` (links in `skills/` with their
  targets, clone state per declared source: exists, head, dirty, remote),
  `diff(manifest, observed) -> list[sync.Difference]` (kinds
  `skill-missing`, `skill-elsewhere`, `skill-unlisted`, `clone-missing`,
  `clone-commit`, `clone-dirty`, `skill-unpinned` (information),
  `skill-conflict`, `skill-ref`, `skill-tree`; `skill-unpinned` added to
  `sync.INFORMATION`), `pin_from_trees(dest, ref, skills) -> (commit,
  unmatched)`, `other_profiles_conflict(name, source, commit, profile)`
  (reads every other profile's `profile.toml`),
  `plan(manifest, observed, prune) -> list[SkillAction]`
  where `SkillAction(description: str, confirm: bool, run: Callable[[],
  None])`, and `import_skills(profile_dir) -> (sources, skills)` reading the
  links, git top levels and the lock file (`Path.home()/".agents/
  .skill-lock.json"`, version 3; other versions ignored with a warning).
- `converge.py`: `converge(profile_dir, ctx, prune=False, cli=None,
  drift_hint=..., skills=True)` runs plugin actions then, when `skills`,
  skill actions; dry run prints `would run: claude ...` for plugins and
  `would run: git ...` or `would link/replace/remove <path> -> <target>`
  for skills; one confirmation lists every `confirm=True` item of both,
  with `question()` rewritten to say what each kind changes (marketplace
  removal deletes plugin data; replacing a link; removing a link); a
  `skill-conflict` stops before any change. `init` and `uninstall` pass
  `skills=False`. `build_manifest` adds the
  imported skill tables. `commands/status.py` adds skill differences.

### Tests
Local git repositories as upstreams through `git:<path>` sources (no
network), committed with `-c user.name=Test -c user.email=test@example.com`
(the global git config is `/dev/null` in tests); a fixture building an upstream with two skills and two commits;
a lock-file fixture in the isolated HOME; profiles from `profile create`.

## Risks / Trade-offs

- Right after import, lock-described skills still link into `~/.agents`:
  status reports them (`run claude-sync apply`) and exits 4 until apply;
  documented.
- A shared clone at one commit serves every profile: two profiles declaring
  the same source at different commits conflict → apply refuses with both
  commits named; use different source names to diverge.
