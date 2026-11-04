## MODIFIED Requirements

### Requirement: Manifest format
A profile manifest SHALL be a TOML file named `profile.toml` at the root of
the profile directory. It holds zero or more `[[marketplace]]` tables with
`name`, `source` (`github:<owner>/<repo>`, `git:<url>`, `url:<url>` or
`path:<directory>`), an optional `ref` (a branch or tag, not allowed for
`path:`) and an optional `commit` (40 lowercase hex, the commit recorded at
import, not allowed for `path:`); zero or more `[[plugin]]` tables with `id`
(`<plugin>@<marketplace>`), `version` and `enabled`; the skill tables
defined by `skill-sources` (`[[skill_source]]`, `[[skill]]`); the `[[mcp]]`
tables defined by `mcp-servers`; and an optional `[account]` table with `org_uuid` (a UUID). Every plugin's
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
