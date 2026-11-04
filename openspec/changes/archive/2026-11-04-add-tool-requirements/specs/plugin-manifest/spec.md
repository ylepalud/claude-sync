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
