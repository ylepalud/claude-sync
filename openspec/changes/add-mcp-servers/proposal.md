## Why

User-scope MCP servers live only in each profile's `.claude.json`, with any
secret written in clear. They are not declared, not reproducible, and a
profile cannot be rebuilt with them. This step declares them in
`profile.toml` with references instead of secrets, and converges them with
the official `claude mcp` CLI.

## What Changes

- `profile.toml` gains `[[mcp]]` tables: `name`, `transport` (`stdio`,
  `http`, `sse`), `command` and `args` (stdio) or `url` (http, sse), and
  `env` / `headers` whose values are references (`env:NAME`,
  `keychain:<service>`) or explicit literals (`value:<text>`).
- `apply` writes `env:NAME` as a `${NAME}` placeholder that Claude Code
  expands at run time, resolves `keychain:` references from the macOS
  Keychain, and adds, replaces (with a confirmation when OAuth tokens would
  be lost) or prunes servers through `claude mcp`.
- `import` reads the profile's servers and turns every value that is not a
  placeholder into an `env:` reference, printing what to export.
- `status` reports MCP differences without ever printing a secret.
- init and uninstall leave MCP servers alone.
- Non-goals: project-scope `.mcp.json`, OAuth flows, machine tools (5c).

## Capabilities

### New Capabilities
- `mcp-servers`: declaring, importing, checking and applying user-scope MCP
  servers with secret references.

### Modified Capabilities
- `plugin-manifest`: the manifest format admits `[[mcp]]`; apply converges
  MCP servers too.
- `migration`: init and uninstall leave MCP servers alone, as they do skills.

## Impact

- New modules for MCP observation, planning and secret resolution; the fake
  `claude` stub learns `mcp add-json` and `mcp remove`; a `security` stub and
  a guard against the real one in tests.
- README: an MCP section.

Reviewed against 33cf2b5 by fable on 2026-11-04
