## Purpose

Move the existing Claude Code configuration into the default claude-sync
profile and back, safely and reversibly, and bring back what tools write to
`~/.claude` afterwards.

## ADDED Requirements

### Requirement: Preconditions
`init`, `uninstall` and `adopt` SHALL refuse with exit code 1, changing
nothing, while a Claude Code CLI process (`claude`) or the Claude desktop app
(`Claude`) runs, listing them. `init` SHALL also refuse when `~/.claude` is
missing or is a symbolic link, when the default profile directory already
exists, when `~/.claude/.claude.json` exists, when `~/.claude` and the
profiles root (or its nearest existing parent) are on different file
systems, when the free space is smaller than the configuration size, or when
an installed plugin cannot be rebuilt from the manifest (installed at
another scope than user, or from a marketplace claude-sync does not manage),
naming each such plugin.

#### Scenario: Claude running
- **WHEN** a `claude` process runs and the user runs `claude-sync init --yes`
- **THEN** the exit code is 1, the process ids are listed and nothing changes

#### Scenario: Plugin that cannot be rebuilt
- **WHEN** a plugin is installed at project scope
- **THEN** `claude-sync init` exits with code 1, names the plugin and changes nothing

#### Scenario: Already migrated
- **WHEN** `profiles/perso/` exists
- **THEN** `claude-sync init` exits with code 1 and changes nothing

### Requirement: Init
`claude-sync init` SHALL print every planned step, ask one confirmation
(exit 3 without a TTY and without `--yes`), and with `--dry-run` change
nothing. Confirmed, it SHALL in order: write a gzip tar backup of `~/.claude`
and `~/.claude.json` (mode 600, symbolic links stored as links, relative
member names) under `backups/` (mode 700) next to the configuration file and
verify it can be listed; produce the manifest of `~/.claude`; rename
`~/.claude` to the default profile directory and `~/.claude.json` into it as
`.claude.json`; write the migration record `.claude-sync-migration.json` in
the profile (untracked) and update it after each later step; recreate every
relative symbolic link whose target lies outside `~/.claude` as an absolute
link to that target (links pointing inside stay relative; `.git` skipped);
replace the old `~/.claude` path in the string values of the profile's
`settings.json` where it is followed by `/` or ends the value; when the
profile's `.gitignore` ignores `profile.toml`, append `!/profile.toml`; add
a marked block evaluating the shell snippet to `~/.zshrc` unless present;
write and load a LaunchAgent that sets `CLAUDE_CONFIG_DIR` to the profile
directory at login; then remove the plugin caches and lists
(`plugins/cache`, `plugins/marketplaces`, `plugins/installed_plugins.json`,
`plugins/known_marketplaces.json`), write the manifest and run apply; and
finally list Markdown files still containing the old path and remind the
user to sign in again with `/login` in each profile. A failure SHALL stop
with exit code 1 and print the recovery for that point: before the first
rename nothing changed; between or after the renames, `claude-sync uninstall`
(which works from the record); a failure of the final apply is a warning
with `run claude-sync apply`, and init exits 4.

#### Scenario: Dry run
- **WHEN** the user runs `claude-sync init --dry-run`
- **THEN** every step is printed and no file, directory, shell block or LaunchAgent changes

#### Scenario: Migration
- **WHEN** the user confirms `claude-sync init` on a `~/.claude` with one plugin, a relative skills symlink and an absolute `~/.claude` path in `settings.json`
- **THEN** `~/.claude` and `~/.claude.json` no longer exist, `profiles/perso/` holds the configuration with `.claude.json`, the plugin is installed again through apply, the symlink is absolute and resolves, `settings.json` names the profile path, `~/.zshrc` has the block once, the LaunchAgent is loaded, and a backup exists

#### Scenario: Markdown listed, not changed
- **WHEN** a rule file in `~/.claude` mentions `~/.claude/hooks`
- **THEN** init lists that file and leaves its content unchanged

### Requirement: Uninstall
`claude-sync uninstall` SHALL refuse when `~/.claude` or `~/.claude.json`
exists, or when the profile has no migration record. Confirmed (same
confirmation and dry-run rules as init), it SHALL unload and delete the
LaunchAgent and run `launchctl unsetenv CLAUDE_CONFIG_DIR`, remove the
`~/.zshrc` block, reverse the recorded `settings.json` rewrite and symbolic
link rewrites, delete the migration record, rename the default profile
directory back to `~/.claude` and its `.claude.json` to `~/.claude.json`,
then remove the plugin caches and lists and rebuild them with apply in
`~/.claude` with `CLAUDE_CONFIG_DIR` unset, and leave other profiles and the
backups in place. With `--from-backup [FILE]` (default: the latest backup)
it SHALL instead unload the LaunchAgent, unset the variable, remove the
shell block, move whatever exists of `~/.claude`, `~/.claude.json` and the
default profile directory aside with a `.failed-<timestamp>` suffix (never
deleting them), and extract the backup with a filter that refuses absolute
or escaping member names.

#### Scenario: Round trip
- **WHEN** the user runs `claude-sync init --yes` then `claude-sync uninstall --yes`
- **THEN** `~/.claude` and `~/.claude.json` exist again with the same files and symbolic links as before (plugin caches rebuilt), `settings.json` names `~/.claude` again, `launchctl unsetenv CLAUDE_CONFIG_DIR` was run, and neither the shell block, the LaunchAgent nor the migration record remains

#### Scenario: From backup
- **WHEN** the migration failed half way and the user runs `claude-sync uninstall --from-backup --yes`
- **THEN** `~/.claude` and `~/.claude.json` are restored from the latest backup

### Requirement: Adopt
`claude-sync adopt [--profile NAME]` (default: the default profile) SHALL
list the entries of `~/.claude` (and `~/.claude.json` if present), move each
entry whose name does not exist in the profile into it, report every
conflict and leave it in place, and remove `~/.claude` when it ends empty.
It SHALL ask a confirmation, support `--dry-run`, and exit 0 with a message
when there is nothing to adopt.

#### Scenario: Adopt a recreated directory
- **WHEN** a tool created `~/.claude/skills/new-skill` and the profile has no `skills/new-skill`
- **THEN** after `claude-sync adopt --yes` the skill is in the profile and `~/.claude` is gone

#### Scenario: Conflict kept
- **WHEN** `~/.claude/settings.json` and the profile's `settings.json` both exist
- **THEN** adopt reports the conflict, leaves both files, and keeps `~/.claude`
