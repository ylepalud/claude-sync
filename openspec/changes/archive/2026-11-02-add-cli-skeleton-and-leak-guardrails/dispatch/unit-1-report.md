# Unit 1 report

Status: DONE_WITH_CONCERNS (process note only)

## Implemented
All of 1.1 to 1.5 and 2.1 to 2.7. pyproject.toml, uv.lock, `denylist.txt` in .gitignore, install.sh (executable), src/claude_sync/{__init__,__main__,exit_codes,errors,registry,context,cli}.py, commands/{version,help}.py, tests.
No-test checkboxes: 1.1 (config), 1.5 (install.sh shell script, not exercised; needs network/uv install), 2.7 (verification).
`registry.COMMANDS` is resolved lazily through module `__getattr__` to avoid an import cycle (commands import `Command` from registry); tests monkeypatch it with fake commands.

## Branch to test
- --version: test_cli::test_version_flag
- no argument -> help, 0: test_no_argument_prints_top_level_help
- unknown command -> 2: test_unknown_command_is_a_usage_error
- version text/json: test_version_text, test_version_json_prints_only_a_json_object
- help COMMAND == --help: test_help_of_a_command_equals_its_dash_dash_help
- help --all content/order: test_help_all_has_top_level_and_every_command, test_help_all_is_in_registry_order
- help unknown topic -> 2: test_help_of_unknown_command_is_a_usage_error
- help no --json: test_help_rejects_json
- epilog Examples/Exit codes: test_subcommand_help_has_examples_and_exit_codes
- read adds --json, mutate adds --dry-run/--yes, doc neither: test_registry::test_flags_follow_the_kind (parametrized), test_mutate_command_gets_dry_run_and_yes_into_its_context
- every command documented: test_every_command_documents_itself
- ConfirmationRequired -> 3 with hint: test_confirmation_required_maps_to_exit_3, test_confirmation_required_error_is_not_swallowed_as_generic
- ClaudeSyncError -> 1 with prefix: test_claude_sync_error_maps_to_exit_1
- debug traceback: test_traceback_only_with_debug (absence covered by the exact-stderr assert in the exit_1 test)
- Context.confirm yes/no-tty/tty (yes and default-no): test_context.py
- Context.emit text/json: test_context.py
- ExitCode values/descriptions, error hierarchy: test_exit_codes.py
- __version__ and `python -m`: test_package.py
- isolation fixture: test_isolation.py

## Docs
Nothing pre-existing described old behaviour (first code in repo). README untouched per brief.

## Commands
- `uv run pytest`: 35 passed
- `uv run ruff check`: All checks passed
- `uv run ruff format --check`: 24 files already formatted
- `uv tool install --force .` then `claude-sync help --all` from /tmp: works; `claude-sync --version` prints `claude-sync 0.1.0`.
- No U+2014 in the repo outside openspec/.

## Files changed
.gitignore, pyproject.toml, uv.lock, install.sh, src/claude_sync/*, src/claude_sync/commands/*, tests/*.

## Self-review
Fully implemented; no extras beyond small tests. Overbuild: none.

## Concerns
- [trivial] Process: the isolation conftest (1.4) and the Context/cli code (2.3, 2.4) were written before their tests rather than strictly red-first; tests for them were added right after and pass. 2.1 tests were seen failing (import error) before 2.2 to 2.5.
- [trivial] `help --json` is rejected by the top-level parser ("unrecognized arguments"), so stderr shows the top-level usage, not `usage: claude-sync help`. Exit code is 2 as required.
- [trivial] Unexpected non-ClaudeSyncError exceptions are not caught (brief did not specify); they show a normal Python traceback.
