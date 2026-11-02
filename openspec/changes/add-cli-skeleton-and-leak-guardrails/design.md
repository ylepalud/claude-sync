## Context

claude-sync isolates several Claude Code user configurations ("profiles") on
one macOS machine and switches between them through `CLAUDE_CONFIG_DIR`. This
change is step 1 of 5. It records the whole architecture settled with the
user on 2026-11-02, so later changes refer to it, and builds only the
foundations: the CLI frame and the leak guard.

Facts established on the target machine:
- `CLAUDE_CONFIG_DIR` relocates everything, `.claude.json` included, and
  Claude Code stores each directory's login under its own Keychain entry
  (`Claude Code-credentials-<hash>`); the unset case uses
  `Claude Code-credentials` and `~/.claude.json`.
- The existing `~/.claude` is a git repository (allowlisted portable config)
  with 11 plugins whose `plugins/installed_plugins.json` and
  `plugins/known_marketplaces.json` hold absolute paths, so a plain move
  breaks them.
- `claude plugin install` has no version flag; the installed version follows
  the marketplace's commit (`gitCommitSha` is recorded).
- Python 3.13, uv, gh are installed; no managed settings exist.

## Goals / Non-Goals

**Goals (this change):**
- An installable `claude-sync` command with the conventions every later
  command inherits.
- A leak guard that runs locally and in CI before the first line of real
  logic is pushed.

**Non-Goals (this change):** profiles, shell integration, migration,
manifests, anything touching `~/.claude` or the Keychain. They come in steps
2 to 5.

## Whole-project decisions (settled, carried by every later change)

| Topic | Decision | Rejected |
|---|---|---|
| Mechanism | One `CLAUDE_CONFIG_DIR` per profile, N profiles | Symlink swap of `~/.claude` (breaks parallel terminals) |
| Layout | `~/.config/claude-sync/{config.toml, machine.toml, denylist.txt, profiles/<name>/}` | `~/.claude-profiles/` |
| `~/.claude` | No profile keeps it; it disappears after migration | Perso keeps it; symlink fallback (two divergent states: root `~/.claude.json`, unhashed Keychain entry) |
| Default | `perso`, variable always set: zsh hook, `launchctl setenv` for GUI apps | Refuse to start without a profile |
| Switch | Longest path prefix in `config.toml` (`[[match]] path, profile`, `default`), per-shell override `claude-sync use <p>` (`CLAUDE_SYNC_PROFILE`), active profile visible | Global toggle; git-remote matching |
| Isolation | Strict, nothing shared; one-off manual copy allowed | Shared base through symlinks |
| Work profile | Starts empty (minimal `profile.toml`, local git, no remote), locked by `forceLoginMethod` / `forceLoginOrgUUID` from `[account] org_uuid` | Template |
| Repo scope | Tool only; directory mapping in untracked `config.toml` | Profile content in this repo |
| Manifest | `profile.toml` in each profile, versioned in the profile's own repo; declarative `import` / `status` / `apply [--prune]` | Snapshot `freeze`; separate lockfile |
| Plugin versions | Marketplace pinned to a git ref + per-plugin version verified; fallback to per-plugin check only if a ref cannot be pinned | Unpinned |
| Tools | `machine.toml` `[tools]`, profiles declare `requires`, conflict is an error | Per-profile tools |
| Secrets | Never in TOML, references only (`env:NAME`, Keychain) | |
| Migration | Tar backup of `~/.claude` and `~/.claude.json`, explicit confirmation, move, plugins rebuilt by `apply` from the imported manifest, hard-coded `~/.claude` references in `.md` listed for manual fix, `uninstall` restores | Rewriting JSON paths; auto-rewriting `.md` |
| Stack | Python 3.11+ stdlib at runtime, `uv tool install git+...`; clone + `install.sh` documented | Go binary; pure zsh |
| IDE / desktop | Terminal only in v1 | |
| Name, license | `claude-sync`, no short alias (`cs` collides); MIT | |

Roadmap: (1) this change; (2) `shell-init` and profile resolution;
(3) `init` / `uninstall` with backup and migration; (4) `import` / `status` /
`apply` for plugins and marketplaces; (5) skills, MCP, settings, machine
`[tools]`.

## Decisions (this change)

### Package and entry point
- `src/` layout: `src/claude_sync/__init__.py` (`__version__`),
  `__main__.py` (`python -m claude_sync`), `cli.py` (parser, dispatch,
  `main(argv) -> int`), `commands/` (one module per command).
- `pyproject.toml`: `requires-python = ">=3.11"`, `license = "MIT"`, no
  runtime dependencies, build backend `hatchling` (build-time only,
  `[tool.hatch.build.targets.wheel] packages = ["src/claude_sync"]`), script
  `claude-sync = "claude_sync.cli:entry"`. Dev dependencies in a
  `[dependency-groups] dev` group: `pytest`, `ruff`.
- `install.sh` at the root: checks `uv` is present, then runs
  `uv tool install --force "${CLAUDE_SYNC_SOURCE:-git+https://github.com/ylepalud/claude-sync}"`
  and prints `claude-sync --version`. It is the documented alternative to
  the one-liner and the hook point where step 3 adds `claude-sync init`.
- argparse with `RawDescriptionHelpFormatter` and `prog="claude-sync"`
  everywhere (otherwise usage reads `pytest` under tests). `main()` catches
  the `SystemExit` raised by argparse and returns its code, so it always
  returns an int. Bare `claude-sync` prints the top-level help and exits 0. Rejected: click/typer (runtime
  dependency, against the stdlib-only decision).

### Command registry
Each command module exposes a `Command` description: `name`, `summary`,
`description`, `examples` (list of `(command line, explanation)`),
`exit_codes` (subset of the global table), `kind` (`read` or `mutate`),
`configure(parser)` and `run(args, ctx) -> int`. The registry adds `--json` to
`read` commands (except `help`, which prints documentation, not state) and `--dry-run` / `--yes` to `mutate` commands, and renders
`Examples:` and `Exit codes:` into the epilog. A test walks the registry and
fails if any command lacks a description, an example or its exit codes, so a
future command cannot ship an incomplete help.

### Exit codes
`ExitCode` IntEnum in `src/claude_sync/exit_codes.py`: `OK=0`, `ERROR=1`,
`USAGE=2`, `CONFIRMATION_REQUIRED=3`, `DRIFT=4`. argparse already exits with
2 on usage errors. An uncaught `ClaudeSyncError` maps to 1 with the
`claude-sync: error:` prefix; tracebacks only with `CLAUDE_SYNC_DEBUG=1`.

### Confirmation
`ctx.confirm(question) -> bool`: returns True with `--yes`; prompts when
stdin is a TTY; otherwise raises `ConfirmationRequired`, mapped to exit 3
with the question and the hint `rerun with --yes` on stderr. No mutating
command exists yet; the behaviour is covered by unit tests on the context
and a hidden test-only command is not added.

### Leak guard
- `scripts/check-denylist`: a stdlib Python script (not part of the package,
  it guards the repository, not the user's machine). Options:
  `--tree` (content and paths of `git ls-files -z`),
  `--staged` (added lines of `git diff --cached -U0 --no-color --no-ext-diff`,
  line numbers parsed from `@@ ... +<start>,<n> @@` hunk headers, and staged
  paths from `git diff --cached --name-only -z`),
  `--history` (added lines and paths of
  `git log --all -p --diff-merges=first-parent -U0 --no-color --no-ext-diff --format=%x00commit %H`
  (merge commits included), and messages plus author and committer
  identities of `git log --all --format=%H%x00%an %ae %cn %ce%x00%B%x00`
  (reported as `<sha>: identity`); the commit sha is
  what is reported, not blob shas),
  `--message-file PATH`, `--text LABEL` (reads stdin). Several may be
  combined. Binary content skipped (NUL byte in the first 8 KiB; `Binary
  files differ` lines in diffs).
- Locations: `<path>:<line>`; `path #<k>` when the path itself matches (the
  path is never printed, it would carry the term); `<short sha>:<path
  #k>:<line>`, `<short sha>: message`, `<short sha>: path #k` for history;
  `message` for `--message-file`; the label for `--text`.
- Terms: `DENYLIST` env var if set (even empty, so CI cannot silently fall
  back to a missing file), else `~/.config/claude-sync/denylist.txt`. Empty
  or missing: exit 3 with `denylist is empty or missing` (2 stays argparse's
  usage error). Findings: exit 1. Clean: 0.
- Error hygiene: git's stderr is captured and never echoed; uncaught
  exceptions print a fixed message and exit 1 without a traceback, so no
  error path can print file content.
- Output: `<location>: term #<n>`; never the term or the line. Rejected:
  printing the line, which would publish the denylist in CI logs.
- The denylist file itself is never in the repository; the script refuses
  to run if a tracked file is named `denylist.txt`.
- `.githooks/pre-commit` runs `--staged`, then `gitleaks git --staged
  --redact` when `gitleaks` is on `PATH` (a warning otherwise);
  `.githooks/commit-msg` runs `--message-file "$1"`; `.githooks/pre-push`
  runs `--history`, so a branch is checked before it becomes public even
  without a PR. `.gitignore` also lists `denylist.txt` as defence in depth. `scripts/install-hooks` sets
  `git config core.hooksPath .githooks`. Rejected: the `pre-commit`
  framework (extra tool to install for a two-hook need).

### CI (`.github/workflows/ci.yml`)
Triggers: `push` on every branch, `pull_request` with
`types: [opened, synchronize, reopened, edited]` (so an edited title or body
is rescanned). Actions pinned by commit SHA:
`actions/checkout` v7.0.1 `3d3c42e5aac5ba805825da76410c181273ba90b1`,
`astral-sh/setup-uv` v10.3.3 `68559e99cc807c1eb7e9238fd43a15bba460eec2`,
and the gitleaks **binary** v8.30.1 (`gitleaks_8.30.1_linux_x64.tar.gz`,
verified against `gitleaks_8.30.1_checksums.txt` with `sha256sum -c`).
Rejected: `gitleaks/gitleaks-action`, which on push and pull_request scans
only `base^..head`, not the full history.
`permissions: contents: read` at the top.
- `test` job, matrix Python 3.11 and 3.13: `uv sync`, `uv run ruff check`,
  `uv run ruff format --check`, `uv run pytest`.
- `leak-guard` job: checkout with `fetch-depth: 0`; fail if `DENYLIST` is
  empty; `scripts/check-denylist --tree --history`; on `pull_request`, pipe
  the title and the body (passed through `env:`, never interpolated into the
  script) into `--text pr-title` and `--text pr-body`; then
  `gitleaks git --redact --log-opts=--all .` over the full history.
- The `test` job has no `name:` so the matrix checks are named
  `test (3.11)` and `test (3.13)`.
- Branch protection on `main` after the first green run, through
  `PUT /repos/ylepalud/claude-sync/branches/main/protection` with
  `required_status_checks: {strict: true, contexts: [test (3.11), test (3.13),
  leak-guard]}`, `enforce_admins: true` (the owner cannot bypass),
  `required_pull_request_reviews: {required_approving_review_count: 0}`
  (single maintainer), `restrictions: null`, plus `allow_force_pushes: false`,
  `allow_deletions: false`.

## Risks / Trade-offs

- A term added to the denylist later does not clean already-pushed history
  → fill the denylist before the first push (done) and treat a later hit as
  an incident (history rewrite, with explicit confirmation).
- Pull requests from forks get no secrets, so `leak-guard` fails → accepted,
  single-maintainer repo; fail closed is the point.
- Scanning every blob of the history grows with the repo → fine at this
  size; revisit if the job exceeds a minute.
- Branch names, tags and PR comments are not scanned → known gap; branch
  names follow `<type>/<change-name>` and are reviewed when created.
- The dry-run scenario of `cli-conventions` has no command to exercise it
  yet → deferred to step 3, which brings the first mutating command; this
  change only builds and unit-tests `Context`.
- The denylist cannot be printed even when debugging → `--text` lets the
  maintainer test a candidate string locally.
