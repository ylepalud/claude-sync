# migration Specification

## Purpose
Move the existing Claude Code configuration into the default claude-sync
profile and back, safely and reversibly, and bring back what tools write to
`~/.claude` afterwards.

## Requirements

### Requirement: Preconditions
`init`, `uninstall` and `adopt` SHALL refuse with exit code 1, changing
nothing, while a Claude Code CLI process (`claude`) or the Claude desktop app
(`Claude`) runs, listing them. `init` SHALL also refuse when `~/.claude` is
missing or is a symbolic link, when `~/.claude.json` is missing (Claude
Code has never started), when the default profile directory already
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
verify it can be listed; produce the manifest of `~/.claude` (running the `claude` CLI with
`CLAUDE_CONFIG_DIR` unset, so it reads `~/.claude.json` where it is and
never creates `~/.claude/.claude.json`); rename
`~/.claude` to the default profile directory; write the migration record
`.claude-sync-migration.json` in the profile (untracked), and update it
after each later step; rename `~/.claude.json` into the profile as
`.claude.json`; recreate every
relative symbolic link whose target lies outside `~/.claude` as an absolute
link to that target (links pointing inside stay relative; `.git` skipped);
replace the old `~/.claude` path, written absolute or as `~/.claude`,
`$HOME/.claude` or `${HOME}/.claude`, in the string values of the profile's
`settings.json` wherever it is not preceded by a path character (letter,
digit, `_`, `/`, `.`, `~`, `-`) and not followed by a name character
(letter, digit, `_`, `.`, `-`), keeping the notation it was written in
when the profile lies under the home directory (else writing the absolute
path); when the
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
with `run claude-sync apply`, and init exits 4. An interrupt (Ctrl-C) is
handled like a failure at that point and exits with code 130. The printed
plan SHALL list the steps in the order they run.

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
`claude-sync uninstall` SHALL refuse when the profile has no migration
record, when `~/.claude` exists, or when `~/.claude.json` exists although the
record says init already moved it (a migration interrupted between the two
renames is recovered by uninstall). Confirmed (same
confirmation and dry-run rules as init), it SHALL unload and delete the
LaunchAgent and run `launchctl unsetenv CLAUDE_CONFIG_DIR`, remove the
`~/.zshrc` block when init added it, reverse the recorded `settings.json`
rewrite and symbolic link rewrites, remove the `!/profile.toml` line when
init added it, check again that `~/.claude` and `~/.claude.json` are absent,
rename the default profile directory back to `~/.claude` and its
`.claude.json` to `~/.claude.json`, delete the migration record (after the
renames, so a failed rename can be retried), then, when init had removed
the plugin caches, remove the plugin caches and lists, rebuild them with apply in `~/.claude` with `CLAUDE_CONFIG_DIR`
unset, delete `profile.toml` when the rebuild succeeded, and leave other
profiles and the backups in place. With `--from-backup [FILE]` (default: the latest backup)
it SHALL instead unload the LaunchAgent, unset the variable, remove the
shell block only when the profile's record says init added it, move whatever exists of `~/.claude`, `~/.claude.json` and the
default profile directory aside with a `.failed-<timestamp>` suffix (never
deleting them), and extract the backup with a filter that refuses absolute
or escaping member names.

#### Scenario: Round trip
- **WHEN** the user runs `claude-sync init --yes` then `claude-sync uninstall --yes`
- **THEN** `~/.claude` and `~/.claude.json` exist again with the same files and symbolic links as before (plugin caches rebuilt), `settings.json` names `~/.claude` again, `launchctl unsetenv CLAUDE_CONFIG_DIR` was run, and neither the shell block, the LaunchAgent nor the migration record remains

#### Scenario: Interrupted between the renames
- **WHEN** init stopped after renaming `~/.claude` but before moving `~/.claude.json`
- **THEN** `claude-sync uninstall --yes` moves the profile back to `~/.claude` and leaves `~/.claude.json` in place

#### Scenario: From backup
- **WHEN** the migration failed half way and the user runs `claude-sync uninstall --from-backup --yes`
- **THEN** `~/.claude` and `~/.claude.json` are restored from the latest backup

### Requirement: Adopt
`claude-sync adopt [--profile NAME]` (default: the default profile) SHALL
refuse a `~/.claude` that is a symbolic link or not a directory, list the
entries of `~/.claude` (and `~/.claude.json` if present), move each
entry whose name does not exist in the profile into it, report every
conflict and leave it in place, and remove `~/.claude` when it ends empty.
It SHALL ask a confirmation before moving or removing anything (including
empty directories), support `--dry-run`, and exit 0 with a message
when there is nothing to adopt.

#### Scenario: Adopt a recreated directory
- **WHEN** a tool created `~/.claude/skills/new-skill` and the profile has no `skills/new-skill`
- **THEN** after `claude-sync adopt --yes` the skill is in the profile and `~/.claude` is gone

#### Scenario: Conflict kept
- **WHEN** `~/.claude/settings.json` and the profile's `settings.json` both exist
- **THEN** adopt reports the conflict, leaves both files, and keeps `~/.claude`

### Requirement: Skills during migration
When `init` and `uninstall` converge the profile, they SHALL converge
plugins only: `init` records the imported skill tables in `profile.toml` and
leaves every skill link as it is; `uninstall` restores links as recorded and
never clones or relinks skills. The user converges skills later with
`claude-sync apply`.

#### Scenario: Init leaves skill links
- **WHEN** `~/.claude/skills/tdd` links to `~/.agents/skills/tdd` and the user confirms `claude-sync init`
- **THEN** `profile.toml` declares the skill, the link still resolves to `~/.agents/skills/tdd`, and no source is cloned

### Requirement: MCP servers during migration
When `init` and `uninstall` converge the profile, they SHALL leave MCP
servers as they are: `init` records the imported `[[mcp]]` tables in
`profile.toml` without changing the servers in `.claude.json`, and
`uninstall` never adds, replaces or removes a server. The user converges
MCP servers later with `claude-sync apply`.

#### Scenario: Init leaves MCP servers
- **WHEN** the profile's `.claude.json` has a server whose `env` holds a literal value and the user confirms `claude-sync init`
- **THEN** `profile.toml` declares the server with an `env:` reference and `.claude.json` still holds the literal value
