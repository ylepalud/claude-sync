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
