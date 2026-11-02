## Why

claude-sync exists to give each directory tree its own Claude Code profile.
Step 1 delivered only the CLI frame. This step adds the core rule (which
profile applies where) and the zsh integration that applies it on every
directory change, so the right `CLAUDE_CONFIG_DIR` is set before `claude`
starts, and the active profile is always visible.

## What Changes

- `config.toml` under `~/.config/claude-sync/` (or `$XDG_CONFIG_HOME`):
  optional, `default` profile plus `[[match]]` path to profile entries.
  Without it: default `perso`, no mappings.
- Read commands: `claude-sync which [DIR]` (the reference resolution),
  `claude-sync list`, `claude-sync config`, all with `--json`.
- Mutating commands: `claude-sync map DIR PROFILE`, `claude-sync unmap DIR`,
  `claude-sync set-default PROFILE`, with `--dry-run` and `--yes`.
- `claude-sync shell-init zsh`: prints a zsh snippet that compiles the
  mappings into a matcher run on `chpwd`, exports `CLAUDE_SYNC_PROFILE`
  always and `CLAUDE_CONFIG_DIR` only when the profile directory exists,
  shows `claude:<profile>` in `RPROMPT`, and defines `claude-sync-use` and
  `claude-sync-reload`.
- Safe before migration: with no profile directory yet, `CLAUDE_CONFIG_DIR`
  stays unset and the current `~/.claude` keeps working.

## Capabilities

### New Capabilities
- `profile-resolution`: the configuration file, the resolution rule and the
  commands that read and edit it.
- `shell-integration`: the zsh snippet, its environment variables, prompt
  segment, override and reload.

### Modified Capabilities
- `cli-conventions`: `shell-init` joins `help` as exempt from `--json`,
  since it prints shell code, not state.

## Impact

- New modules under `src/claude_sync/` (config, resolution, zsh snippet) and
  six commands; tests including a zsh/Python parity test (needs `zsh` in CI,
  present on GitHub's Ubuntu runners only after `apt-get install zsh`).
- README: usage of the new commands and the `.zshrc` line.
- No change to `~/.claude` or the Keychain; launchctl and `.zshrc` editing
  come with `init` in step 3.

Reviewed against 136fa85 by fable on 2026-11-02
