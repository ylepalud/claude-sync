## MODIFIED Requirements

### Requirement: Machine-readable output for read commands
Every command that only reads state SHALL accept `--json` and then print a
single JSON document on standard output and nothing else on standard output.
`help` and `shell-init` are exempt: they print documentation or shell code,
not state.

#### Scenario: Version as JSON
- **WHEN** the user runs `claude-sync version --json`
- **THEN** standard output is a JSON object with a `version` string and a `python` string, and the exit code is 0

#### Scenario: Shell code has no JSON form
- **WHEN** the user runs `claude-sync shell-init zsh --json`
- **THEN** it is a usage error and the exit code is 2
