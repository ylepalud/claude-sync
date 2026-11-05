# mcp-servers Specification

## Purpose
Declare the user-scope MCP servers of a profile without storing secrets in
versioned files, and converge the profile to that declaration through the
`claude mcp` CLI.

## Requirements

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

### Requirement: Resolution
apply SHALL build each server's configuration with `env:NAME` written as
`${NAME}`, `value:<text>` as `<text>`, and `keychain:` references resolved
from the macOS Keychain (`security find-generic-password -w`). A missing
Keychain item (exit 44), or any other failure of `security`, SHALL stop
apply with exit code 1 before any change, naming the server, the key and the
reference and never showing the tool's output. No secret value SHALL ever
be printed or written outside the profile's `.claude.json`: every command
shown (dry run, confirmation, error messages of a failing `claude` command)
SHALL show `env` and `headers` values as `***`.

#### Scenario: Environment reference stays a placeholder
- **WHEN** a server declares `env = { TOKEN = "env:SERVICE_TOKEN" }` and apply adds it
- **THEN** the profile's `.claude.json` holds `"TOKEN": "${SERVICE_TOKEN}"` and no resolved value

#### Scenario: Failing add does not leak
- **WHEN** `claude mcp add-json` fails for a server whose header comes from `keychain:service-x`
- **THEN** apply exits with code 1 and its output shows the command with `***` and not the resolved value

#### Scenario: Missing Keychain item
- **WHEN** a server declares `keychain:service-x` and no such Keychain item exists
- **THEN** apply exits with code 1, names the server, the key and `keychain:service-x`, and changes nothing

### Requirement: Import MCP servers
`claude-sync import` SHALL also read the top-level `mcpServers` of the
profile's `.claude.json` and record each server: its transport, command,
args or url as they are, and each `env` or `headers` value as `env:NAME`
when it is exactly `${NAME}`, as `value:<text>` when it contains another
form of placeholder, else as `env:<SERVER>_<KEY>` (upper case,
non-alphanumerics replaced by `_`), printing on standard error the variables
to export. Two keys of a server giving the same name, or a name starting
with a digit, SHALL be an error naming the server and keys. A field already
declared in the previous manifest for the same server and key, whose
reference still produces the observed value, SHALL keep its reference; a
previous `keychain:` reference that cannot be resolved SHALL be kept with a
warning. A server with fields claude-sync does not model (anything beyond
type, command, args, env, url, headers) SHALL be left out with a warning
naming the fields; it is unmanaged.

#### Scenario: Literal turned into a reference
- **WHEN** a server `tools` has `env = {"API_KEY": "s3cr3t"}`
- **THEN** the manifest records `API_KEY = "env:TOOLS_API_KEY"`, the output names `TOOLS_API_KEY`, and `s3cr3t` appears nowhere in the manifest or the output

#### Scenario: Keychain reference kept
- **WHEN** the previous manifest declares `keychain:service-x` for a key and the profile holds that Keychain value
- **THEN** import keeps `keychain:service-x`

### Requirement: MCP status
`claude-sync status` SHALL also report a declared server that is missing, an
unlisted server, and a server whose configuration differs from the
declaration (comparing resolved values, and for a Keychain reference the
value it resolves to), naming the server and the differing fields but never
a value of `env` or `headers`. A Keychain reference that cannot be resolved
SHALL be reported as drift. An unmanaged server (with unmodelled fields) is
information, not drift.

#### Scenario: Changed header
- **WHEN** the declared header resolves to another value than the one in `.claude.json`
- **THEN** status names the server and `headers.Authorization` and exits with code 4, without printing either value

### Requirement: Apply MCP servers
`claude-sync apply` SHALL add a missing server with `claude mcp add-json
--scope user` (always writing `type`), replace a differing server by
removing and adding it again (a `stdio` server without confirmation; an
`http` or `sse` server after a confirmation that says removing it drops its
OAuth sign-in), and with `--prune` remove unlisted servers after a
confirmation. Unmanaged servers SHALL never be replaced or removed.
Resolution failures SHALL stop apply before any change.

#### Scenario: Converge a server
- **WHEN** the manifest declares one stdio server and the profile has none
- **THEN** apply adds it and status then exits 0

#### Scenario: Replacing an HTTP server needs confirmation
- **WHEN** an http server's url differs and apply runs without `--yes` and without a TTY
- **THEN** nothing changes and the exit code is 3
