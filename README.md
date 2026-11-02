# claude-sync

Keep several Claude Code user configurations (profiles) strictly isolated on
one machine, and switch between them automatically by directory.

Each profile is a separate `CLAUDE_CONFIG_DIR` under
`~/.config/claude-sync/profiles/<name>/`, with its own settings, skills,
plugins, MCP servers, history and login. A declarative `profile.toml` in each
profile records what is installed, at which version.

Status: under construction. The CLI frame, the leak guard, profile
resolution, the zsh integration, `profile create` and the manifest commands
(`import`, `status`, `apply`) exist today. Moving an existing `~/.claude`
into a profile (`init`) comes in step 4; see the roadmap below and
`openspec/changes/` for the planned work.

## Install

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) and
Python 3.11 or later. The package has no runtime dependencies.

```sh
uv tool install git+https://github.com/ylepalud/claude-sync
claude-sync --version
```

Or from a clone, with `install.sh` (it checks that `uv` is on `PATH`, runs
`uv tool install --force` on `CLAUDE_SYNC_SOURCE`, which defaults to the
GitHub URL above, then prints `claude-sync --version`):

```sh
git clone https://github.com/ylepalud/claude-sync
cd claude-sync
CLAUDE_SYNC_SOURCE=. ./install.sh
```

## Usage

```sh
claude-sync help --all     # top-level help, then the help of every command
claude-sync help version   # same as `claude-sync version --help`
claude-sync version --json # {"version": ..., "python": ...}
```

Conventions every command follows:

- `--help` lists examples and the exit codes the command can return.
- Read commands accept `--json` and print one JSON document.
- Mutating commands accept `--dry-run` (print the planned actions, change
  nothing) and `--yes` (answer every confirmation).
- Without a TTY on stdin and without `--yes`, a command refuses instead of
  prompting, and exits 3.
- `CLAUDE_SYNC_DEBUG=1` prints the traceback of an error.

Exit codes:

| Code | Meaning |
| ---- | ------- |
| 0 | success |
| 1 | runtime error |
| 2 | usage error |
| 3 | confirmation required but not given (rerun with `--yes`) |
| 4 | drift detected: state differs from what is declared |

## Profiles

The configuration file is `~/.config/claude-sync/config.toml`
(`$XDG_CONFIG_HOME/claude-sync/config.toml` when `XDG_CONFIG_HOME` is set). It
holds the default profile and the directories mapped to a profile:

```toml
default = "perso"

[[match]]
path = "~/Dev/work"
profile = "work"
```

Without the file, the default is `perso` and nothing is mapped. Unknown keys,
missing fields, invalid names, a mapping of `/` and two mappings of the same
path are errors that name the file. A profile name
matches `[a-z0-9][a-z0-9-]*`.

A directory gets the profile of the longest mapped path that is the directory
itself or one of its parents, compared after `~` expansion and symlink
resolution, else the default. `~/Dev/work/api` is `work`; `~/Dev/workshop` is
not.

Edit the file with the commands rather than by hand:

```sh
claude-sync map ~/Dev/work work      # map a directory and everything below it
claude-sync unmap ~/Dev/work         # remove a mapping (exit 1 if there is none)
claude-sync set-default perso        # profile used outside mapped directories
```

`map` needs an existing directory (not `/`) and stores its on-disk spelling, so
`~/dev/work` is stored as `~/Dev/work` on a case-insensitive file system.
Mapping a directory to the profile it already has prints `already mapped` and
writes nothing. Replacing the profile of an already mapped directory asks for a
confirmation (`--yes` to skip it). After a write, these commands remind you to run
`claude-sync-reload` in open shells.

Read the configuration and the result:

```sh
claude-sync which [DIR]   # profile of DIR (default: the current directory)
claude-sync list          # every known profile, * marks the default
claude-sync config        # file path, whether it exists, default, mappings
```

All three accept `--json`.

### Shell integration (zsh)

Add this line to `~/.zshrc`, after oh-my-zsh and the theme are loaded (the
snippet captures the theme's `RPROMPT` once, when it is first evaluated):

```sh
eval "$(claude-sync shell-init zsh)"
```

The snippet embeds the mappings, so a directory change runs no external
process. On start and after every `cd` it:

- exports `CLAUDE_SYNC_PROFILE` with the resolved profile;
- exports `CLAUDE_CONFIG_DIR` as the profile directory, `profiles/<profile>/`
  next to the configuration file, only when that directory exists
  (`claude-sync profile create`, see below); until then a
  `CLAUDE_CONFIG_DIR` you set yourself is kept;
- shows `claude:<profile>` at the start of `RPROMPT`, with a `?` when the
  profile directory does not exist yet (`claude:work?`). Set
  `CLAUDE_SYNC_PROMPT=0` before the `eval` line to turn the segment off.

It also defines two shell functions:

```sh
claude-sync-use work     # use the work profile in this shell, whatever the directory
claude-sync-use --auto   # back to the mappings
claude-sync-reload       # apply configuration changes to this shell
```

`claude-sync-use` exports `CLAUDE_SYNC_OVERRIDE`, which `claude-sync which`
honours too. Open shells keep the mappings they were started with until
`claude-sync-reload`. Only zsh is supported.

## Manifest

Each profile declares its marketplaces and user-scope plugins in
`profile.toml`, at the root of the profile directory:

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

[account]
org_uuid = "00000000-0000-0000-0000-000000000000"
```

- `source` is `github:<owner>/<repo>`, `git:<url>`, `url:<url>` or
  `path:<dir>`. Marketplaces with a file or claude.ai source are not managed:
  `import` skips them with a warning, `status` lists them as information and
  `apply` never touches them.
- `ref` is a branch or a tag, passed to `claude plugin marketplace add` as
  `<source>#<ref>`. It cannot be a commit: the CLI fails to clone one.
- `commit` and `version` record what was installed when you imported. The
  CLI cannot install a given commit or plugin version, so they are checks,
  not pins: when the upstream moves, `status` reports drift and you accept
  it by running `import` again.
- A `path` source has neither `ref` nor `commit`.
- A plugin id is `<plugin>@<marketplace>`, and the marketplace must be
  declared. Unknown keys, missing fields and duplicates are errors that name
  the file.

Create a profile, then fill its manifest from an existing configuration:

```sh
claude-sync profile create perso
claude-sync profile create work --org-uuid 00000000-0000-0000-0000-000000000000
claude-sync import --source ~/.claude --output -   # print, write nothing
claude-sync import --source ~/.claude --profile perso
```

`profile create` makes `profiles/<name>/` next to the configuration file
(mode 700) with a `profile.toml` that is empty, or holds only `[account]`
with `--org-uuid`, and a git repository whose `.gitignore` lets through only
`profile.toml` and itself: the rest of the profile, `settings.json` included,
can hold tokens (in `env`, for example) and stays out of Git. No commit is
made. An existing profile is an error.

`import` reads the plugins and marketplaces through the `claude` CLI. Without
`--source` it reads the target profile; without `--output` it writes that
profile's `profile.toml`. The target profile is `--profile NAME`, else the
profile of the current directory, and its directory must exist. An
`[account]` table already in the written file is kept; overwriting the file
asks for a confirmation.

Compare and converge:

```sh
claude-sync status --profile work           # exit 4 on drift
claude-sync apply --profile work --dry-run  # print the claude commands
claude-sync apply --profile work
claude-sync apply --profile work --prune    # also remove what is not listed
```

`status` lists every difference: a missing or unlisted marketplace or plugin,
another source, ref, commit, version or enabled state, the account keys
below, and the signed-in organization. A marketplace without a recorded
`commit`, and an unmanaged one, are information, not drift.

`apply` adds missing marketplaces, installs missing plugins and enables or
disables plugins to match. A marketplace installed with another source or
ref is removed and added again, and its plugins reinstalled. Removing a
marketplace uninstalls its plugins and deletes their data, so those steps,
and everything `--prune` removes, are listed in one confirmation first.
`apply` never approves a marketplace-declared command for you: it stops and
shows the CLI message. When a version or commit still differs afterwards,
the upstream moved: `apply` says so and exits 4, and `import` accepts it.

### Account

With an `[account]` table, `apply` writes `forceLoginMethod = "claudeai"` and
`forceLoginOrgUUID = ["<org_uuid>"]` to the profile's `settings.json`. Outside
managed settings these keys only guide the login screen; they do not stop a
sign-in to another organization. `status` is the check: it reports drift when
the keys are absent or different, and when the signed-in organization
(`oauthAccount.organizationUuid` in the profile's `.claude.json`) is not
`org_uuid`. Before the first sign-in there is nothing to compare.

## Development

```sh
uv sync                 # create .venv with the dev group (pytest, ruff)
uv run pytest
uv run ruff check
uv run ruff format --check
scripts/install-hooks   # git config core.hooksPath .githooks
```

CI (`.github/workflows/ci.yml`) runs ruff and pytest on Python 3.11 and 3.13,
and the leak guard below.

## Leak guard

This repository is public. `scripts/check-denylist` blocks any term from a
private denylist from reaching it.

- The denylist lives outside the repository, in
  `~/.config/claude-sync/denylist.txt`: one term per line, blank lines and
  lines starting with `#` ignored, case-insensitive. The `DENYLIST`
  environment variable, when set, replaces the file.
- It is never committed: `denylist.txt` is in `.gitignore`, and the scanner
  refuses (exit 4) when a tracked file has that name.
- Findings print as `<location>: term #<n>`, the term's position in the
  denylist. The term, the matching line and any path that contains a term are
  never printed, so CI logs are safe to publish.
- Git hooks (after `scripts/install-hooks`): `pre-commit` scans the staged
  changes (and runs `gitleaks` when installed), `commit-msg` scans the
  message, `pre-push` scans the full history.
- CI needs a repository secret named `DENYLIST` holding the terms; the
  `leak-guard` job fails when it is missing or empty. It scans the tree, the
  history, commit messages, author identities, branch and tag names, annotated
  tag messages, the pull request title and body, and runs `gitleaks` on the
  full history.

Run it by hand:

```sh
scripts/check-denylist --help
scripts/check-denylist --tree --history
```

## Roadmap

1. [x] CLI skeleton and leak guard.
2. [x] `shell-init` and profile resolution.
3. [x] Manifest: `profile create`, `import` / `status` / `apply` for plugins
   and marketplaces.
4. [ ] `init` / `uninstall` with backup and migration.
5. [ ] Skills, MCP, settings, machine `[tools]`.

## License

MIT
