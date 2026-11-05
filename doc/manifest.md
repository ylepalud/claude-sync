# The manifest: profile.toml

Each profile can declare what it is made of in `profile.toml`, at the
root of the profile directory. Three commands work from it:

- `claude-sync import` writes it from what is installed;
- `claude-sync status` compares it with the profile and reports drift;
- `claude-sync apply` makes the profile match it, as far as the Claude
  Code CLI allows.

The manifest holds no secret: MCP server values are references (see
[MCP servers](mcp-servers.md)). It is the one file the profile's git
repository tracks, so you can commit it, push it to a private remote and
replay it on another machine.

## Overview

```toml
[[marketplace]]
name = "example-tools"
source = "github:example/claude-plugins"
ref = "v1.2"
commit = "0123456789abcdef0123456789abcdef01234567"

[[marketplace]]
name = "local-tools"
source = "path:~/Dev/claude-plugins"

[[plugin]]
id = "formatter@example-tools"
version = "1.2.0"
enabled = true

[[plugin]]
id = "notes@local-tools"
version = "0.3.1"
enabled = false

[[skill_source]]
name = "example-skills"
source = "github:example/skills"
ref = "main"
commit = "0123456789abcdef0123456789abcdef01234567"

[[skill]]
id = "tdd@example-skills"
path = "skills/engineering/tdd"
tree = "89abcdef0123456789abcdef0123456789abcdef"

[[mcp]]
name = "tools"
transport = "stdio"
command = "npx"
args = ["-y", "example-tools-mcp"]
[mcp.env]
"TOOLS_TOKEN" = "env:TOOLS_TOKEN"

[[tool]]
name = "jq"
version = "1.7"
install = "brew:jq"

[account]
org_uuid = "00000000-0000-0000-0000-000000000000"
```

Every table is optional; an empty file is a valid manifest (it is what
`profile create` writes). When claude-sync writes the file, it orders the
tables as above (marketplaces by name, plugins by id, skill sources by
name, skills by id, MCP servers by name, tools by name, then `[account]`)
and writes it atomically with mode 600.

## Validation

Every command that reads a manifest fails with exit code 1, naming the
file and the problem, on:

- invalid TOML or invalid UTF-8;
- an unknown top-level key or an unknown key in a table;
- a missing required field;
- a value of the wrong type or form (each table below gives the rules);
- a duplicate marketplace name, plugin id, skill source name, skill id,
  MCP server name or tool name;
- a plugin whose marketplace is not declared, or a skill whose source is
  not declared.

The commands that read a manifest are `status` and `apply` (the target
profile's), `import` (the file it replaces), `doctor` (every profile's),
and `apply` of a profile that declares skill sources (every other
profile's, to compare the sources they share).

The top-level keys are `marketplace`, `plugin`, `skill_source`, `skill`,
`mcp`, `tool` (arrays of tables) and `account` (a table).

## [[marketplace]]

| Key | Required | Value |
| --- | -------- | ----- |
| `name` | yes | `[A-Za-z0-9][A-Za-z0-9._-]*`, unique |
| `source` | yes | `github:<owner>/<repo>`, `git:<url>`, `url:<url>` or `path:<directory>` |
| `ref` | no | A branch or a tag; not allowed for `path:` |
| `commit` | no | 40 lowercase hex characters, the commit recorded at import; not allowed for `path:` |

- `github:` takes `<owner>/<repo>`, each part made of letters, digits,
  `.`, `_` and `-`.
- `ref` is passed to `claude plugin marketplace add` as `<source>#<ref>`.
  It cannot be a commit: the CLI clones with `--branch`, which fails on a
  commit hash.
- `path:` accepts `~`; `import` writes a path under your home directory
  with `~`. A path source has no `ref` and no `commit`.
- The argument of `claude plugin marketplace add` is `<owner>/<repo>`
  for `github:`, the URL for `git:` and `url:` (each with `#<ref>` when a
  ref is declared), and the absolute directory for `path:`.

Marketplaces whose source is a file or claude.ai are *unmanaged*:
`import` skips them (and their plugins) with a warning, `status` lists
them as information, and `apply` never touches them. Declaring a
marketplace whose name an unmanaged one already holds stops `apply` with
exit 1: remove the unmanaged one, or rename the declared one.

## [[plugin]]

| Key | Required | Value |
| --- | -------- | ----- |
| `id` | yes | `<plugin>@<marketplace>`, unique; the marketplace must be declared |
| `version` | yes | Non-empty string, the version recorded at import |
| `enabled` | yes | `true` or `false` |

Only user-scope plugins are managed. A declared plugin installed only at
project or local scope looks missing, and `apply` installs it at user
scope.

## [[skill_source]] and [[skill]]

External skills, pinned to a commit and linked into the profile's
`skills/` directory. Summary:

| Table | Key | Required | Value |
| ----- | --- | -------- | ----- |
| `[[skill_source]]` | `name` | yes | `[A-Za-z0-9][A-Za-z0-9._-]*`, unique |
| | `source` | yes | `github:<owner>/<repo>` or `git:<url>` |
| | `ref` | no | A branch or a tag |
| | `commit` | no | 40 lowercase hex characters |
| `[[skill]]` | `id` | yes | `<skill>@<source name>`; the skill name follows the profile name rule |
| | `path` | yes | Relative path in the repository, without `.`, `..` or empty segments |
| | `tree` | no | 40 lowercase hex characters, the git tree hash of the skill directory |

Full behaviour in [Skills](skills.md).

## [[mcp]]

User-scope MCP servers. Summary:

| Key | Required | Value |
| --- | -------- | ----- |
| `name` | yes | `[A-Za-z0-9][A-Za-z0-9._-]*`, unique |
| `transport` | yes | `stdio`, `http` or `sse` |
| `command` | `stdio` | Non-empty string |
| `args` | no, `stdio` only | List of strings |
| `env` | no, `stdio` only | Table of references |
| `url` | `http`, `sse` | Non-empty string |
| `headers` | no, `http` and `sse` only | Table of references |

A reference is `env:<NAME>`, `keychain:<service>[/<account>]` or
`value:<text>`. Full behaviour in [MCP servers](mcp-servers.md).

## [[tool]]

Command-line tools the profile needs. Summary:

| Key | Required | Value |
| --- | -------- | ----- |
| `name` | yes | `[A-Za-z0-9][A-Za-z0-9._-]*`, unique |
| `version` | no | A minimum, dotted numbers with two or more parts (`1.7`) |
| `check` | no | A command line whose first word is `name`; default `<name> --version` |
| `install` | no | `brew:<formula>`, `npm:<package>`, `uv:<package>`, `cargo:<crate>` or `script:<command>` |

Full behaviour in [Tools](tools.md).

## [account]

| Key | Required | Value |
| --- | -------- | ----- |
| `org_uuid` | yes | A UUID in hyphenated form |

With it, `apply` writes the login guide keys to `settings.json` and
`status` checks the signed-in organization. See
[Profiles](profiles.md#the-account-guide-and-the-organization-check).

## The target profile

`import` (when it reads or writes a profile), `status` and `apply` act on
one profile:

- `--profile NAME` when given;
- otherwise the profile resolved for the current directory, with
  `CLAUDE_SYNC_OVERRIDE` taken into account.

The profile directory must exist, otherwise the command exits 1 with
`profile 'work' does not exist (...): run claude-sync profile create work`.
Every `claude` command runs with `CLAUDE_CONFIG_DIR` set to that
directory and standard input from `/dev/null`, so no `claude` prompt can
wait.

## import

```sh
claude-sync import --source ~/.claude --output -     # print, write nothing
claude-sync import --profile work                    # refresh work's file
claude-sync import --profile work --yes              # overwrite, no prompt
claude-sync import --output manifest.toml --dry-run  # would write manifest.toml
```

`import` reads a configuration and produces a manifest:

- **Marketplaces and plugins** through `claude plugin marketplace list
  --json` and `claude plugin list --json`. A marketplace keeps the `ref`
  the CLI reports. When its local copy is a git repository of its own
  (its own top level, not a directory inside another repository) and the
  source is not `path:`, its current commit is recorded as `commit`.
  Plugins are the user-scope ones, with their version and enabled state.
  Unmanaged marketplaces and their plugins are skipped with
  `claude-sync: warning: skipped marketplace 'x' (file source, not managed
  by claude-sync)`.
- **Skills** from the links in the configuration's `skills/` directory
  (see [Skills](skills.md#import)).
- **MCP servers** from the top-level `mcpServers` of the configuration's
  `.claude.json` (see [MCP servers](mcp-servers.md#import)). The
  environment variables to export for new references are listed on
  standard error.
- **Tools** cannot be observed: the `[[tool]]` tables of the manifest
  being replaced are carried over.
- **Account**: an `[account]` table already in the file being replaced is
  kept.

Where it reads and writes:

| Options | Reads | Writes |
| ------- | ----- | ------ |
| none | The target profile | The target profile's `profile.toml` |
| `--source DIR` | `DIR` | The target profile's `profile.toml` |
| `--output FILE` | The target profile | `FILE` |
| `--source DIR --output FILE` | `DIR` | `FILE` (no profile needed) |
| `--output -` | As above | Standard output, only the manifest |

- `--source DIR` runs `claude` with `CLAUDE_CONFIG_DIR=DIR`. For
  `~/.claude` the MCP servers are read in `~/.claude.json`, where Claude
  Code keeps them without `CLAUDE_CONFIG_DIR`; for any other directory, in
  the `.claude.json` inside it.
- Without `--source` or without `--output`, a target profile is needed
  and its directory must exist.
- Overwriting an existing file asks `<file> exists; overwrite it?`
  (exit 3 without a TTY and without `--yes`; answering no prints
  `cancelled` and exits 0).
- `--dry-run` still reads everything (it runs `claude`), then prints
  `would write <file>` and writes nothing.
- What import keeps from the file it replaces (the `ref` of a skill
  source, a skill's `tree`, MCP references, tools, `[account]`) is read
  from the destination file. With `--output -` there is no destination
  file, so nothing is kept: a `value:` literal, for example, comes out as
  an `env:` reference.

## status

```sh
claude-sync status
claude-sync status --profile work
claude-sync status --profile work --json
```

Compares the manifest with the profile and lists each difference. It
exits 0 when there is no drift, 4 when there is, and 1 on an error
(invalid manifest, `claude` failing).

Text output:

```text
profile work: drift
  drift: missing formatter@example-tools: expected '1.2.0', found None
  info: unmanaged local-file: expected None, found 'file'
```

`--json` prints `{"profile": "work", "drift": true, "differences": [...]}`
where each difference is `{"kind", "subject", "expected", "actual",
"drift"}`.

Difference kinds for marketplaces, plugins and the account:

| Kind | Subject | Drift | Meaning |
| ---- | ------- | ----- | ------- |
| `missing` | marketplace or plugin | yes | Declared, not installed |
| `unlisted` | marketplace or plugin | yes | Installed, not declared |
| `source` | marketplace | yes | Installed from another source |
| `ref` | marketplace | yes | Installed with another ref |
| `commit` | marketplace | yes | Its copy moved from the recorded commit |
| `version` | plugin | yes | Another version is installed |
| `enabled` | plugin | yes | Another enabled state |
| `guide` | `account` | yes | Login guide keys absent or different |
| `org` | `account` | yes | Signed in to another organization |
| `unpinned` | marketplace | no | No `commit` recorded (not for `path:`) |
| `unmanaged` | marketplace | no | File or claude.ai source |

Plugins of an unmanaged marketplace are never reported as unlisted.
Skill kinds are listed in [Skills](skills.md#status) and MCP kinds in
[MCP servers](mcp-servers.md#status).

## apply

```sh
claude-sync apply --profile work --dry-run
claude-sync apply --profile work
claude-sync apply --profile work --prune
claude-sync apply --profile work --prune --yes
```

### Order of actions

1. **Tools.** `apply` checks the tools the profile declares (`[[tool]]`)
   and refuses with exit 1, naming each one that is missing or too old
   and suggesting `claude-sync doctor --fix`, before anything else, dry
   run included.
2. **Plan.** It reads the manifest and the profile, and plans every
   action. Planning can refuse, with exit 1 and before any change:
   a declared marketplace whose name an unmanaged one holds; a skill
   conflict (see [Skills](skills.md#apply)); an MCP reference that does
   not resolve, or a declared MCP server whose installed entry is
   unmanaged (see [MCP servers](mcp-servers.md#apply)).
3. **Dry run.** With `--dry-run`, it prints every planned action and
   exits 0.
4. **Confirmation.** When any action needs one, it asks one confirmation
   listing all of them (see below).
5. **Plugins and marketplaces**, as `claude` commands, in this order:
   - add each missing marketplace (`claude plugin marketplace add`);
   - for each marketplace installed with another source or ref (re-pin):
     remove it, add it again, then install each of its declared plugins
     and disable those declared disabled;
   - for each other declared plugin: install it when missing (then
     disable it when declared disabled), or enable or disable it to match;
   - with `--prune`: uninstall the unlisted plugins of the declared
     marketplaces, then remove the unlisted managed marketplaces (their
     plugins go with them).
6. **Skills**: clones, fetches, checkouts, then links.
7. **MCP servers**: adds, replacements, then prunes.
8. **Account guide**: writes `forceLoginMethod` and `forceLoginOrgUUID`
   when `[account]` is declared and they differ.
9. **Check.** It observes the profile again. A plugin version, a
   marketplace commit or a skill tree that still differs from the
   manifest is printed, followed by `accept with: claude-sync import`, and
   `apply` exits 4. Otherwise it exits 0.

The plugin commands always pin the user scope:
`claude plugin install <id> --scope user`, and likewise `uninstall`,
`enable` and `disable`. `install` is never given `--yes`.

### Confirmation

These actions need a confirmation; everything else (adding, installing,
enabling, linking a missing skill, replacing a stdio MCP server) does
not:

- every step of a marketplace re-pin, because removing a marketplace
  uninstalls its plugins and deletes their data;
- everything `--prune` removes;
- replacing a skill link that points elsewhere;
- replacing an `http` or `sse` MCP server, which drops its OAuth sign-in.

They are listed together in one question:

```text
These changes need your approval:
  claude plugin marketplace remove example-tools  (removes a marketplace: uninstalls its plugins, deletes their data)
  claude plugin marketplace add example/claude-plugins#v1.3
  claude plugin install formatter@example-tools --scope user
  replace ~/.config/claude-sync/profiles/work/skills/tdd -> ~/.config/claude-sync/sources/example-skills/skills/tdd
Continue?
```

Without a TTY and without `--yes`, `apply` prints the question on
standard error with `rerun with --yes` and exits 3, having changed
nothing. Answering no prints `cancelled` and exits 0.

### Dry run

`--dry-run` prints one line per planned action and changes nothing:

```text
would run: claude plugin marketplace add example/claude-plugins#v1.2
would run: claude plugin install formatter@example-tools --scope user
would run: git clone https://github.com/example/skills.git ~/.config/claude-sync/sources/example-skills
would link ~/.config/claude-sync/profiles/work/skills/tdd -> ~/.config/claude-sync/sources/example-skills/skills/tdd
would run: claude mcp add-json tools '{"type": "stdio", ..., "env": {"TOOLS_TOKEN": "***"}}' --scope user
would write forceLoginMethod and forceLoginOrgUUID to ~/.config/claude-sync/profiles/work
```

Every `env` and `headers` value is shown as `***`. A dry run still runs
the read-only commands it needs (`claude plugin ... list`, `git`) and
reads `keychain:` items to compare.

### Failures

- A failing `claude` or `git` command stops `apply` with exit 1 and shows
  the command (MCP values masked) and its error output. What ran before
  it stays done; run `apply` again once the cause is fixed.
- `apply` never approves a marketplace-declared command on your behalf:
  when `claude plugin install` needs that approval, the CLI fails, and
  `apply` stops with exit 1 and shows the CLI's message. Install that
  plugin by hand with `claude plugin install` in the profile, then run
  `apply` again.

### Prune

Without `--prune`, unlisted plugins, marketplaces, skill links and MCP
servers stay, and `status` keeps reporting them as `unlisted`. With it,
after the confirmation, `apply` removes:

- unlisted user-scope plugins of declared marketplaces;
- unlisted marketplaces with a managed source;
- links in `skills/` into the sources directory that the manifest does
  not list (nothing else in `skills/`);
- unlisted MCP servers, never an unmanaged one.

## Pinning and drift

The Claude Code CLI cannot install a given plugin version or check out a
given marketplace commit: it installs whatever the marketplace serves.
So for plugins and marketplaces:

- `ref` is a real pin of the branch or tag the marketplace is added
  with. A different ref is drift, and `apply` re-pins (with the
  confirmation).
- `commit` and `version` record what was installed when you imported.
  They are checks, not pins: when the upstream moves, `status` reports
  `commit` or `version` drift, and `apply` cannot undo it (it reports it
  again and exits 4).
- You accept the new state by running `claude-sync import` again, which
  records the new commit and versions, then committing `profile.toml`.
- A marketplace without a `commit` is `unpinned`: information, not
  drift. A `path:` marketplace is never pinned.

Skill sources are different: claude-sync runs git itself, so `apply`
checks out the recorded `commit` (see [Skills](skills.md)).

A typical upgrade:

```sh
claude-sync status --profile work      # exit 4: version drift
claude-sync import --profile work --yes
git -C ~/.config/claude-sync/profiles/work diff profile.toml
git -C ~/.config/claude-sync/profiles/work commit -am "chore: accept upstream"
```

## Marketplaces and plugins, end to end

On a new profile:

```sh
claude-sync profile create work
$EDITOR ~/.config/claude-sync/profiles/work/profile.toml
claude-sync apply --profile work --dry-run
claude-sync apply --profile work
claude-sync import --profile work --yes   # record commits and versions
claude-sync status --profile work         # exit 0
```

A manifest written by hand can carry any `version` for a plugin: `apply`
installs what the marketplace serves and then reports the version
difference (exit 4). The `import` afterwards records the real values.

From an existing profile, `import` first, then edit, then `apply`. To copy
what a profile declares (plugins, skills, MCP servers) to another one,
import with `--source` from the first into the second, then apply the
second:

```sh
claude-sync import --source ~/.config/claude-sync/profiles/perso --profile work
claude-sync apply --profile work
```
