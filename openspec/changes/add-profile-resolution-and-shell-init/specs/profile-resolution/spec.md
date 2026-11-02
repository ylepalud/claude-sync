## Purpose

Decide which Claude Code profile applies to a directory, from an optional
configuration file that claude-sync reads and edits itself.

## ADDED Requirements

### Requirement: Configuration file
claude-sync SHALL read its configuration from
`$XDG_CONFIG_HOME/claude-sync/config.toml`, or
`~/.config/claude-sync/config.toml` when `XDG_CONFIG_HOME` is unset. The file
is optional: when it is absent the configuration is `default = "perso"` with
no mappings. The file holds `default` (a profile name) and zero or more
`[[match]]` tables with `path` and `profile`. Profile names SHALL match
`[a-z0-9][a-z0-9-]*`. An invalid file (TOML error, unknown key, bad profile
name, missing field, a mapping of the root directory `/`, or two mappings
whose paths are the same once normalized) SHALL make every command that reads it fail with exit
code 1 and a message naming the file and the problem.

#### Scenario: No configuration file
- **WHEN** no configuration file exists and the user runs `claude-sync which`
- **THEN** the profile is `perso` and the source is `default`

#### Scenario: Duplicate mapping
- **WHEN** the configuration maps `~/Dev/work` to `work` and `~/Dev/work/` to `perso`
- **THEN** `claude-sync which` exits with code 1 and names the file and the duplicated path

#### Scenario: Invalid profile name
- **WHEN** the configuration maps a path to the profile `Work!`
- **THEN** `claude-sync which` exits with code 1 and names the file and the invalid profile

### Requirement: Resolution rule
The profile of a directory SHALL be the profile of the mapping whose path is
the longest one equal to the directory or a parent of it, comparing both as
absolute paths with `~` expanded and symbolic links resolved; otherwise the
default profile. A mapping path matches whole path components only.

#### Scenario: Longest prefix wins
- **WHEN** `~/Dev/work` maps to `work` and `~/Dev/work/oss` maps to `perso`
- **THEN** `~/Dev/work/oss/lib` resolves to `perso` and `~/Dev/work/api` resolves to `work`

#### Scenario: Component boundary
- **WHEN** `~/Dev/work` maps to `work`
- **THEN** `~/Dev/workshop` resolves to the default profile

#### Scenario: Symbolic link
- **WHEN** `~/w` is a symbolic link to `~/Dev/work`, which maps to `work`
- **THEN** `~/w/api` resolves to `work`

### Requirement: Which command
`claude-sync which [DIR]` SHALL print the profile name for `DIR` (default:
the current directory). With `--json` it SHALL print `profile`, `source`
(`override`, `match` or `default`), `match` (the matching configured path or
null), `config_dir` (the profile directory) and `initialized` (whether that
directory exists). When `CLAUDE_SYNC_OVERRIDE` is set to a valid profile name
it wins, with source `override`.

#### Scenario: JSON output
- **WHEN** the user runs `claude-sync which ~/Dev/work/api --json` with `~/Dev/work` mapped to `work` and no `work` profile directory
- **THEN** the output is a JSON object with `profile` `work`, `source` `match`, `match` the configured path, `config_dir` ending in `claude-sync/profiles/work` and `initialized` false

#### Scenario: Override
- **WHEN** `CLAUDE_SYNC_OVERRIDE=perso` and the directory maps to `work`
- **THEN** `claude-sync which` prints `perso` and the JSON source is `override`

### Requirement: Editing the configuration
`claude-sync map DIR PROFILE` SHALL add or replace the mapping for `DIR`,
which MUST be an existing directory other than `/` (otherwise exit 1, nothing
written); the stored path SHALL use the directory's on-disk spelling, so a
wrong letter case on a case-insensitive file system is corrected. Mapping a
directory to the profile it already has SHALL print `already mapped: <path>
-> <profile>`, write nothing and exit 0.
`claude-sync unmap DIR` SHALL remove it, and `claude-sync set-default
PROFILE` SHALL set the default. They SHALL store a path under the home
directory with a leading `~`, create the file and its directory when needed
(directory mode 700, file mode 600), write atomically, and keep every other
entry. Replacing an existing mapping with a different profile SHALL need a
confirmation. `unmap` of a path with no mapping SHALL exit with code 1.
`--dry-run` SHALL print the resulting change and write nothing.

#### Scenario: Map a directory
- **WHEN** the user runs `claude-sync map ~/Dev/work work --yes` with no configuration file
- **THEN** the file exists with mode 600 and holds `default = "perso"` and one match `~/Dev/work` to `work`

#### Scenario: Replace needs confirmation
- **WHEN** `~/Dev/work` maps to `work` and the user runs `claude-sync map ~/Dev/work other` without `--yes` and without a TTY
- **THEN** nothing is written and the exit code is 3

#### Scenario: Directory must exist
- **WHEN** the user runs `claude-sync map ~/Dev/missing work --yes`
- **THEN** the exit code is 1 and no file is written

#### Scenario: On-disk spelling
- **WHEN** `~/Dev/work` exists, the file system is case-insensitive, and the user runs `claude-sync map ~/dev/work work --yes`
- **THEN** the stored path is `~/Dev/work`

#### Scenario: Already mapped
- **WHEN** `~/Dev/work` maps to `work` and the user runs `claude-sync map ~/Dev/work work`
- **THEN** the output is `already mapped: ~/Dev/work -> work`, nothing is written and the exit code is 0

#### Scenario: Dry run
- **WHEN** the user runs `claude-sync map ~/Dev/work work --dry-run`
- **THEN** the planned change is printed and no file is created

### Requirement: Listing and showing
`claude-sync list` SHALL list every known profile (the default, every
mapped profile, and every directory under the profiles root), each with
whether it is the default, whether it is initialized, and its mapped paths.
`claude-sync config` SHALL print the configuration file path, whether it
exists, the default and the mappings. Both SHALL support `--json`.

#### Scenario: List
- **WHEN** `~/Dev/work` maps to `work` and only the `perso` profile directory exists
- **THEN** `claude-sync list --json` contains `perso` (default, initialized, no paths) and `work` (not default, not initialized, path `~/Dev/work`)
