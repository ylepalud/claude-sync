# plugin-manifest Specification

## Purpose
Declare the plugins and marketplaces of a Claude Code profile in a
versioned file, detect when the profile or its upstream sources differ from
it, and converge the profile to it as far as the Claude Code CLI allows.

## Requirements

### Requirement: Manifest format
A profile manifest SHALL be a TOML file named `profile.toml` at the root of
the profile directory. It holds zero or more `[[marketplace]]` tables with
`name`, `source` (`github:<owner>/<repo>`, `git:<url>`, `url:<url>` or
`path:<directory>`), an optional `ref` (a branch or tag, not allowed for
`path:`) and an optional `commit` (40 lowercase hex, the commit recorded at
import, not allowed for `path:`); zero or more `[[plugin]]` tables with `id`
(`<plugin>@<marketplace>`), `version` and `enabled`; the skill tables
defined by `skill-sources` (`[[skill_source]]`, `[[skill]]`); the `[[mcp]]`
tables defined by `mcp-servers`; the `[[tool]]` tables defined by
`tool-requirements`; and an optional `[account]` table with `org_uuid` (a UUID). Every plugin's
marketplace SHALL be declared. Unknown keys, duplicate names or ids, a
plugin whose marketplace is undeclared, or an invalid value SHALL make
commands that read the manifest fail with exit code 1, naming the file and
the problem. The manifest SHALL hold no secret.

#### Scenario: Undeclared marketplace
- **WHEN** a manifest lists the plugin `x@market` and no marketplace named `market`
- **THEN** `claude-sync status` exits with code 1 and names the file and `market`

#### Scenario: Path source with a ref
- **WHEN** a `path:` marketplace has a `ref`
- **THEN** the manifest is invalid

### Requirement: Target profile
`import` (when it writes a profile manifest), `status` and `apply` SHALL act
on one profile: `--profile NAME` when given, otherwise the profile resolved
for the current directory. They SHALL run every `claude` command with
`CLAUDE_CONFIG_DIR` set to that profile's directory, and SHALL refuse with
exit code 1 when the directory does not exist, suggesting
`claude-sync profile create <name>`.

#### Scenario: Profile not created
- **WHEN** the user runs `claude-sync apply --profile work` and `profiles/work/` does not exist
- **THEN** the exit code is 1 and the message contains `claude-sync profile create work`

#### Scenario: Profile from the current directory
- **WHEN** the current directory maps to `work`, `profiles/work/` exists, and the user runs `claude-sync status` without `--profile`
- **THEN** status reports on the `work` profile

### Requirement: Import
`claude-sync import` SHALL read the installed marketplaces and user-scope
plugins with the `claude` CLI and produce a manifest. A marketplace keeps the
`ref` the CLI reports, if any; when its local copy is a git repository (its
own top level, not inside another repository) and the source is not
`path:`, the current commit is recorded as `commit`. A `path:` source under
the home directory is written with `~`. Marketplaces whose source is a file
or claude.ai are skipped with a warning on standard error. `--source DIR`
reads the configuration in `DIR` instead of a profile. The result goes to
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

### Requirement: Status
`claude-sync status` SHALL compare the manifest with the profile and list
each difference: a marketplace or plugin missing or unlisted; a marketplace
with another source or ref; a marketplace whose commit moved from the
recorded one; a plugin with another version or enabled state; the account
guide keys absent or different; a signed-in organization (the
`oauthAccount.organizationUuid` of the profile's `.claude.json`) different
from `org_uuid`. Marketplaces without a recorded commit and unmanaged
marketplaces SHALL be listed as information, not drift. It SHALL exit 0
when there is no drift and 4 otherwise, and support `--json`.

#### Scenario: Missing plugin
- **WHEN** the manifest lists a plugin the profile does not have
- **THEN** status reports it as missing and exits with code 4

#### Scenario: Wrong organization
- **WHEN** `org_uuid` is set and the profile is signed in to another organization
- **THEN** status reports the mismatch and exits with code 4

### Requirement: Apply
`claude-sync apply` SHALL make the profile match its manifest as far as the
CLI allows: add missing marketplaces (with `#<ref>` when a ref is declared),
install missing plugins, enable or disable plugins to match, write the
account guide keys, converge skills as `skill-sources` defines, and
converge MCP servers as `mcp-servers` defines. A
marketplace present with another source or ref SHALL be removed and added
again, and its plugins reinstalled with their declared enabled state, only
after a confirmation that says removing a marketplace uninstalls its plugins
and deletes their data. Unlisted plugins and marketplaces SHALL be removed
only with `--prune`, after the same kind of confirmation. One confirmation
SHALL list every action that needs one, plugins, skills and MCP servers
together, each with what it changes. apply SHALL never approve a marketplace-declared
command on the user's behalf: when the CLI requires that approval, apply
stops with exit code 1 and shows the CLI's message. After applying, a
plugin version or a marketplace commit that still differs from the manifest
SHALL be reported, with the hint to accept it with `claude-sync import`, and
the exit code SHALL be 4. `--dry-run` SHALL print the planned `claude` and
`git` commands and link changes, with every secret value masked, and change
nothing. A failing `claude` or
`git` command SHALL stop apply with exit code 1 and show the command (secret
values masked) and its error output.

#### Scenario: Converge a new profile
- **WHEN** a new profile's manifest lists one marketplace and one plugin, matching what the marketplace serves
- **THEN** apply adds the marketplace, installs the plugin, and status then exits 0

#### Scenario: Re-pin needs confirmation
- **WHEN** a marketplace is installed with another ref and apply runs without `--yes` and without a TTY
- **THEN** nothing changes and the exit code is 3

#### Scenario: Prune
- **WHEN** the profile has a plugin the manifest does not list and apply runs without `--prune`
- **THEN** the plugin stays installed and status still reports it as unlisted

#### Scenario: Upstream moved
- **WHEN** the marketplace now serves another version of a declared plugin
- **THEN** apply installs it, reports the version difference with the `import` hint, and exits with code 4
