# claude-sync

Keep several Claude Code user configurations (profiles) strictly isolated on
one machine, and switch between them automatically by directory.

Each profile is a separate `CLAUDE_CONFIG_DIR` under
`~/.config/claude-sync/profiles/<name>/`, with its own settings, skills,
plugins, MCP servers, history and login. A declarative `profile.toml` in each
profile records what is installed, at which version.

Status: under construction. The CLI frame, the leak guard, profile
resolution and the zsh integration exist today. Profile directories are not
created yet (`init` comes in step 3); see the roadmap below and
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
missing fields and invalid names are errors that name the file. A profile name
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

Replacing the profile of an already mapped directory asks for a confirmation
(`--yes` to skip it). After a write, these commands remind you to run
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
  next to the configuration file, only when that directory exists. Step 3
  (`init`) creates the profile directories; until then a `CLAUDE_CONFIG_DIR`
  you set yourself is kept;
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
3. [ ] `init` / `uninstall` with backup and migration.
4. [ ] `import` / `status` / `apply` for plugins and marketplaces.
5. [ ] Skills, MCP, settings, machine `[tools]`.

## License

MIT
