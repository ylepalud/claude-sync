## Why

Profiles exist, resolve per directory and can be rebuilt from a manifest,
but the personal configuration still lives in `~/.claude`, outside any
profile. This step moves it into the default profile safely and reversibly,
so every Claude Code configuration on the machine is a claude-sync profile,
and keeps it that way when a tool recreates `~/.claude`.

## What Changes

- `claude-sync init`: refuses while Claude Code runs; backs up `~/.claude`
  and `~/.claude.json`; imports the manifest; moves both into the default
  profile; rebuilds plugins with `apply`; rewrites relative symlinks as
  absolute and the old path in `settings.json`; lets `profile.toml` through
  an allowlist `.gitignore`; adds the shell block to `~/.zshrc`; installs a
  LaunchAgent that sets `CLAUDE_CONFIG_DIR` for GUI apps; lists Markdown
  files still naming `~/.claude` and reminds to `/login` per profile. One
  confirmation, `--dry-run`.
- `claude-sync uninstall`: moves the default profile back, reverses the
  `settings.json` rewrite, rebuilds plugins there, removes the shell block
  and the LaunchAgent; `--from-backup` restores the backup instead.
- `claude-sync adopt`: moves a recreated `~/.claude` into a profile without
  overwriting anything; the shell snippet warns once per shell when
  `~/.claude` reappears after migration.
- Non-goals: skills, MCP servers, general settings and machine `[tools]`
  (step 5); IDE integration beyond the LaunchAgent.

## Capabilities

### New Capabilities
- `migration`: init, uninstall and adopt.

### Modified Capabilities
- `shell-integration`: a warning when `~/.claude` exists again after
  migration.

## Impact

- New modules for the migration steps and adapters for `pgrep` and
  `launchctl`, with test stubs and guards like the one for `claude`.
- Touches the real `~/.claude`, `~/.claude.json`, `~/.zshrc` and
  `~/Library/LaunchAgents` only when the user runs `init`, `uninstall` or
  `adopt`; tests never do.

Reviewed against ae52cef by fable on 2026-11-03
