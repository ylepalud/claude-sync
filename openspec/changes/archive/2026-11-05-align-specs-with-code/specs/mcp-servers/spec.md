## MODIFIED Requirements

### Requirement: MCP tables
The profile manifest SHALL accept zero or more `[[mcp]]` tables with a
unique `name`, a `transport` (`stdio`, `http` or `sse`), for `stdio` a
`command`, an optional `args` list and an optional `env` table, and for
`http` and `sse` a `url` and an optional `headers` table; `command`, `args`
and `env` SHALL be refused on `http` and `sse` servers, and `url` and
`headers` on `stdio` servers.
Every `env` and `headers` value SHALL be `env:<NAME>` (an environment
variable name), `keychain:<service>` or `keychain:<service>/<account>`, or
`value:<text>` (an explicit non-secret literal, which MAY contain `${NAME}`
or `${NAME:-default}` placeholders). `command`, `args` and `url` are literal
strings and MAY contain such placeholders. An invalid table
SHALL make commands that read the manifest fail with exit code 1, naming the
file and the problem.

#### Scenario: Bare value refused
- **WHEN** an `[[mcp]]` table has `env = { TOKEN = "abc" }`
- **THEN** the manifest is invalid and the error says the value must be `env:`, `keychain:` or `value:`
