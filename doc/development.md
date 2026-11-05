# Development

claude-sync is a Python 3.11+ program using the standard library only
(`argparse`, `tomllib`, `subprocess`, `tarfile`), tested with pytest and
linted with ruff. This page is for contributors.

## Repository layout

```text
src/claude_sync/
  cli.py            parser, dispatch, error and exit code handling
  registry.py       the Command description and the list of command modules
  context.py        --json/--dry-run/--yes, confirm() and emit()
  exit_codes.py     ExitCode (0 to 4) with their descriptions
  errors.py         ClaudeSyncError, ConfirmationRequired
  commands/         one module per command (import_cmd.py for import)
  paths.py          configuration directory, profiles, backups, path normalization
  config.py         config.toml: load, validate, save
  resolve.py        the resolution rule (the reference for the zsh matcher)
  target.py         the profile a command acts on (--profile or resolution)
  zsh.py            the zsh snippet
  manifest.py       profile.toml: tables, validation, rendering
  claude_cli.py     the `claude plugin` adapter (fails on unknown JSON shapes)
  sync.py           marketplaces and plugins: observe, diff, plan
  skills.py         skill sources: observe, diff, plan, import
  gitops.py         thin layer over git for skill clones
  mcp.py            MCP servers: observe, diff, plan, import
  secrets.py        resolution of env:, value: and keychain: references
  settings.py       settings.json guide keys, signed-in organization
  converge.py       apply's convergence and import's manifest building
  tools.py          tool checks, merge across profiles, fix commands
  migration.py      file-system steps of init and uninstall, the record
  system.py         pgrep, launchctl, free space, devices
  fileio.py         atomic private writes (600, parent 700)
tests/              pytest suite, stubs and fixtures
scripts/
  check-denylist    the leak guard scanner
  install-hooks     points git at .githooks
.githooks/          pre-commit, commit-msg, pre-push
.github/workflows/ci.yml
openspec/           specs, archived changes, project context
install.sh          install through uv tool install
```

### Adding a command

Each command module exposes a `COMMAND = Command(...)` with `name`,
`summary`, `description`, `examples`, `exit_codes`, `kind` (`read`,
`mutate` or `doc`), `configure(parser)` and `run(args, ctx) -> int`, and
is listed in `registry.COMMAND_MODULES`. The registry adds `--json` to
`read` commands and `--dry-run`/`--yes` to `mutate` commands, and renders
`Examples:` and `Exit codes:` into the help. A test walks the registry
and fails when a command lacks a description, an example or its exit
codes.

Rules every command follows (from `CLAUDE.md` and the `cli-conventions`
spec): a complete `--help`; `--json` for read commands; `--dry-run` and
`--yes` for mutating commands; never a prompt without a TTY; errors as
`ClaudeSyncError` (exit 1) with a message that names the file or object.

## Set up and run the tests

```sh
uv sync                    # .venv with the dev group (pytest, ruff)
uv run pytest
uv run ruff check
uv run ruff format --check
scripts/install-hooks      # git config core.hooksPath .githooks
```

The zsh tests (`tests/test_zsh_parity.py`) run the snippet in a real
`zsh -f`, never your `~/.zshrc`. They are skipped when zsh is missing,
except in CI, where a missing zsh fails them.

### Isolation guards

No test may touch the real `~/.claude`, `~/.claude.json`,
`~/.config/claude-sync`, the Keychain, launchd or a package manager.
`tests/conftest.py` enforces it with autouse fixtures:

- `isolated_environment`: `HOME` is a temporary directory; it unsets
  `XDG_CONFIG_HOME`, `CLAUDE_CONFIG_DIR`, `DENYLIST`, every
  `CLAUDE_SYNC_*` variable and `CLAUDE_SYNC_E2E`, and points
  `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` at `/dev/null`;
- `block_real_claude`: a `claude` first on `PATH` that refuses to run
  (except in the opt-in end-to-end module);
- `block_real_system`: `pgrep`, `launchctl` and `security` that refuse
  to run (exit 2, so a blocked `pgrep` is never read as "no process");
- `block_real_managers`: `brew`, `npm`, `uv` and `cargo` that refuse to
  run for the code under test (the test runner itself is not affected).

`tests/test_isolation.py` checks the guards themselves.

### Stubs

Fixtures put these executable stubs ahead of the guards when a test asks
for them:

| Stub | Fixture | Stands in for |
| ---- | ------- | ------------- |
| `fake_claude.py` | `fake_claude` | `claude plugin ...` and `claude mcp ...`; state in `<config dir>/fake-claude.json`, every call logged to `fake-claude.log`; `marketplace add` clones a local upstream repository |
| `fake_pgrep.py`, `fake_launchctl.py` | `fake_system` | Process listing (from `FAKE_PGREP_PIDS*`) and launchd (exit from `FAKE_LAUNCHCTL_EXIT`), calls logged under the temporary HOME |
| `fake_security.py` | `fake_keychain` | `security find-generic-password`, answering from `$HOME/.fake-keychain.json`; a missing item exits 44 |
| `fake_tool.py` | `fake_tools` | Command-line tools printing a configured version; use unique names such as `fakejq` so a real binary never satisfies a test |
| `fake_manager.py` | `fake_managers` | `brew`, `npm`, `uv`, `cargo`; an install makes the configured tool present |

Other fixtures build realistic inputs: `legacy_claude` (a `~/.claude`
with a git repository, an allowlist `.gitignore`, a plugin, relative
skill links and an absolute hook path), `skills_upstream` (a local
repository with two skills and two commits), `skill_lock` (a
`~/.agents/.skill-lock.json`), and `case_insensitive_fs` /
`case_sensitive_fs` (skip according to the file system). Upstreams are
local git repositories reached through `git:<path>` sources, so the suite
needs no network.

### End-to-end test

```sh
CLAUDE_SYNC_E2E=1 uv run pytest tests/test_e2e.py
```

It runs the real `claude` CLI and the network against a profile created
in the temporary HOME, with one public marketplace. It is skipped unless
`CLAUDE_SYNC_E2E=1`.

## OpenSpec workflow

Behaviour is specified with OpenSpec (schema `spec-driven`,
`openspec/config.yaml`):

- `openspec/specs/<capability>/spec.md` is the behaviour contract of each
  capability: `cli-conventions`, `leak-guard`, `profile-resolution`,
  `shell-integration`, `profile-management`, `plugin-manifest`,
  `migration`, `skill-sources`, `mcp-servers`, `tool-requirements`. Each
  requirement has scenarios that the tests follow.
- A change lives in `openspec/changes/<name>/` with `proposal.md`,
  `design.md` (decisions and their reasons, facts checked about Claude
  Code), `tasks.md` and delta specs under `specs/`. Once implemented it is
  archived in `openspec/changes/archive/<date>-<name>/` and its deltas
  are merged into `openspec/specs/`.
- One change per roadmap step: the proposal first, then the
  implementation on the same branch and pull request. Tasks name exact
  paths and acceptance criteria, include the command's `--help` text, and
  ask for a failing test before the implementation.
- `openspec/.work/` is scratch space and is not committed.

The archived designs are the place to look for why something is the way
it is: for example why markers in `~/.zshrc`, why `ref` cannot be a
commit, or why `keychain:` values end up in `.claude.json`.

## Conventions

- Everything in English, no em dash.
- Neutral names only in code, tests, fixtures, docs, commit messages and
  pull requests: `perso`, `work`, `~/Dev/work`, `example/skills`,
  `tools`, `jq`, `example.invalid` domains. Never an employer, a client,
  an internal domain or a work e-mail; the leak guard enforces it (see
  [Security](security.md#the-leak-guard-of-this-repository)).
- No secret in any file; manifests in tests hold references only.
- Conventional Commits.
- Line length 100 for Python (ruff); ruff rules `E`, `F`, `I`, `B`, `UP`,
  also applied to `scripts/check-denylist`.

## CI

`.github/workflows/ci.yml` runs on every push to any branch and on pull
requests opened, synchronized, reopened or edited. Permissions are
`contents: read`; actions are pinned by commit SHA.

- `test`, on Python 3.11 and 3.13 (`ubuntu-latest`): `uv sync`,
  `uv run ruff check`, `uv run ruff format --check`, installs zsh, then
  `uv run pytest -rs`.
- `leak-guard`: fails when the `DENYLIST` secret is missing or empty;
  `scripts/check-denylist --tree --history` on a full clone; on pull
  requests, the title and body through `--text`; then gitleaks v8.30.1
  (binary checked against its published checksums) over the full
  history.

The design of the first change also sets branch protection on `main`,
requiring `test (3.11)`, `test (3.13)` and `leak-guard`.

## Releasing

There is no release process yet: no tags, no published package. The
version is `version` in `pyproject.toml` (currently `0.1.0`), read at run
time with `importlib.metadata`, and users install from the default
branch with `uv tool install git+https://github.com/ylepalud/claude-sync`.
`claude-sync --version` therefore changes only when `version` in
`pyproject.toml` changes; users pick up new commits with
`uv tool install --force --reinstall` (see [Installation](installation.md#upgrade)).
