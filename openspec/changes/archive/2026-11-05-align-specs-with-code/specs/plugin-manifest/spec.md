## MODIFIED Requirements

### Requirement: Import
`claude-sync import` SHALL read the installed marketplaces and user-scope
plugins with the `claude` CLI and produce a manifest. A marketplace keeps the
`ref` the CLI reports, if any; when its local copy is a git repository (its
own top level, not inside another repository) and the source is not
`path:`, the current commit is recorded as `commit`. A `path:` source under
the home directory is written with `~`. Marketplaces whose source is a file
or claude.ai are skipped with a warning on standard error. `--source DIR`
reads the configuration in `DIR` instead of a profile; when `DIR` is the
default `~/.claude`, the `claude` CLI SHALL run with `CLAUDE_CONFIG_DIR`
unset (it writes `<CLAUDE_CONFIG_DIR>/.claude.json` when it starts, and a
`~/.claude/.claude.json` would make `init` refuse), and the MCP servers are
read from `~/.claude.json`. The result goes to
`--output FILE`, to standard output with `--output -`, or to the target
profile's `profile.toml`, which SHALL only be written when the profile
directory exists. An existing `[account]` table in that file SHALL be kept.
Overwriting an existing file SHALL need a confirmation.

#### Scenario: Import before migration
- **WHEN** the user runs `claude-sync import --source ~/.claude --output -` and no profile directory exists
- **THEN** a valid manifest is printed on standard output and no file or directory is created

#### Scenario: Commit recorded
- **WHEN** a GitHub marketplace's local copy is a git repository at commit `C`
- **THEN** its table has `commit = "C"`

#### Scenario: Unmanaged source
- **WHEN** a marketplace comes from claude.ai
- **THEN** it is left out of the manifest and a warning names it
