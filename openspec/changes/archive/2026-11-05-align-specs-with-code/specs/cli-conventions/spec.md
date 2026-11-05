## MODIFIED Requirements

### Requirement: Documented exit codes
Commands SHALL use these exit codes: 0 success, 1 runtime error, 2 usage
error, 3 confirmation required but not given, 4 drift detected (state differs
from what is declared). Commands that can be interrupted part way (`init`,
`uninstall`) SHALL exit with 130 on an interrupt (Ctrl-C), after printing
how to recover. Errors SHALL be written to standard error, prefixed with
`claude-sync: error:`. When the reader of standard output closes it early,
the command SHALL end quietly with exit code 1.

#### Scenario: No command
- **WHEN** the user runs `claude-sync` with no argument
- **THEN** the top-level help is printed and the exit code is 0

#### Scenario: Unexpected internal error
- **WHEN** a command fails with an error that is not a known claude-sync error
- **THEN** standard error shows `claude-sync: error: internal error, rerun with CLAUDE_SYNC_DEBUG=1 for details`, no traceback, and the exit code is 1

#### Scenario: Unknown command
- **WHEN** the user runs `claude-sync does-not-exist`
- **THEN** a usage error is printed on standard error and the exit code is 2
