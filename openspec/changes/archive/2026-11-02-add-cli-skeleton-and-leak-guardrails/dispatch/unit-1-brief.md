# Unit 1 brief: package skeleton and CLI frame

Repository: /Users/yveslepalud/Dev/perso/my-projects/claude-sync (Python, uv available, Python 3.13 local, must support 3.11+).
Do NOT create `scripts/`, `.githooks/`, `.github/` or touch README.md: later units own them. You may add `denylist.txt` to `.gitignore` (task 1.1).

Non-negotiables (from CLAUDE.md):
- Public repo: never write an employer, client, internal domain or work e-mail anywhere. Use neutral names only.
- Tests never touch the real HOME, ~/.claude, ~/.claude.json, ~/.config/claude-sync or the Keychain (task 1.4 makes this structural).
- Every command has a complete --help: description, examples, exit codes. Read commands --json, mutating commands --dry-run/--yes, never prompt without a TTY.
- English only, no em dash (the character U+2014) anywhere.
- Runtime: standard library only. hatchling is build-time only; pytest and ruff are dev-only.

Seams: `claude_sync.cli.main(argv) -> int` (tests call it with capsys), `claude_sync.context.Context`, `claude_sync.registry` (the command list it exposes). `uv tool install --force .` + `claude-sync help --all` for task 2.7 (you may install it; it only writes under ~/.local).

## Tasks (implement exactly these checkboxes)

## 1. Package skeleton

- [ ] 1.1 Create `pyproject.toml`: name `claude-sync`, version `0.1.0`, `license = "MIT"`, `requires-python = ">=3.11"`, no runtime `dependencies`, build backend `hatchling` with `[tool.hatch.build.targets.wheel] packages = ["src/claude_sync"]`, `[project.scripts] claude-sync = "claude_sync.cli:entry"`, `[dependency-groups] dev = ["pytest", "ruff"]`, `[tool.ruff] target-version = "py311"`, `line-length = 100`, `extend-include = ["scripts/check-denylist"]`, `[tool.ruff.lint] select = ["E", "F", "I", "B", "UP"]`. Run `uv sync` and commit `uv.lock`. Add `denylist.txt` to `.gitignore`.
- [ ] 1.4 Create `tests/conftest.py` with an `autouse` fixture that sets `HOME` to a fresh `tmp_path`, unsets `XDG_CONFIG_HOME`, `CLAUDE_CONFIG_DIR` and `DENYLIST`, and sets `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` to `/dev/null`, so no test can reach the real home, git config or Keychain.
- [ ] 1.5 Create executable `install.sh`: `set -euo pipefail`, fail with a clear message if `uv` is missing, run `uv tool install --force "${CLAUDE_SYNC_SOURCE:-git+https://github.com/ylepalud/claude-sync}"`, then print `claude-sync --version`.
- [ ] 1.2 Create `src/claude_sync/__init__.py` exposing `__version__` read with `importlib.metadata.version("claude-sync")`, and `src/claude_sync/__main__.py` calling `raise SystemExit(entry())`.
- [ ] 1.3 Create `src/claude_sync/exit_codes.py` with `ExitCode(IntEnum)`: `OK=0, ERROR=1, USAGE=2, CONFIRMATION_REQUIRED=3, DRIFT=4`, each with a one-line description used by the help renderer, and `src/claude_sync/errors.py` with `ClaudeSyncError` and `ConfirmationRequired(ClaudeSyncError)`.

## 2. CLI frame (`cli-conventions`)

- [ ] 2.1 Write failing tests in `tests/test_cli.py` (call `main(argv)` with `capsys`; `main` returns an int and never raises `SystemExit`): `--version` prints `claude-sync 0.1.0` and returns 0; no argument prints the top-level help and returns 0; unknown command returns 2 with `usage: claude-sync` on stderr; `version --json` prints only a JSON object with `version` and `python`; `help version` output equals `version --help` output; `help --all` contains the top-level description and every registered command name; `version --help` starts with `usage: claude-sync version` and contains `Examples:` and `Exit codes:`; `help --json` is rejected with 2. Watch them fail.
- [ ] 2.2 Create `src/claude_sync/registry.py`: `Command` dataclass (`name, summary, description, examples: list[tuple[str, str]], exit_codes: list[ExitCode], kind: Literal["read", "mutate", "doc"], configure, run`; `help` is `doc` and gets no extra flag), and the builder that adds `--json` to read commands, `--dry-run` and `--yes` to mutate commands, and renders `Examples:` (each line `  $ <cmd>` then indented explanation) and `Exit codes:` (`  <n>  <description>`) into the epilog with `RawDescriptionHelpFormatter`.
- [ ] 2.3 Create `src/claude_sync/context.py`: `Context(json: bool, dry_run: bool, yes: bool, stdin_is_tty: bool)` with `confirm(question) -> bool` (True with `yes`; `input()` prompt when TTY; else raise `ConfirmationRequired(question)`), and `emit(data: dict, text: str)` printing JSON when `json` else text.
- [ ] 2.4 Create `src/claude_sync/cli.py`: top-level parser with `prog="claude-sync"` (subparsers inherit `claude-sync <name>`), description, examples and exit codes; `--version`; bare invocation prints the top-level help and returns 0; `main` wraps parsing in `try/except SystemExit as e: return int(e.code or 0)`; subcommands from the registry; `main(argv: list[str] | None = None) -> int` mapping `ConfirmationRequired` to 3 (message plus `rerun with --yes` on stderr), `ClaudeSyncError` to 1 with `claude-sync: error: ` prefix, tracebacks only when `CLAUDE_SYNC_DEBUG=1`; `entry()` calls `sys.exit(main())`.
- [ ] 2.5 Create `src/claude_sync/commands/version.py` (read command; text `claude-sync <version>`, JSON `{"version", "python"}`) and `src/claude_sync/commands/help.py` (`help [COMMAND] [--all]`: no argument prints top-level help, `COMMAND` prints that command's help, `--all` prints top-level then each command's help separated by a rule line, in registry order).
- [ ] 2.6 Note: the `cli-conventions` dry-run scenario has no mutating command to exercise yet; it is covered from step 3 on. Add `tests/test_context.py`: `confirm` returns True with `yes=True`, raises `ConfirmationRequired` with `yes=False, stdin_is_tty=False`, and calls `input` when `stdin_is_tty=True` (monkeypatched). Add `tests/test_registry.py`: every registered command has a non-empty summary, description, at least one example and at least one exit code; read commands accept `--json`; mutate commands accept `--dry-run` and `--yes`.
- [ ] 2.7 `uv run pytest` and `uv run ruff check && uv run ruff format --check` pass; `uv tool install --force .` then `claude-sync help --all` works from another directory.



## Binding design

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



## Spec this unit satisfies

## Purpose

Define the behaviour every `claude-sync` command shares so that a human or an
LLM agent can discover, preview and run any command safely from its help text.

## ADDED Requirements

### Requirement: Every command documents itself
Every command and subcommand SHALL answer `--help` with a one-line summary, a
description, every option with its meaning, at least one runnable example and
the list of exit codes it can return. `claude-sync help --all` SHALL print the
help of every command in one output, in a stable order.

#### Scenario: Help of a subcommand
- **WHEN** the user runs `claude-sync version --help`
- **THEN** the output contains a description, an `Examples:` section and an `Exit codes:` section, and the exit code is 0

#### Scenario: Full reference
- **WHEN** the user runs `claude-sync help --all`
- **THEN** the output contains the help of every registered command, including the top-level command, and the exit code is 0

#### Scenario: Help of one command through help
- **WHEN** the user runs `claude-sync help version`
- **THEN** the output equals the output of `claude-sync version --help`

### Requirement: Documented exit codes
Commands SHALL use these exit codes: 0 success, 1 runtime error, 2 usage
error, 3 confirmation required but not given, 4 drift detected (state differs
from what is declared). Errors SHALL be written to standard error, prefixed
with `claude-sync: error:`.

#### Scenario: No command
- **WHEN** the user runs `claude-sync` with no argument
- **THEN** the top-level help is printed and the exit code is 0

#### Scenario: Unknown command
- **WHEN** the user runs `claude-sync does-not-exist`
- **THEN** a usage error is printed on standard error and the exit code is 2

### Requirement: Machine-readable output for read commands
Every command that only reads state SHALL accept `--json` and then print a
single JSON document on standard output and nothing else on standard output.
`help` is exempt: it prints documentation, not state.

#### Scenario: Version as JSON
- **WHEN** the user runs `claude-sync version --json`
- **THEN** standard output is a JSON object with a `version` string and a `python` string, and the exit code is 0

### Requirement: Safe mutating commands
Every command that changes files or external state SHALL accept `--dry-run`,
which prints the planned actions and changes nothing, and `--yes`, which
answers its confirmations. Without `--yes` and without a TTY on standard
input, a command that needs a confirmation SHALL not prompt: it SHALL print
what it would have asked on standard error and exit with code 3.

#### Scenario: No TTY and no --yes
- **WHEN** a mutating command needing confirmation runs with standard input not attached to a terminal and without `--yes`
- **THEN** it changes nothing, explains on standard error that `--yes` is required, and exits with code 3

#### Scenario: Dry run
- **WHEN** a mutating command runs with `--dry-run`
- **THEN** it prints each planned action and leaves the file system unchanged

### Requirement: Version
`claude-sync --version` and `claude-sync version` SHALL print the installed
package version.

#### Scenario: Version flag
- **WHEN** the user runs `claude-sync --version`
- **THEN** the output is `claude-sync <version>` and the exit code is 0

