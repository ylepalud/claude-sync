# Security

claude-sync handles configuration that can hold tokens, and it is
developed in a public repository. This page says where secrets go, what
claude-sync never prints or touches, and how the repository keeps private
names out.

## Secrets in profiles

### What may hold a secret

- `settings.json` of a profile can hold tokens, in `env` for example.
- `.claude.json` holds the account state and the MCP servers, possibly
  with resolved values.
- The login itself is in the macOS Keychain, under an entry that follows
  the config dir; claude-sync never reads or copies it.

The profile repository made by `profile create` tracks only
`profile.toml` and `.gitignore`, so neither file can be committed by
accident. A profile `init` migrated keeps your own `.gitignore`: check
that it does not let `settings.json` or `.claude.json` through before you
push it anywhere.

### What the manifest holds

`profile.toml` never holds a secret. MCP server values are references:

| Reference | Value on disk | Where |
| --------- | ------------- | ----- |
| `env:NAME` | none, only `${NAME}` | Expanded by Claude Code from its environment when it starts the server |
| `keychain:SERVICE[/ACCOUNT]` | the resolved value | In clear in the profile's `.claude.json` (mode 600, outside git) |
| `value:TEXT` | `TEXT` | In `profile.toml`, so in git: never a secret |

`command`, `args` and `url` are literal and end up in `profile.toml`:
keep secrets out of them, or use a placeholder Claude Code expands.

`import` never writes a literal it finds in `env` or `headers`: it
replaces it with `env:<SERVER>_<KEY>` and lists the variable name (never
the value) on standard error. The literal stays in `.claude.json` until
`apply` replaces the server.

### Masking

claude-sync never prints a value of `env` or `headers`:

- `status` names field paths only (`headers.Authorization`), never a
  value, even for a difference;
- the dry run, the confirmation and the error of a failing `claude mcp`
  command show every such value, placeholders included, as `***`;
- the error output of a failing `claude mcp` command is scrubbed of the
  resolved values, raw and JSON-escaped, before it is shown;
- errors about a reference name the server, the key and the reference,
  never the output of `security`;
- manifest errors name the key, never the text of a reference.

### Keychain caveats

- **Access dialog.** On the first read of an item, macOS may open a
  dialog asking to allow `security` to access it. It is a window, not a
  terminal prompt, so `--yes` does not answer it. `status` and
  `apply --dry-run` read the items too, to compare.
- **`ps` exposure.** While `claude mcp add-json` runs, the resolved value
  is one of its arguments, visible to `ps` for other processes of the
  machine for that instant.
- **Clear text in `.claude.json`.** Claude Code does not read the
  Keychain, so the value is written to the profile's `.claude.json`.

Prefer `env:` when the variable is available in the environment Claude
Code starts in: the value then never touches the disk.

## What claude-sync never touches

- **The login.** Credentials and Keychain login entries are never read,
  copied or moved. Sign in once per profile with `/login`.
- **`~/.agents`.** Links into `~/.agents/skills` and the lock file
  `~/.agents/.skill-lock.json` are read by `import`, never changed.
- **Files inside a skill clone**, other than through `git clone`,
  `git fetch` and `git checkout --detach`; a clone with local changes
  stops `apply`.
- **Real directories in `skills/`**: your own skills are never replaced
  or removed; one in the way of a declared skill stops `apply`.
- **Unmanaged things**: marketplaces from a file or claude.ai,
  project and local scope plugins, MCP servers with fields claude-sync
  does not model, project `.mcp.json` files.
- **Markdown files**: `init` lists those that name `~/.claude`, never
  rewrites them.
- **Backups**: never deleted. `uninstall --from-backup` moves the current
  state aside with a `.failed-<timestamp>` suffix instead of deleting it.
- **Marketplace-declared commands**: `apply` never approves them on your
  behalf (`claude plugin install` is never given `--yes`).

Every `claude` command runs with standard input from `/dev/null`, so
none can wait on a hidden prompt. Without a TTY,
claude-sync itself never prompts: a command that needs a confirmation
exits 3 instead.

Files claude-sync writes itself (`config.toml`, `profile.toml`,
`settings.json` when it adds the account guide, the migration record) are
written atomically with mode 600, and the directories it creates for them
with mode 700. Backups are mode 600 in a mode 700 directory.

## Tool installation

`doctor --fix` runs package managers and, for `script:` recipes,
arbitrary shell from a profile you may have pulled. Every command is
printed in full before it runs, managers by absolute path. A `script:`
recipe always needs an interactive confirmation on a terminal, even with
`--yes`, and is skipped without one. A `check` command runs without a
shell and its first word must be the tool's name, so a manifest cannot
make `doctor` run an arbitrary program as a check.

## The leak guard of this repository

This repository is public. `scripts/check-denylist` keeps any term from a
private denylist (employer, client, internal domain, work e-mail) out of
the repository: files, history, commit messages, branch and tag names and
pull requests. It concerns contributors, not users of the tool.

### The denylist

- Terms come from the `DENYLIST` environment variable when it is set,
  even empty; otherwise from `~/.config/claude-sync/denylist.txt` (this
  path does not follow `XDG_CONFIG_HOME`).
- One term per line; blank lines and lines starting with `#` are ignored;
  matching is case-insensitive.
- The list is never committed: `denylist.txt` is in `.gitignore`, and the
  scanner refuses to run (exit 4) when a tracked file has that name.
- It fails closed: no source, or no term, exits 3 instead of reporting a
  clean scan.

### What it scans

| Option | Scans |
| ------ | ----- |
| `--tree` | Tracked files and their paths; a tracked symbolic link's target path as text, never the file it points to |
| `--staged` | Staged added lines and staged paths |
| `--history` | Every added line, path, commit message and author or committer identity on every branch (merge commits included), every branch and tag name, every annotated tag message |
| `--message-file PATH` | A commit message file |
| `--text LABEL` | Free text on standard input, reported under `LABEL` |

Binary content is skipped.

### Findings never reveal the terms

A finding is printed as `<location>: term #<n>`, where `n` is the term's
1-based position in the denylist. The term, the matching line and any
path containing a term are never printed, so CI logs are safe to
publish:

| Location | Meaning |
| -------- | ------- |
| `<path>:<line>` | A line of a tracked or staged file |
| `path #<k>` | The path itself matches (`k`: position in the scanned list) |
| `<sha>:<path>:<line>` | An added line in the history |
| `<sha>: message` | A commit message |
| `<sha>: identity` | An author or committer name or e-mail |
| `ref #<k>` | A branch or tag name |
| `ref #<k>: tag message` | An annotated tag message |
| `message`, `<label>` | `--message-file`, `--text` |

Exit codes: 0 clean, 1 findings, 2 usage error, 3 denylist empty or
missing, 4 a tracked `denylist.txt` (refused), 5 internal failure
(details withheld, since they could carry file content or git output).

### Enforcement points

- **Git hooks**, after `scripts/install-hooks` (which sets
  `core.hooksPath` to `.githooks`):
  - `pre-commit` scans the staged changes, then runs
    `gitleaks git --staged --redact` when gitleaks is installed (a
    warning otherwise);
  - `commit-msg` scans the message;
  - `pre-push` scans the full history.
- **CI**, on every push to any branch and on every pull request opened,
  synchronized, reopened or edited: the `leak-guard` job fails when the
  `DENYLIST` repository secret is missing or empty (so a pull request
  from a fork fails), scans the tree and the full history, scans the pull
  request title and body (passed through the environment, never
  interpolated into the script), and runs a checksum-verified gitleaks
  binary over the full history.

```sh
scripts/check-denylist --help
scripts/check-denylist --tree --history
printf '%s' "candidate text" | scripts/check-denylist --text check
```
