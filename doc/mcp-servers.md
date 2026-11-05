# MCP servers

A profile's user-scope MCP servers are the top-level `mcpServers` of its
`.claude.json`, what `claude mcp add --scope user` writes. claude-sync
declares them in `profile.toml` and converges them through the `claude
mcp` CLI. Secrets stay out of the manifest: each value of `env` and
`headers` is a reference.

Project and local scope servers, and a project's `.mcp.json`, are not
managed.

## Tables

```toml
[[mcp]]
name = "docs"
transport = "http"
url = "https://docs.example.invalid/mcp"
[mcp.headers]
"Authorization" = "value:Bearer ${DOCS_TOKEN}"

[[mcp]]
name = "tools"
transport = "stdio"
command = "npx"
args = ["-y", "example-tools-mcp"]
[mcp.env]
"TOOLS_API_KEY" = "keychain:tools-api/perso"
"TOOLS_MODE" = "value:fast"
"TOOLS_TOKEN" = "env:TOOLS_TOKEN"
```

| Key | Transports | Required | Value |
| --- | ---------- | -------- | ----- |
| `name` | all | yes | `[A-Za-z0-9][A-Za-z0-9._-]*`, unique in the file |
| `transport` | all | yes | `stdio`, `http` or `sse` |
| `command` | `stdio` | yes | Non-empty string |
| `args` | `stdio` | no | List of strings |
| `env` | `stdio` | no | Table of references |
| `url` | `http`, `sse` | yes | Non-empty string |
| `headers` | `http`, `sse` | no | Table of references |

- A key of the other transport is an error: `url` or `headers` on a
  `stdio` server, `command`, `args` or `env` on an `http` or `sse` server.
- `command`, `args` and `url` are literal: written, compared and printed
  as they are. They may hold placeholders Claude Code expands (`${NAME}`,
  `${NAME:-default}`), but never put a secret in them.
- Keys of `env` and `headers` must be non-empty.
- Errors name the file and the key, never the text of a reference.

## References

Every value of `env` and `headers` is one of three references, and each
ends up in a different place.

| Reference | Written to `.claude.json` as | Where the value lives |
| --------- | ---------------------------- | --------------------- |
| `env:NAME` | `${NAME}` | Your environment, when Claude Code starts the server |
| `keychain:SERVICE[/ACCOUNT]` | The Keychain item's value | The macOS Keychain, and in clear in `.claude.json` |
| `value:TEXT` | `TEXT` | `profile.toml`, so in git |

### env:NAME

`NAME` matches `[A-Za-z_][A-Za-z0-9_]*`. `apply` writes the placeholder
`${NAME}`, and Claude Code expands it from its own environment each time
it starts the server. The value is never on disk: not in `profile.toml`,
not in `.claude.json`.

Export the variable in the environment Claude Code starts in (your
`~/.zshrc`, or a secrets manager that exports it). When it is unset, the
server gets the literal text `${NAME}` and fails to authenticate, and
`claude mcp list` warns. `status` cannot see the environment of future
sessions, so it does not report an unset variable.

### keychain:SERVICE or keychain:SERVICE/ACCOUNT

Neither part contains `/`. `apply` runs
`security find-generic-password -s SERVICE [-a ACCOUNT] -w`, removes the
final newline, and writes the value: Claude Code does not read the
Keychain, so the value sits in clear in the profile's `.claude.json`.
Claude Code writes that file with mode 600, and the `.gitignore` of
`profile create` keeps it out of git (check the `.gitignore` of a profile
`init` migrated).

Create the item with the macOS `security` tool or Keychain Access, for
example:

```sh
security add-generic-password -s tools-api -a perso -w
```

(`-w` without a value asks for the password, so it does not end up in
your shell history.)

A missing item (`security` exits 44), or any other failure of
`security`, stops `apply` with exit 1 before any change, naming the
server, the key and the reference, never the tool's output:

```text
claude-sync: error: MCP server 'tools': env.TOOLS_API_KEY: keychain:tools-api/perso: Keychain item not found
```

See [Security](security.md) for the side effects of reading the Keychain.

### value:TEXT

`TEXT` is written as it is, and it sits in `profile.toml`, so in git. Use
it for non-secret settings (`value:fast`) and for values that combine a
literal with a placeholder Claude Code expands: `value:Bearer
${DOCS_TOKEN}` keeps the token out of the manifest, but its literal part,
`Bearer `, is in `profile.toml`. Never put a secret in a `value:`.

A bare value is refused: `env = { TOKEN = "abc" }` makes the manifest
invalid, with an error saying the value must be `env:`, `keychain:` or
`value:`.

## Import

`claude-sync import` (see [The manifest](manifest.md#import)) reads the
servers in a `.claude.json`: with `--source ~/.claude`, in
`~/.claude.json`, where Claude Code keeps them without
`CLAUDE_CONFIG_DIR`; for any other directory and for a profile, in the
`.claude.json` inside it. A missing `type` is read as `stdio`, and
`streamable-http` as `http`.

`command`, `args` and `url` are kept as they are. Each value of `env`
(stdio) or `headers` (http, sse) becomes a reference:

| Observed value | Recorded as |
| -------------- | ----------- |
| Exactly `${NAME}` | `env:NAME` |
| Another placeholder form (`Bearer ${T}`, `${MODE:-fast}`) | `value:` with the same text |
| Anything else (a literal, possibly a secret) | `env:<SERVER>_<KEY>` |

The made variable name is the server name and the key, joined by `_`, in
upper case, with every character other than a letter or digit as `_`: the
key `API_KEY` of the server `tools` gives `env:TOOLS_API_KEY`. The value
itself is neither written nor printed; the variables to export are listed
on standard error:

```text
claude-sync: export these variables in the shell that starts Claude Code:
  TOOLS_API_KEY
```

A reference of the manifest being replaced is kept, for the same server,
table and key, while it still resolves to the observed value: a
`keychain:` reference holding the same value stays `keychain:`, a
`value:fast` stays `value:fast`. A `keychain:` reference that cannot be
resolved is kept with a warning. With `--output -` there is no manifest
being replaced, so nothing is kept.

### The literal stays until apply

After an import that made `env:TOOLS_API_KEY`, the literal is still in
`.claude.json`. `status` reports the key as changed
(`mcp-changed tools: expected None, found 'env.API_KEY'`), and `apply`
replaces the server with `${TOOLS_API_KEY}`, which removes the literal
from the file. Before that, save the value elsewhere and export it, or
edit the reference to a `keychain:` one holding the same value: `status`
then has nothing to report.

### Import errors

The whole import stops with exit 1, naming the servers and keys, when:

- a made variable would start with a digit (rename the server);
- two keys, of one server or of two, would make the same variable;
- a made variable is also used by another key of the same server (an
  exact `${NAME}` or a kept `env:` reference).

A server the manifest rules would reject (an invalid name, an empty
`command` or `url`) is left out with a warning.

### Unmanaged servers

A server claude-sync cannot record is *unmanaged*: an unknown field
(anything beyond `type`, `command`, `args`, `env`, `url`, `headers`), a
field of another shape than the manifest gives (a non-string `command`,
`env` values that are not strings, and so on), another `type`, a field of
the other transport, or a missing `command` or `url`.

- `import` leaves it out, with a warning naming those fields.
- `status` lists it as information (`mcp-unmanaged`).
- `apply` never replaces or removes it, not even with `--prune`.

When the manifest declares a server of that name, `status` reports it as
changed (drift), and `apply` stops with exit 1 before any change: remove
the server with `claude mcp remove <name> -s user`, or drop it from the
manifest.

## Status

| Kind | Drift | Meaning |
| ---- | ----- | ------- |
| `mcp-missing` | yes | Declared, not in `.claude.json` |
| `mcp-unlisted` | yes | In `.claude.json`, not declared |
| `mcp-changed` | yes | Differs; `actual` names the differing field paths (`url`, `args`, `headers.Authorization`), or the unmodelled fields of an unmanaged entry |
| `mcp-secret` | yes | A reference does not resolve (`expected` is its field path, `actual` the problem) |
| `mcp-unmanaged` | no | An entry with fields claude-sync does not model |

References are compared by what they resolve to: `env:` as its
placeholder text, `value:` as its text, `keychain:` as the item's value.
`status` therefore reads the Keychain items it compares. It never prints
a value of `env` or `headers`, only field paths.

## Apply

`apply` converges the servers after the skills, with:

```sh
claude mcp add-json <name> <json> --scope user
claude mcp remove <name> -s user
```

- Every reference is resolved while planning, before any change to
  plugins, skills or servers. A failure stops `apply` with exit 1.
- A missing server is added. The JSON always carries `type`.
- A server that differs is removed, then added again:
  - an `http` or `sse` server only after the confirmation, because
    removing it deletes its OAuth tokens and client registration; the
    confirmation says `(removes an http server: drops its OAuth
    sign-in)`; sign in to it again afterwards;
  - a `stdio` server without confirmation.
- With `--prune`, servers the manifest does not list are removed after
  the confirmation, never an unmanaged one. Without it, they stay.

The replacement is not atomic: when the add fails after the remove, the
server is gone, and the error ends with `(run apply again)`.

Masking: the dry run, the confirmation and the error of a failing
command show every `env` and `headers` value, placeholders included, as
`***`, and the error output of a failing command is scrubbed of the
resolved values (raw and JSON-escaped). `command`, `args` and `url` are
shown as they are.

```text
would run: claude mcp add-json tools '{"type": "stdio", "command": "npx", "args": ["-y", "example-tools-mcp"], "env": {"TOOLS_TOKEN": "***", "TOOLS_MODE": "***"}}' --scope user
```

## Example: from a literal to a reference

```sh
claude-sync import --profile perso        # tools.env.API_KEY is a literal
#   claude-sync: export these variables ...: TOOLS_API_KEY
security add-generic-password -s tools-api -a perso -w   # store the value
# edit profile.toml: "API_KEY" = "keychain:tools-api/perso"
claude-sync status --profile perso        # nothing to report for that key
```

Or, to keep the value only in your environment, export `TOOLS_API_KEY`
in `~/.zshrc` (from wherever you keep it), then run
`claude-sync apply --profile perso`, which rewrites the server with
`${TOOLS_API_KEY}`.

## During migration

`init` records the servers of `~/.claude.json` in `profile.toml`,
listing the variables to export, and moves the file with the servers as
they are; its own `apply` leaves the servers alone, so imported literals
stay until you run `claude-sync apply`. `uninstall` moves `.claude.json`
back with the servers as they are and runs no `claude mcp` command.
