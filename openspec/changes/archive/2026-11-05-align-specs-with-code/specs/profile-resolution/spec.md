## MODIFIED Requirements

### Requirement: Which command
`claude-sync which [DIR]` SHALL print the profile name for `DIR` (default:
the current directory). With `--json` it SHALL print `profile`, `source`
(`override`, `match` or `default`), `match` (the matching configured path or
null), `config_dir` (the profile directory) and `initialized` (whether that
directory exists). When `CLAUDE_SYNC_OVERRIDE` is set to a valid profile name
it wins, with source `override`; when it is set to an invalid name, `which`
(and every command resolving the profile from the current directory) SHALL
fail with exit code 1 naming the variable, while the shell snippet ignores
it with a warning.

#### Scenario: JSON output
- **WHEN** the user runs `claude-sync which ~/Dev/work/api --json` with `~/Dev/work` mapped to `work` and no `work` profile directory
- **THEN** the output is a JSON object with `profile` `work`, `source` `match`, `match` the configured path, `config_dir` ending in `claude-sync/profiles/work` and `initialized` false

#### Scenario: Override
- **WHEN** `CLAUDE_SYNC_OVERRIDE=perso` and the directory maps to `work`
- **THEN** `claude-sync which` prints `perso` and the JSON source is `override`
