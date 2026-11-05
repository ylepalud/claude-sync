# Troubleshooting

Messages are shown as claude-sync prints them, after the
`claude-sync: error:` prefix. Rerun any command with `CLAUDE_SYNC_DEBUG=1`
to see the traceback behind an error.

## General

**`internal error, rerun with CLAUDE_SYNC_DEBUG=1 for details`**
An unexpected failure. Rerun with `CLAUDE_SYNC_DEBUG=1` and read the
traceback; it usually points to an unreadable file or an unexpected
output of an external program.

**`<question>` followed by `rerun with --yes`, exit 3**
The command needed a confirmation and standard input is not a
terminal (a script, a pipe, an agent). Read the question, then rerun
with `--yes`, or run it in a terminal.

**`claude not found on PATH`, `git ... cannot run`, `pgrep not found on
PATH`, `launchctl not found on PATH`**
The program is not on the `PATH` of the process running claude-sync.
Fix `PATH`, or install it (see [Installation](installation.md)).

## Configuration and profiles

**`<file>: invalid TOML: ...`, `unknown key ...`, `missing field ...`,
`invalid profile name ...`**
`config.toml` is invalid; every command that reads it stops, and the
shell snippet is not loaded (the shell starts without it). Fix the line
the message names, or move the file aside: without it the default is
`perso` with no mapping.

**`match path '...' duplicates '...'`**
Two mappings normalize to the same directory (`~/Dev/work` and
`~/Dev/work/`). Remove one with `claude-sync unmap` or by hand.

**`match path '/' maps the root directory`**, **`cannot map the root
directory /`**
Mapping `/` is refused; set the default with `claude-sync set-default`
instead.

**`<dir>: not an existing directory`** (map)
`map` needs the directory to exist. Create it first. Watch out for a
`~` that your shell expanded to another home (inside quotes it is
expanded by claude-sync instead).

**`no mapping for <path>`** (unmap)
Compare with `claude-sync config`; the path is matched after `~`
expansion and symbolic link resolution.

**`invalid CLAUDE_SYNC_OVERRIDE '...'`**
The variable holds an invalid name, probably inherited from another
environment. `claude-sync-use --auto` or `unset CLAUDE_SYNC_OVERRIDE`.

**`profile 'work' does not exist (...): run claude-sync profile create work`**
`status`, `apply`, `import` and `adopt` need the profile directory.
Create it, or check which profile was resolved with `claude-sync which`
(an override or a mapping may point elsewhere than you think).

**`profile 'work' already exists (...)`** (profile create)
Nothing was changed. Use the existing profile, or remove its directory
yourself if you really want to start over.

**`invalid organization UUID '...'`**
`--org-uuid` takes a hyphenated UUID, such as
`00000000-0000-0000-0000-000000000000`.

**`git is required to create a profile but was not found`**, **`git init
failed: ...`**
Install git, or fix the error git reports; nothing is left behind.

## Shell integration

**The prompt does not show `claude:<profile>`**
The `eval` line runs before your theme sets `RPROMPT`, or the theme
rewrites `RPROMPT` in its own hook. Move the line after the theme, or
set `CLAUDE_SYNC_PROMPT=0` and display `$CLAUDE_SYNC_PROFILE` yourself.
Check also that `CLAUDE_SYNC_PROMPT` is not `0`.

**A new mapping does not apply in an open shell**
Open shells keep the mappings they were started with. Run
`claude-sync-reload`.

**`CLAUDE_CONFIG_DIR` is not set in a mapped directory**
The profile is not initialized (the prompt shows `?`). Create it with
`claude-sync profile create <name>`, or run `init` for the default
profile.

**`claude-sync: ignoring invalid CLAUDE_SYNC_OVERRIDE ...`**
The shell inherited an invalid override. `claude-sync-use --auto`.

**`claude-sync-use: invalid profile name ...`**
Names are `[a-z0-9][a-z0-9-]*`, ASCII only.

**`claude-sync: ~/.claude exists again; claude-sync adopt moves it into a
profile`**
Something started Claude Code without `CLAUDE_CONFIG_DIR`. Run
`claude-sync adopt --dry-run`, then `claude-sync adopt`. To find the
culprit, look at what you started outside a zsh with the snippet
(another shell, a script, an app opened before the LaunchAgent ran).

## Manifest, status and apply

**`<file>: ...` naming `profile.toml`**
The manifest is invalid; the message names the table and key. The
rules are in [The manifest](manifest.md#validation). With skill
sources, `apply` also reads every other profile's manifest, so the file
named may be another profile's.

**`plugin 'x@market' uses undeclared marketplace 'market'`**
Add the `[[marketplace]]` table, or fix the plugin id.

**`` `claude plugin ...` failed: ... ``**
The Claude Code CLI failed; its error output follows. Common causes:
the network, a marketplace that no longer serves a plugin, a `ref`
that does not exist upstream. Fix it and run `apply` again: what ran
before the failure stays done.

**`` `claude plugin install ...` failed `` asking for an approval**
The marketplace declares a command that needs your approval, and
`apply` never gives it for you. Install that plugin yourself in a
shell where the profile is active (`claude plugin install <id> --scope
user`), then run `apply` again.

**`marketplace 'x' is declared, but the profile has a file marketplace of
that name, managed outside claude-sync`**
Remove the unmanaged marketplace with `claude plugin marketplace
remove`, or rename the declared one.

**`field '...' missing or not ... in ...`, `expected a JSON list of
objects`, `invalid JSON`**
The `claude` CLI printed JSON of a shape claude-sync does not know,
probably after a Claude Code update. claude-sync refuses to guess;
report it with the output of `claude plugin list --json`.

**`status` exits 4 with `version` or `commit` drift after `apply`**
The marketplace moved upstream; the CLI cannot install an older
version. Accept it with `claude-sync import`, then commit
`profile.toml`. See [Pinning and drift](manifest.md#pinning-and-drift).

**`status` exits 4 with `guide account`**
`[account]` is declared and `settings.json` lacks the login guide
keys. Run `apply`.

**`status` exits 4 with `org account`**
The profile is signed in to another organization than `org_uuid`. Run
`/login` in that profile and pick the right organization.

**`profile 'work' needs tools that are not ok`**
`apply` checks the profile's `[[tool]]` tables first, even for a dry
run. Run `claude-sync doctor --fix`, or fix the tool by hand.

## Skills

**`~/.../skills/tdd is not a link: move it away to install
tdd@example-skills, or remove the skill from the manifest`**
A real directory has the skill's name. claude-sync never replaces it.
Rename or move it (it may be your own skill), then run `apply`.

**`~/.config/claude-sync/sources/x has local changes: commit or discard
them, then apply again`**
Someone edited the shared clone. Inspect with
`git -C ~/.config/claude-sync/sources/x status`, then discard
(`git -C ... checkout -- .`, `git -C ... clean -fd`) or keep the
changes elsewhere.

**`~/.config/claude-sync/sources/x is a clone of ..., not of ...`**
The clone's `origin` differs from the declared source. Remove the
clone directory (it is only a clone) or give the source another name.

**`skill source 'x': profile 'work' declares ... profile 'perso' declares
...`**
Two profiles disagree on a shared source. Align `source` and `commit`
in both manifests, or rename the source in one of them so each gets
its own clone.

**`unknown ref 'x' in <clone>`**
The declared `ref` exists neither as a branch nor as a tag upstream,
even after a fetch. Fix `ref`.

**`skill-elsewhere` right after an import**
The links still point into `~/.agents/skills`. Run `apply`, then
`import` again to record the commit (see
[Skills](skills.md#after-an-import-from-the-lock-file)).

**`skipped ...: ... has no remote`, `... is not a skill source`**
`import` cannot trace that link to a repository. Declare the skill by
hand, or leave it as one of your own skills.

## MCP servers

**`MCP server 'x': env.KEY: keychain:...: Keychain item not found`**
Create the item (`security add-generic-password -s SERVICE [-a
ACCOUNT] -w`) or fix the reference. Nothing was changed.

**`the security tool failed (exit N)`**, **`cannot run the security
tool`**
Not on macOS, or the Keychain is locked or access was denied in the
dialog. The tool's output is never shown; run `security
find-generic-password -s SERVICE -w` yourself to see why.

**`... must be env:, keychain: or value: ...`**
A value of `env` or `headers` is a bare string. Wrap it: `value:` for a
non-secret literal, `env:` or `keychain:` for a secret.

**`MCP server 'x' is declared, but the profile's entry has fields
claude-sync does not manage (...)`**
Remove the server with `claude mcp remove x -s user` (apply then adds
the declared one), or drop it from the manifest.

**`MCP server 'x': ... would become 1X_KEY, which starts with a digit`**,
**`... would both use NAME`** (import)
The variable import would make is invalid or taken. Rename the server
or the key, or write the reference into the manifest yourself.

**`` `claude mcp add-json ...` failed: ... (run apply again) ``**
The server was removed and the add failed: it is now absent. Fix the
cause and run `apply` again.

**A server fails to authenticate after `apply`**
An `env:NAME` reference needs `NAME` exported where Claude Code
starts; otherwise the server receives the literal `${NAME}`.
`claude mcp list` warns about it. An `http` or `sse` server that was
replaced lost its OAuth sign-in: sign in to it again.

**Import turned a `value:` into an `env:` reference**
You imported with `--output -` or to a new file: import keeps
references only from the file it replaces. Import into the profile
(`claude-sync import --profile NAME`) instead.

## Tools

**A tool is `missing` although it is installed**
The check command exited non-zero, timed out (10 seconds), or is not
on the `PATH` claude-sync sees (nvm, pyenv and similar set up `PATH` in
your shell startup files). Run the check command yourself in the same
environment.

**A tool is `too-old` although it is recent**
Its version is read from standard output only, as the first dotted
number. Set a `check` that prints it there (`gh version`), or drop
`version`. After `--fix`, `still too-old: ..., found first at <path>`
names the binary that shadows the new one on `PATH`.

**`<manager> not found on PATH, needed by <recipe>`**
Install the package manager, or change the recipe.

**`skipped (needs an interactive confirmation): <name>`**
A `script:` recipe never runs without an answer typed on a terminal.
Run `claude-sync doctor --fix` in a terminal.

**`conflict <tool>: perso ...; work ...`**
Two profiles give different recipes. Make them agree; the first
profile in name order wins in the meantime.

## Migration

**`Claude is running (claude 1234, Claude 5678): quit it first`**
Quit every Claude Code session and the desktop app. A stuck process:
check it with `ps -p <pid>`.

**`` `pgrep -x claude` failed: ... ``**
`pgrep` failed in another way than "no process"; claude-sync does not
take that as "nothing runs". Check `pgrep` on your system.

**`~/.claude/.claude.json exists and would clash with ~/.claude.json`**
A Claude Code started with `CLAUDE_CONFIG_DIR=~/.claude` created it.
`claude-sync import --source ~/.claude` runs `claude` that way, so it
can be the cause. Compare it with `~/.claude.json`, keep what you need
in `~/.claude.json`, and move the inner file aside, then run `init`
again.

**`these plugins cannot be rebuilt from a manifest; uninstall them first`**
Uninstall each plugin named (project or local scope, or from a file or
claude.ai marketplace), migrate, then install them again in the
profile.

**`... are not on the same file system`**
`~/.claude` and `~/.config/claude-sync/profiles` must be on one file
system. Point `XDG_CONFIG_HOME` to a directory on the same volume, or
move `~/.claude` there first.

**`not enough free space for the backup`**
Free space, or move large session history out of `~/.claude/projects`
first.

**`warning: rebuilding the plugins failed`** (init, exit 4)
The profile is migrated and usable; some plugins are missing. Run
`claude-sync apply` once the cause (often the network) is fixed.

**`profile 'perso' has no migration record (...): nothing to uninstall`**
The default profile was not created by `init` (or the record was
deleted). Nothing to reverse; use `--from-backup` to restore a backup.

**`~/.claude exists: move it aside, or bring it into the profile with
claude-sync adopt`** (uninstall)
Something recreated `~/.claude`. Run `adopt`, or move it aside, then
run `uninstall` again.

**`~/.claude.json exists, and the profile's own state file would replace
it: move it aside first`**
Something recreated `~/.claude.json`. Move it aside (or merge it), then
run `uninstall` again.

**`damaged migration record ...`**
The record cannot be read. Use `claude-sync uninstall --from-backup`.

**`no backup in ~/.config/claude-sync/backups`**, **`cannot read the
backup ...`**, **`backup member '...' refused: ...`**
Pass another backup with `--from-backup FILE`. A refused member means
the archive holds something a claude-sync backup cannot (an absolute
or escaping name, another top-level entry): it was not written by
`init`, or was altered.

**`~/.claude.failed-... exists: rerun in a moment`**
Two restores in the same microsecond; rerun.

**`<zshrc>: '# >>> claude-sync >>>' without '# <<< claude-sync <<<'`**
The block in `~/.zshrc` was edited. Restore the end marker or remove
the block by hand, then rerun.

**`adopt stopped part way: what moved is in ...`**
Rerun `claude-sync adopt` for the rest.

**Desktop app or IDE uses the wrong profile**
The LaunchAgent sets the default profile at login, for every app.
Apps opened before it ran keep their environment: quit and reopen
them. Whether an app honours `CLAUDE_CONFIG_DIR` is up to the app.
