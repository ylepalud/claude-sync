## Context

New roadmap step 3 (steps 3 and 4 swapped on 2026-11-02). Whole-project
decisions: `openspec/changes/archive/2026-11-02-add-cli-skeleton-and-leak-guardrails/design.md`.

Facts (checked against the installed CLI 2.1.x and the docs):
- `claude plugin list --json`: list of `{id, version, scope, enabled,
  installPath, ...}`; versions are semver or short shas.
- `claude plugin marketplace list --json`: list of `{name, source, repo |
  url | path, ref?, installLocation}`; `source` is `github`, `git`, `url`,
  `directory`, `file` or a claude.ai source.
- `claude plugin marketplace add owner/repo#<branch-or-tag>` works; `#<sha>`
  fails (`fatal: Remote branch <sha> not found`: shallow `clone --branch`).
- `marketplace remove` uninstalls every plugin of that marketplace and
  deletes their options and data.
- `plugin install --yes` silently approves marketplace-declared commands;
  `enable`/`disable` exit 1 when already in that state and need `--scope user`
  to avoid auto-detection.
- Some marketplace copies are not git repositories of their own (the
  official one sits inside `~/.claude`'s repository): check
  `git -C <dir> rev-parse --show-toplevel` equals `<dir>`.
- `forceLoginOrgUUID` is enforced only from managed settings; in a profile's
  `settings.json` it and `forceLoginMethod` only steer the login screen. The
  documented `forceLoginOrgUUID` value is a list.
- The signed-in organization is `oauthAccount.organizationUuid` in
  `<profile>/.claude.json`.

## Goals / Non-Goals

**Goals:** a declarative manifest for plugins and marketplaces, import,
status, apply, profile creation, an account guide with detection.

**Non-Goals:** migrating `~/.claude`, `uninstall`, `/login`, `adopt`,
`launchctl` (step 4); skills, MCP servers, general settings, machine
`[tools]` (step 5); freezing upstream content (the CLI cannot).

## Decisions

| Topic | Decision | Rejected |
|---|---|---|
| Order | Manifest and apply before migration | Mini-reinstall in init; rewriting plugin JSON paths |
| Import target | `--source` / `--output` before migration; profile file only if the dir exists | Creating profiles/perso now |
| Pinning | `ref` = branch or tag given to `add`; `commit` and plugin versions recorded; upstream movement is drift accepted with `import` | Commit refs (CLI cannot clone them); `git checkout` inside the copy (undone by updates); no pinning |
| Sources | github, git, url, path managed; file and claude.ai skipped with a warning; path never pinned | Skip everything but github and path |
| Apply | Converge, confirm re-pin and prune (warning about data loss), restore enabled state after reinstall | Add only |
| Install approval | Never `--yes`; stop with the CLI message | `--yes` after apply's own confirmation |
| Account | Guide keys written + status checks the signed-in organization | Verify only; drop |
| Profiles | `profile create`; repo tracks `profile.toml` only (settings.json can hold tokens in `env`) | Tracking settings.json |
| Tests | Fake `claude` on PATH, autouse guard against the real one, opt-in e2e | Calling real claude in unit tests |

### Modules
- `src/claude_sync/manifest.py`: `Manifest(marketplaces, plugins, account)`,
  `Marketplace(name, source, ref: str | None, commit: str | None)`,
  `Plugin(id, version, enabled)`, `Account(org_uuid)`; `MANIFEST_FILE =
  "profile.toml"`; `load(path)` (validation per spec, raising
  `ManifestError(ClaudeSyncError)` naming the file), `render(manifest)`
  (marketplaces sorted by name, then plugins sorted by id), `save(path,
  manifest)` (atomic, mode 600). `source_spec(marketplace) -> str` gives the
  argument for `marketplace add`: `owner/repo[#ref]`, `<url>[#ref]`, or the
  absolute path.
- `src/claude_sync/settings.py`: `read(profile_dir) -> dict`,
  `apply_guide(profile_dir, org_uuid) -> bool` (sets `forceLoginMethod =
  "claudeai"`, `forceLoginOrgUUID = [org_uuid]`, keeps other keys, indent 2,
  atomic, mode 600; returns whether it changed), `guide_of(settings) ->
  str | None`, `signed_in_org(profile_dir) -> str | None` (from
  `.claude.json`, None when absent).
- `src/claude_sync/claude_cli.py`: `ClaudeCli(config_dir)` runs
  `claude plugin ...` with `CLAUDE_CONFIG_DIR=config_dir`: `plugins()` (user
  scope), `marketplaces()`, `add_marketplace(spec)`, `remove_marketplace(name)`,
  `install(id)` (`--scope user`, never `--yes`, stdin closed so no prompt
  can wait), `uninstall(id)` (`--scope user`), `enable(id)` / `disable(id)`
  (`--scope user`). Failures raise `ClaudeCliError(command, stderr)`.
  Unknown JSON shapes raise. `marketplace_commit(location)` returns the HEAD
  commit only when the location is its own git top level.
- `src/claude_sync/sync.py`: `observe(cli, profile_dir) -> Observed`,
  `diff(manifest, observed) -> list[Difference]` (`kind`: missing, unlisted,
  source, ref, commit, version, enabled, guide, org, unpinned, unmanaged;
  `drift` false for unpinned and unmanaged), `plan(manifest, observed,
  prune) -> list[Action]` (each with its `claude` arguments and `confirm:
  bool`; re-pin = remove, add, install each declared plugin of that
  marketplace, then disable those declared disabled).
- Commands: `profile` (positional action with `choices=["create"]`, then
  `NAME`, `--org-uuid`), `import` (module `import_cmd.py`), `status`,
  `apply`.

### Tests
- `tests/fake_claude.py`: executable stub, state in
  `$CLAUDE_CONFIG_DIR/fake-claude.json`:
  `{"marketplaces": [{"name", "source", "repo"|"url"|"path", "ref"?,
  "installLocation"}], "plugins": [{"id", "version", "scope", "enabled"}],
  "catalog": {"<marketplace>": {"<plugin>": "<version>"}},
  "upstream": {"<owner/repo or url>": "<local git repo path>"},
  "fail": {"<subcommand words>": "<stderr text>"}}`. `marketplace add X[#R]`
  clones `upstream[X]` (a test-built local repo) into
  `$CLAUDE_CONFIG_DIR/plugins/marketplaces/<name>` with `git clone --branch R`
  when R is given, so `marketplace_commit` reads a real commit. `install`
  takes the version from `catalog`. `enable`/`disable` exit 1 when already in
  that state. Every call is appended to `$CLAUDE_CONFIG_DIR/fake-claude.log`.
  A command listed in `fail` exits 1 with that stderr.
- `tests/conftest.py`: an autouse fixture puts a `claude` first on PATH that
  exits 1 with "real claude blocked in tests" unless the `fake_claude`
  fixture replaced it or `CLAUDE_SYNC_E2E=1`; `CLAUDE_SYNC_E2E` is cleared
  by the isolation fixture except in the e2e module.
- `tests/test_e2e.py`: only with `CLAUDE_SYNC_E2E=1`, real `claude`,
  temporary profile, one public marketplace, apply then status.

## Decisions carried to step 4 (migration), settled 2026-11-02

- `/login` once per profile; the Keychain hash is undocumented and the
  published guess matched none of 14 local entries.
- Stray `~/.claude` recreated by tools: one warning per shell from the hook,
  `claude-sync adopt` moves it into a chosen profile (dry-run, confirmation).
- `launchctl setenv CLAUDE_CONFIG_DIR <perso>` kept (user choice) despite
  undocumented GUI behaviour and an IDE on a work folder using perso.
- The migration must handle relative skills symlinks
  (`../../.agents/skills/...`) and the absolute `~/.claude` hook path in
  `settings.json`. Proposed (to confirm in step 4): refuse while Claude
  sessions are running.

## Risks / Trade-offs

- Upstream marketplaces move: apply cannot freeze them → reported as drift,
  accepted explicitly with `import`.
- Undocumented CLI JSON shapes may change → one adapter module, fails loudly.
- The account guide is not enforcement → status detects a wrong sign-in.
