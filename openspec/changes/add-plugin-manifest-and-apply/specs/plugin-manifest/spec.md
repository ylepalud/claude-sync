## Purpose

Declare the plugins and marketplaces of a Claude Code profile in a
versioned file, and converge the profile to that declaration.

## ADDED Requirements

### Requirement: Manifest format
A profile manifest SHALL be a TOML file named `profile.toml` at the root of
the profile directory. It holds zero or more `[[marketplace]]` tables with
`name`, `source` (`github:<owner>/<repo>` or `path:<directory>`) and either
`ref` (a full commit hash) or `pinned = false`; zero or more `[[plugin]]`
tables with `id` (`<plugin>@<marketplace>`), `version` and `enabled`; and an
optional `[account]` table with `org_uuid`. Every plugin's marketplace SHALL
be declared. Unknown keys, duplicate names or ids, and a plugin whose
marketplace is undeclared SHALL make commands that read the manifest fail
with exit code 1, naming the file and the problem. The manifest SHALL hold
no secret.

#### Scenario: Undeclared marketplace
- **WHEN** a manifest lists the plugin `x@market` and no marketplace named `market`
- **THEN** `claude-sync status` exits with code 1 and names the file and `market`

### Requirement: Target profile
`import` (when it writes a profile manifest), `status` and `apply` SHALL act
on one profile: `--profile NAME` when given, otherwise the profile resolved
for the current directory. They SHALL run every `claude` command with
`CLAUDE_CONFIG_DIR` set to that profile's directory, and SHALL refuse with
exit code 1 when the directory does not exist.

#### Scenario: Profile not created
- **WHEN** the user runs `claude-sync apply --profile work` and `profiles/work/` does not exist
- **THEN** the exit code is 1 and the message suggests `claude-sync profile create work`

### Requirement: Import
`claude-sync import` SHALL read the installed marketplaces and user-scope
plugins with the `claude` CLI and produce a manifest: a marketplace whose
local copy is a git repository gets its current commit as `ref`, any other
gets `pinned = false`; a `path:` source under the home directory is written
with `~`. `--source DIR` reads the configuration in `DIR` instead of a
profile. The result goes to `--output FILE`, or to standard output when
`--output -`, or to the target profile's `profile.toml`, which SHALL only be
written when the profile directory exists. An existing `[account]` table in
that file SHALL be kept. Overwriting an existing manifest SHALL need a
confirmation.

#### Scenario: Import before migration
- **WHEN** the user runs `claude-sync import --source ~/.claude --output -` and no profile directory exists
- **THEN** a valid manifest is printed and no file or directory is created

#### Scenario: Git marketplace pinned
- **WHEN** a marketplace's local copy is a git repository at commit `C`
- **THEN** its table has `ref = "C"` and no `pinned` key

### Requirement: Status
`claude-sync status` SHALL compare the manifest with the profile and list
each difference: a marketplace or plugin missing, unlisted, with another
source or ref, a plugin with another version or enabled state, the account
lock absent or different, and every marketplace with `pinned = false`
(reported as unpinned, not as drift). It SHALL exit 0 when there is no
drift and 4 otherwise, and support `--json`.

#### Scenario: Missing plugin
- **WHEN** the manifest lists a plugin the profile does not have
- **THEN** status reports it as missing and exits with code 4

### Requirement: Apply
`claude-sync apply` SHALL make the profile match its manifest: add missing
marketplaces (a pinned GitHub source as `<owner>/<repo>#<ref>`), install
missing plugins, enable or disable plugins to match, and write the account
lock. A marketplace present with another ref SHALL be removed and added
again at the declared ref, and its plugins reinstalled, only after a
confirmation. Unlisted plugins and marketplaces SHALL be removed only with
`--prune`, after a confirmation. After applying, a plugin whose installed
version differs from the manifest SHALL be reported and the exit code SHALL
be 4. `--dry-run` SHALL print the planned `claude` commands and change
nothing. A failing `claude` command SHALL stop apply with exit code 1 and
show the command and its error output.

#### Scenario: Converge a new profile
- **WHEN** a new profile's manifest lists one pinned marketplace and one plugin
- **THEN** apply adds the marketplace at its ref, installs the plugin, and status then exits 0

#### Scenario: Re-pin needs confirmation
- **WHEN** a marketplace is installed at another ref and apply runs without `--yes` and without a TTY
- **THEN** nothing changes and the exit code is 3

#### Scenario: Prune
- **WHEN** the profile has a plugin the manifest does not list and apply runs without `--prune`
- **THEN** the plugin stays installed and status still reports it as unlisted
