## Why

claude-sync will move and rewrite a user's Claude Code configuration, and it
lives in a public repository written next to a work setup. Before any profile
logic exists, the project needs two foundations: a CLI frame whose every
command an LLM agent can drive safely from `--help` alone, and a guardrail
that makes it impossible to publish an employer, client or internal name, or
a secret, through code, history, commit messages or pull requests.

## What Changes

- Python package `claude_sync` (3.11+, standard library only at runtime),
  installable with `uv tool install git+https://github.com/ylepalud/claude-sync`,
  exposing the `claude-sync` command.
- CLI frame shared by every future command: rich `--help` (description,
  examples, exit codes), documented exit codes, `--json` for read commands,
  `--dry-run` and `--yes` for mutating commands, refusal instead of a prompt
  when there is no TTY.
- First commands: `claude-sync --version`, `claude-sync version`,
  `claude-sync help [--all]`.
- Leak guard: a denylist scanner (`scripts/check-denylist`) over the working
  tree, staged content, full history, commit messages and PR title/body,
  reading terms from a local untracked file or the `DENYLIST` CI secret,
  failing closed when the list is empty, never printing a term in its output.
- Git hooks (`.githooks/pre-commit`, `.githooks/commit-msg`) enabled by
  `scripts/install-hooks`.
- GitHub Actions CI: tests and lint on Python 3.11 and 3.13, gitleaks, the
  denylist scan; `main` protected so a PR merges only with green CI.

## Capabilities

### New Capabilities
- `cli-conventions`: behaviour every `claude-sync` command follows (help
  content, exit codes, JSON output, dry run, non-interactive safety, version).
- `leak-guard`: detection of denylisted terms and secrets before anything
  reaches the public repository.

### Modified Capabilities

None.

## Impact

- New: `pyproject.toml`, `src/claude_sync/`, `tests/`, `scripts/`,
  `.githooks/`, `.github/workflows/ci.yml`, README sections (install,
  development, guardrail).
- GitHub: repository secret `DENYLIST` (already set), branch protection on
  `main`.
- No effect yet on any Claude Code configuration on the machine.

Reviewed against f948946 by fable on 2026-11-02
