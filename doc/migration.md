# Migration: init, uninstall, adopt

`init` moves an existing `~/.claude` and `~/.claude.json` into the
default profile; `uninstall` moves them back; `adopt` brings back what a
tool wrote to `~/.claude` afterwards. All three target macOS: they run
`pgrep` and `launchctl`.

The default profile is `default` in `config.toml`, else `perso`. Set it
with `claude-sync set-default` before you run `init` if you want another
name.

## Before you start

- **Quit every Claude Code session and the desktop app.** `init`,
  `uninstall` and `adopt` refuse, listing the processes
  (`Claude is running (claude 1234): quit it first`), while
  `pgrep -x claude` or `pgrep -x Claude` finds one. A Claude Code binary
  running under another name is not seen: the backup is the safety net.
- **Uninstall the plugins `init` cannot rebuild** from a manifest: those
  installed at another scope than user, and those from a marketplace
  claude-sync does not manage (a file or claude.ai source). `init`
  refuses and lists them.
- **Have the network**: the plugins are reinstalled at the end.
- **Run `claude-sync init --dry-run`** first.

## init

```sh
claude-sync init --dry-run   # check the files, print the steps
claude-sync init             # check, print the steps, ask once, migrate
claude-sync init --yes       # the same without the question
```

### Checks

`init` refuses with exit 1, changing nothing, when:

- `claude` or `Claude` runs (not checked by `--dry-run`);
- `~/.claude` is a symbolic link (move its target by hand) or does not
  exist (nothing to migrate);
- `~/.claude.json` does not exist (start Claude Code once to create it);
- `~/.claude/.claude.json` exists: it would clash with `~/.claude.json`,
  merge or remove it by hand;
- the default profile directory already exists (already migrated, or a
  profile made with `profile create`);
- `~/.claude` and the profiles directory (or its nearest existing parent)
  are on different file systems: the move is a rename;
- the free space where the backup goes is smaller than the size of
  `~/.claude` and `~/.claude.json`;
- a plugin cannot be rebuilt from a manifest (not checked by
  `--dry-run`), naming each one:
  `these plugins cannot be rebuilt from a manifest; uninstall them first:
  x@market (installed at project scope)`.

`--dry-run` runs only the file checks: it runs neither `pgrep` nor
`claude`, prints the steps and says that a real run also checks the
processes and the plugins.

### Steps

After the checks, `init` prints every step and asks one confirmation
(`Migrate now?`; exit 3 without a TTY and without `--yes`; no prints
`cancelled` and exits 0). Confirmed, it runs, in this order:

1. **Backup.** Writes `~/.claude` and `~/.claude.json` to
   `~/.config/claude-sync/backups/<UTC timestamp>.tar.gz`
   (`20261104T101500Z.tar.gz`): a gzip tar with relative member names
   (`.claude/...`, `.claude.json`), symbolic links stored as links, never
   followed, sockets and FIFOs skipped and named on standard error, one
   progress line per 1000 entries. The archive has mode 600 and the
   directory mode 700. The archive is listed back to check it can be
   read. Backups are never deleted for you.
2. **Manifest.** Reads the installed plugins and marketplaces of
   `~/.claude` (running `claude` with `CLAUDE_CONFIG_DIR` unset, so it
   reads `~/.claude.json` where it is and never creates
   `~/.claude/.claude.json`), the skill links (see [Skills](skills.md))
   and the MCP servers of `~/.claude.json` (see
   [MCP servers](mcp-servers.md)), listing the variables to export.
3. **Rename** `~/.claude` to `~/.config/claude-sync/profiles/<default>/`
   (the profiles directory is created with mode 700 when needed).
4. **Migration record.** Writes `.claude-sync-migration.json` in the
   profile (mode 600) and updates it after each later step: the old path,
   the steps done, the `settings.json` values rewritten, the links
   rewritten with their original text, and the LaunchAgent path.
   `uninstall` works from it. It is not meant for git; an allowlist
   `.gitignore` does not let it through.
5. **Rename** `~/.claude.json` to the profile's `.claude.json`.
6. **Symbolic links.** Relative links that pointed outside `~/.claude`,
   such as `skills/x -> ../../.agents/skills/x`, would break after the
   move: each one whose target exists becomes an absolute link to that
   target. A link that reached back in through the old path
   (`../.claude/rules`) gets a relative text to the same entry in the
   profile. Links inside that still work (`../rules`), absolute links and
   dangling links stay. `.git` is skipped and linked directories are not
   followed.
7. **settings.json.** Replaces the old `~/.claude` path by the profile
   path in the string values of `settings.json`, in its absolute, `~/`,
   `$HOME/` and `${HOME}/` spellings. A spelling counts when it starts the
   value or follows a character that cannot be in a path (not a letter,
   digit, `_`, `/`, `.`, `~` or `-`), and when no letter, digit, `_`, `.`
   or `-` follows it: `~/.claude/hooks/x.sh` changes, `~/.claude.json`
   and `~/.claude-code-config` do not. A changed file is written back with
   two-space indentation, keeping its mode.
8. **.gitignore.** When the profile is a git repository whose ignore
   rules ignore `profile.toml`, appends `!/profile.toml` to its
   `.gitignore`, so the manifest can be committed.
9. **Shell block.** Appends this block to `~/.zshrc` (creating the file
   when needed, following a symbolic link, keeping the mode), unless its
   first line is already there:

   ```sh
   # >>> claude-sync >>>
   command -v claude-sync >/dev/null && eval "$(claude-sync shell-init zsh)"
   # <<< claude-sync <<<
   ```

   An `eval` line you added yourself stays: keep one of the two.
10. **LaunchAgent.** Writes
    `~/Library/LaunchAgents/io.github.ylepalud.claude-sync.env.plist` and
    loads it with `launchctl bootstrap gui/<uid>` (after a `bootout` whose
    failure is ignored). At load and at every login it runs
    `/bin/launchctl setenv CLAUDE_CONFIG_DIR <profile>`, for the apps
    started outside a shell (the desktop app, IDEs): they use the default
    profile, whatever the directory. Apps already open keep their
    environment. Whether each app honours the variable is not documented.
11. **Plugins.** Removes the plugin caches and lists
    (`plugins/cache`, `plugins/marketplaces`,
    `plugins/installed_plugins.json`, `plugins/known_marketplaces.json`;
    `plugins/data` stays), because they hold absolute paths into the old
    `~/.claude`. Writes `profile.toml` (replacing one that `~/.claude` may
    have had) and runs `apply` on the profile, which installs the
    marketplaces and plugins again (network). This `apply` converges
    plugins only: skill links and MCP servers stay as they are and no
    skill source is cloned until you run `claude-sync apply` yourself.
12. **Markdown.** Lists the Markdown files that still name `~/.claude`
    (absolute or `~/` form), outside `projects/`, `plugins/` and `.git`.
    They are never rewritten: fix them by hand.

It ends with `migrated ~/.claude into ~/.config/claude-sync/profiles/perso`
and a reminder: sign in again with `/login` in each profile, because the
login follows the config dir.

### After init

```sh
exec zsh                                  # load the shell block
claude-sync which                         # perso
echo $CLAUDE_CONFIG_DIR                   # the perso profile directory
claude                                    # then /login
claude-sync status                        # skills still to converge?
claude-sync apply                         # clone skill sources, MCP servers
```

The imported manifest has no `[account]` and no `[[tool]]`; add them by
hand if you want them.

### When init fails

A failure stops `init` with exit 1 and prints how to recover at that
point. An interrupt (Ctrl-C) is handled the same way and exits 130.

| Where it stopped | What you see | What to do |
| ---------------- | ------------ | ---------- |
| Before the first rename (backup, manifest) | `init stopped before moving anything` | Nothing changed except a backup file; fix the cause and run `init` again |
| After the first rename, before the record | The rename is undone, then as above | As above |
| The undo of the first rename failed too | `... could not rename it back` | Rename the profile directory back to `~/.claude` by hand, or run `claude-sync uninstall --from-backup` |
| After the record is written | `init stopped after moving the configuration` | `claude-sync uninstall` moves it back, or `claude-sync uninstall --from-backup` restores the backup |
| The final plugin rebuild | `warning: rebuilding the plugins failed` (exit 4) | The profile is migrated: run `claude-sync apply` |

When the rebuild succeeds but a plugin version or a marketplace commit
moved upstream since you last used it, `init` prints it with
`accept with: claude-sync import` and exits 4.

## uninstall

```sh
claude-sync uninstall --dry-run
claude-sync uninstall
claude-sync uninstall --yes
```

`uninstall` reverses `init` from the migration record.

### Checks

It refuses with exit 1, changing nothing, when:

- `claude` or `Claude` runs (not checked by `--dry-run`);
- the default profile has no migration record (`nothing to uninstall`),
  or the record is damaged; when the profile is gone and
  `~/.claude/.claude-sync-migration.json` exists, an earlier uninstall
  already moved it back, and the message says what is left to finish by
  hand;
- `~/.claude` exists: move it aside, or bring it into the profile with
  `claude-sync adopt`;
- `~/.claude.json` exists and the profile's own `.claude.json` would
  replace it (the record says `init` moved it, or the profile has one):
  move it aside first.

A migration interrupted between its two renames is recovered:
`~/.claude.json`, still in place, stays.

### Steps

It prints every step and asks one confirmation
(`Move the profile back now?`). Confirmed, in this order:

1. Unload the LaunchAgent (`launchctl bootout`, failure ignored), delete
   its file, and run `launchctl unsetenv CLAUDE_CONFIG_DIR`.
2. Remove the `~/.zshrc` block, only when `init` added it.
3. Put `~/.claude` back in `settings.json`. Values added under the profile
   path since the migration are rewritten too, which is what you want
   once the profile is `~/.claude` again.
4. Give the links `init` rewrote their original text back.
5. Remove the `!/profile.toml` line, only when `init` added it.
6. Check again that `~/.claude` and `~/.claude.json` are absent.
7. Rename the profile directory to `~/.claude`, and its `.claude.json` to
   `~/.claude.json` when it has one.
8. Delete the migration record (after the renames, so a failed rename can
   be retried).
9. When `init` had removed the plugin caches: remove the caches and lists
   of `~/.claude` again and rebuild them from `profile.toml`, running
   `claude` with `CLAUDE_CONFIG_DIR` unset (network). This installs the
   current upstream versions; a version that moved is printed with
   `the plugins were rebuilt with the upstream versions` and the exit code
   is 4. Then delete `profile.toml`. A failing rebuild is a warning
   (exit 4) and keeps `profile.toml`: install the plugins it lists with
   `claude plugin install`.

Skills are never cloned or relinked: the skill links keep their targets.
MCP servers stay as they are in `.claude.json`; no `claude mcp` command
runs. Other profiles, `config.toml`, the skill sources in `sources/` and
the backups stay.

### When uninstall fails

| Where it stopped | What to do |
| ---------------- | ---------- |
| Before the profile is renamed back | Run `claude-sync uninstall` again (moving aside, or adopting, a `~/.claude` recreated meanwhile), or `claude-sync uninstall --from-backup` |
| After the rename back | Finish by hand as the message says: move `~/.claude/.claude.json` to `~/.claude.json` if it is still there, then delete `~/.claude/.claude-sync-migration.json` |
| The plugin rebuild | `~/.claude` is back: install the plugins listed in `~/.claude/profile.toml` with `claude plugin install` |

An interrupt (Ctrl-C) prints the same recovery and exits 130.

## uninstall --from-backup

```sh
claude-sync uninstall --from-backup --dry-run
claude-sync uninstall --from-backup          # the latest backup
claude-sync uninstall --from-backup FILE     # that backup
```

Restores a backup instead of moving the profile back. Use it when the
migration failed half way and the record cannot help, or to return to the
exact state before `init`. It needs no migration record.

1. Refuses while `claude` or `Claude` runs (not checked by `--dry-run`).
2. Picks `FILE`, or the latest `*.tar.gz` in `backups/` (by name, which is
   the UTC timestamp), and checks the whole archive before anything
   moves: only `.claude/...` and `.claude.json`, relative names without
   `..`, no duplicate, only files, directories, symbolic links and hard
   links to an earlier file. Anything else refuses the restore, naming the
   member.
3. Prints the steps and asks `Restore the backup now?`.
4. Unloads and deletes the LaunchAgent and runs
   `launchctl unsetenv CLAUDE_CONFIG_DIR`.
5. Removes the `~/.zshrc` block, only when a readable migration record in
   the default profile says `init` added it (otherwise the block is
   treated as yours).
6. Renames whatever exists of `~/.claude`, `~/.claude.json` and the
   default profile directory with a `.failed-<UTC timestamp>` suffix
   (`~/.claude.failed-20261104T101500123456Z`). Nothing is deleted.
7. Extracts the backup into a staging directory inside your home
   directory, checking that every member, and every hard link target,
   resolves inside it, then renames `.claude` and `.claude.json` into
   place. Symbolic links keep their stored text.

The plugins are not rebuilt: the backup holds their caches. Remove the
`.failed-*` entries yourself once you have checked them. A failure part
way names what was moved aside and says to rerun
`claude-sync uninstall --from-backup` or to rename them back by hand.

## adopt

A tool started without `CLAUDE_CONFIG_DIR` (a shell without the snippet,
a cron job, an app the LaunchAgent did not reach) can recreate
`~/.claude` and `~/.claude.json`. Once the default profile exists, the
shell integration warns once per shell:

```text
claude-sync: ~/.claude exists again; claude-sync adopt moves it into a profile
```

```sh
claude-sync adopt --dry-run           # list the moves and conflicts
claude-sync adopt                     # into the default profile
claude-sync adopt --profile work --yes
```

`adopt` moves what it can into the profile (`--profile NAME`, else the
default profile):

- each entry of `~/.claude` whose name the profile lacks is moved into
  it (`move ~/.claude/skills/new to .../profiles/perso/skills/new`);
- a directory both have is searched the same way, entry by entry;
- any other entry is a conflict, reported and left in place
  (`conflict: ~/.claude/settings.json stays, .../settings.json exists`);
- `~/.claude.json` becomes the profile's `.claude.json` when the profile
  has none, else it is a conflict;
- directories of `~/.claude` left empty are removed, and `~/.claude`
  itself when it ends empty.

One confirmation (`Move and remove these entries now?`) covers the moves
and removals. When only conflicts remain, nothing changes and nothing is
asked: merge them by hand. When neither `~/.claude` nor `~/.claude.json`
exists, it prints `nothing to adopt` and exits 0.

`adopt` refuses with exit 1 while `claude` or `Claude` runs (not checked
by `--dry-run`), when the profile does not exist, and when `~/.claude` is
a symbolic link or not a directory. A failure part way says what moved
and to rerun `claude-sync adopt` for the rest.
