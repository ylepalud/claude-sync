# claude-sync

Keep several Claude Code user configurations (profiles) strictly isolated on
one machine, and switch between them automatically by directory.

Each profile is a separate `CLAUDE_CONFIG_DIR` under
`~/.config/claude-sync/profiles/<name>/`, with its own settings, skills,
plugins, MCP servers, history and login. A declarative `profile.toml` in each
profile records what is installed, at which version.

Status: under construction. Only the CLI frame (`version`, `help`) and the
leak guard exist today; see the roadmap below and `openspec/changes/` for the
planned work.

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
2. [ ] `shell-init` and profile resolution.
3. [ ] `init` / `uninstall` with backup and migration.
4. [ ] `import` / `status` / `apply` for plugins and marketplaces.
5. [ ] Skills, MCP, settings, machine `[tools]`.

## License

MIT
