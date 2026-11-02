# Unit 3 report: README

Status: DONE. File changed: README.md (intro and License kept; Status line extended).
Task 4.1 has no testable behaviour; verified by reading sources and running the commands.

Claims and where each was checked:
- Install one-liner, clone + `CLAUDE_SYNC_SOURCE=. ./install.sh`, install.sh behaviour (uv check, `uv tool install --force`, prints `--version`): install.sh.
- Python >= 3.11, no runtime deps, dev group pytest/ruff: pyproject.toml.
- `help --all`, `help version` equals `version --help`: commands/help.py; ran `uv run claude-sync help --all` (rc 0) and `help version`.
- `version --json` keys version/python: commands/version.py; ran it.
- --help has examples and exit codes: registry.render_epilog, add_command_parser.
- --json on read, --dry-run/--yes on mutate: registry.add_command_parser.
- Refuse without TTY, exit 3: context.Context.confirm, cli.main (ConfirmationRequired -> 3).
- CLAUDE_SYNC_DEBUG=1 traceback: cli._report.
- Exit codes table: exit_codes.py (descriptions copied verbatim).
- Dev commands: pyproject.toml, scripts/install-hooks, ci.yml (ruff check, ruff format --check, pytest, py 3.11/3.13).
- Denylist location, format, DENYLIST override, finding format, nothing printed: `scripts/check-denylist --help` and load_terms.
- Never committed: .gitignore has `denylist.txt`; refusal exit 4 in check-denylist (line ~196-205).
- Hooks: .githooks/pre-commit, commit-msg, pre-push.
- CI DENYLIST secret, scans, gitleaks: .github/workflows/ci.yml leak-guard job.
- Roadmap: design.md line 55-58, only step 1 marked done.
Checks: no U+2014 in README; `scripts/check-denylist --tree` exit 0 after the edit.
