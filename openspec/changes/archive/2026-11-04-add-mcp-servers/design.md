## Context

Roadmap step 5b. Builds on the manifest, converge and the skills
integration (`openspec/changes/archive/2026-11-02-add-plugin-manifest-and-apply/design.md`,
`openspec/changes/archive/2026-11-03-add-skill-sources/design.md`).

Facts (2026-11-04):
- `claude mcp add-json --scope user <name> <json>` stores the JSON verbatim
  (verified in a throwaway `CLAUDE_CONFIG_DIR`: `${VAR}` and `${VAR:-x}`
  kept) in `$CLAUDE_CONFIG_DIR/.claude.json` top-level `mcpServers`; the
  file is written with mode 600. `claude mcp remove <name> -s user` removes
  it. Re-adding an existing name fails ("already exists").
- Claude Code expands `${VAR}` and `${VAR:-default}` when it starts a
  server (documented for `.mcp.json`; verified for a user-scope entry's
  `env`, `args` and `${X:-d}` with a throwaway server dumping its
  environment); an unset variable stays literal and
  `claude mcp list` warns. `list`/`get` show placeholders unexpanded and
  have no JSON output.
- Removing an http/sse server deletes its OAuth tokens and client
  registration.
- Shapes: stdio `{"type": "stdio", "command", "args", "env"}`, remote
  `{"type": "http"|"sse", "url", "headers"}`; `add-json` refuses a remote
  entry without `type` and stores `streamable-http` as `http`; re-adding an
  existing name and removing an unknown one both exit 1.
- The maintainer's profile has one user-scope server, `idea`, http with a
  url only.

## Goals / Non-Goals

**Goals:** declared user-scope servers with references instead of secrets,
import, status without leaking, apply through the CLI.

**Non-Goals:** project and local scopes, `.mcp.json`, OAuth flows,
Windows/Linux secret stores, machine tools (5c).

## Decisions

| Topic | Decision | Rejected |
|---|---|---|
| `env:` | Written as `${NAME}`; Claude Code expands at run time; never on disk | Resolving and writing the value |
| `keychain:` | Resolved by apply with `security find-generic-password -s <service> [-a <account>] -w`, written as the value (file 600, outside git) | Unsupported; exporting from the shell |
| Literals | Must be explicit `value:<text>` in env/headers; command/args/url literal | Bare values (a secret could slip into git) |
| Import | Non-placeholder values become `env:<SERVER>_<KEY>`; previous references kept when they still produce the observed value | Keeping literals |
| Observe | Read `mcpServers` from the profile's `.claude.json` | Parsing `claude mcp get` text |
| Change | Remove then `add-json`; confirmation for http/sse (OAuth loss); stdio replaced without confirmation | In-place file edit |
| Migration | init and uninstall leave MCP servers alone (`mcp=False`, like `skills=False`) | Converging during migration |
| Output | Never print env/headers values; every shown command (dry run, confirmation, `ClaudeCliError` of an MCP action) masks them as `***` | Printing values |
| Composite placeholders | `value:` may hold `${...}`; import maps any value with a placeholder to `value:` | Converting `Bearer ${T}` to an env reference |
| Unmodelled fields | Server is unmanaged: skipped by import with a warning, information in status, never replaced or pruned | Dropping the fields silently |

### Modules
- `manifest.py`: `McpServer(name, transport, command, args, url, env,
  headers)` with `env`/`headers` as ordered `dict[str, str]` of references;
  validation per spec; render after skills, sorted by name.
- `secrets.py`: `resolve(reference) -> str` (`env:` -> `${NAME}`, `value:`
  -> text, `keychain:` -> `security` output stripped of the final newline;
  missing item raises `ClaudeSyncError` naming the reference), and
  `keychain_value(service, account)`; runs `security` found on PATH.
- `mcp.py`: `observe(profile_dir) -> dict[str, dict]` (top-level
  `mcpServers`, `type` defaulting to `stdio`, `streamable-http` read as
  `http`), `desired(server) -> dict` (resolved JSON for add-json),
  `diff(manifest, observed) -> list[sync.Difference]` (kinds `mcp-missing`,
  `mcp-unlisted`, `mcp-changed` with the differing field paths in
  `actual`, `mcp-secret` when a reference cannot be resolved,
  `mcp-unmanaged` as information), `plan(...) -> list[McpAction]`
  (`McpAction(description, confirm, args, shown)`: `args` after `claude`,
  `shown` the masked command line used for dry run, confirmation and the
  error raised when the command fails; `desired()` always writes `type`),
  `import_servers(profile_dir, previous) -> (servers, exports)`.
- `converge.py`: `mcp=True` parameter; MCP plan built (and resolution
  errors raised) with the skill plan, before any action; MCP actions run
  after skills; the confirmation question covers them. `init` and
  `uninstall` pass `mcp=False`. `build_manifest` includes imported servers
  and prints the exports on stderr. `status` includes MCP differences.

### Tests
- The fake claude learns `mcp add-json <name> <json> --scope user` (writes
  `mcpServers` into `$CLAUDE_CONFIG_DIR/.claude.json`, fails when the name
  exists) and `mcp remove <name> -s user`.
- `tests/fake_security.py` answers `find-generic-password -s/-a -w` from a
  JSON file in the isolated HOME; the autouse guard blocks the real
  `security` like `claude`, `pgrep` and `launchctl`.

## Risks / Trade-offs

- A `keychain:` value sits in clear in the profile's `.claude.json` (mode
  600, outside git): the price of Claude Code not reading the Keychain.
- A `keychain:` value is an argument of `claude mcp add-json` while it
  runs, visible to `ps` for that instant; and `security` may open a macOS
  access dialog (a GUI prompt, not a TTY one) on the first read.
- Remove then add is not atomic: a failing add after the remove loses the
  server (and its OAuth sign-in); the error says to run apply again.
- A dry run and status resolve Keychain items (to compare), by design.
- An `env:` variable unset when Claude Code starts leaves the literal
  `${NAME}`: the server fails to authenticate; status cannot see the
  environment of future sessions, so it does not report it.
