# claude-sync

CLI that isolates several Claude Code user configurations (profiles) and
switches between them through `CLAUDE_CONFIG_DIR`. Python 3.11+ standard
library only, tests with pytest.

## Non-negotiables

- This repository is public. Never write an employer, client, internal domain
  or work e-mail anywhere: code, tests, fixtures, docs, commit messages, PR
  titles and bodies. Use neutral names (`perso`, `work`, `~/Dev/work`).
  `scripts/check-denylist` enforces it locally and in CI.
- No secret in any file. Manifests hold references only (`env:NAME`).
- Never touch the real `~/.claude`, `~/.claude.json`, `~/.config/claude-sync`
  or the Keychain from tests: every test runs against a temporary `HOME`.
- Every CLI command has a complete `--help`: description, examples, exit
  codes. Read commands offer `--json`, mutating commands `--dry-run` and
  `--yes`, and nothing ever waits on a prompt without a TTY.
- Everything in English, no em dash. Conventional Commits.

## PR pipeline

Spec-driven work goes through OpenSpec: one change per step of the roadmap,
proposal first, then implementation on the same branch.
