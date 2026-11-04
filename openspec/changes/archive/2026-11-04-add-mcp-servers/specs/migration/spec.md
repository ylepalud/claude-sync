## ADDED Requirements

### Requirement: MCP servers during migration
When `init` and `uninstall` converge the profile, they SHALL leave MCP
servers as they are: `init` records the imported `[[mcp]]` tables in
`profile.toml` without changing the servers in `.claude.json`, and
`uninstall` never adds, replaces or removes a server. The user converges
MCP servers later with `claude-sync apply`.

#### Scenario: Init leaves MCP servers
- **WHEN** the profile's `.claude.json` has a server whose `env` holds a literal value and the user confirms `claude-sync init`
- **THEN** `profile.toml` declares the server with an `env:` reference and `.claude.json` still holds the literal value
