# claude-sync

Keep several Claude Code user configurations (profiles) strictly isolated on
one machine, and switch between them automatically by directory.

Each profile is a separate `CLAUDE_CONFIG_DIR` under
`~/.config/claude-sync/profiles/<name>/`, with its own settings, skills,
plugins, MCP servers, history and login. A declarative `profile.toml` in each
profile records what is installed, at which version.

Status: under construction. The CLI frame, the leak guard, profile
resolution, the zsh integration, `profile create`, the manifest commands
(`import`, `status`, `apply`), the migration of an existing `~/.claude`
into a profile (`init`, `uninstall`, `adopt`) and external skill sources
(step 5a) exist today. MCP servers (5b) and machine tools (5c) come next;
see the roadmap below and `openspec/changes/` for the planned work.

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

`claude-sync init` appends an equivalent block for you (see Migration).

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

Each profile declares its marketplaces and user-scope plugins, and its
external skills (see Skills), in `profile.toml`, at the root of the profile
directory:

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

## Skills

A profile's own skills are real directories in its `skills/`, versioned by
the profile's git repository; claude-sync leaves them alone. External
skills, taken from someone else's repository, are declared in
`profile.toml`, pinned to a commit, and linked into `skills/`:

```toml
[[skill_source]]
name = "example-skills"
source = "github:example/skills"
ref = "main"
commit = "0123456789abcdef0123456789abcdef01234567"

[[skill]]
id = "tdd@example-skills"
path = "skills/engineering/tdd"
tree = "89abcdef0123456789abcdef0123456789abcdef"
```

- `source` is `github:<owner>/<repo>` or `git:<url>` (a local path works
  too). `ref` is an optional branch or tag; without it, the remote's
  default branch. `commit` is optional, 40 lowercase hex characters.
- A skill id is `<skill>@<source name>`: the skill name follows the profile
  name rule and becomes the link `skills/<skill>`; the source must be
  declared. `path` is the skill's directory in the repository, relative,
  without `.`, `..` or empty segments.
- `tree`, optional, is the git tree hash of that directory as installed.
- Unknown keys, missing fields, duplicates and invalid values are errors
  that name the file.

### Shared clones

Each source is cloned once per machine, in `sources/<name>/` next to the
configuration file (`~/.config/claude-sync/sources/<name>/`), and every
profile declaring that source name shares the clone. `skills/<skill>` in
each profile is an absolute link to `sources/<name>/<path>`. claude-sync
changes a clone only through `git clone`, `git fetch` and `git checkout
--detach`.

Since the clone is shared, a source name means one source at one commit on
the machine. `apply` reads the manifests of the other profiles and refuses,
naming both profiles and their commits, when one declares the same name
with another `source`, records another `commit` than the current profile,
or pins a commit the current profile leaves out. To use two commits of one
repository, give the sources two names.

### Import

`import` (see Manifest) also records the links of the profile's `skills/`:

- a link into `sources/<name>/` keeps the source name, its clone's `origin`
  (`https://github.com/<owner>/<repo>` with or without `.git` becomes
  `github:<owner>/<repo>`, any other URL `git:<url>`) and its checked-out
  commit;
- a link into another git checkout with a remote does the same, the source
  named after the checkout's directory;
- a link into `~/.agents/skills/<skill>`, installed by a third-party skills
  CLI, is read from that CLI's lock file `~/.agents/.skill-lock.json`
  (version 3, entries of type `github`): `source` gives
  `github:<owner>/<repo>`, the directory of `skillPath` gives `path`, and
  `skillFolderHash`, the git tree hash of the installed directory, gives
  `tree`. There is no commit. One source is made per repository, named
  after the first `pluginName` of its entries in file order, else
  `<owner>-<repo>`.

A name already taken gets `-2`, `-3`, and so on. Real skill directories are
left out; a link to anything else, into a checkout without a remote or into
the profile's own repository, and a lock entry missing or of another type,
are left out with a warning. A lock of another version is ignored with a
warning. From the manifest being replaced, import keeps the `ref` of a
source of the same name and source (a ref you added by hand), and the
`tree` of a skill of the same id and path, read again from the clone.

Right after an import from the lock, the links still point into
`~/.agents/skills`, and the source has no commit yet. `status` reports each
link as pointing elsewhere (`skill-elsewhere`, run `claude-sync apply`) and
the clone as missing, and exits 4; the missing commit is information. Run
`apply`, then `import` again to record the commit:

```sh
claude-sync import --profile perso   # skills still link into ~/.agents
claude-sync apply --profile perso    # clone, pin, relink (confirmation)
claude-sync import --profile perso   # record the commit apply checked out
claude-sync status --profile perso   # exit 0
```

### Status and apply

`status` also reports a declared skill without its link, a link pointing
elsewhere, a link into `sources/` that the manifest does not list, a
missing clone, a clone of another source, at another commit, off its
declared ref or with local changes, and a skill whose directory in the
clone has another tree than its recorded `tree`. A source without a
`commit` is information, not drift.

`apply` converges the skills after the plugins. Per source, it clones a
missing one (`--branch <ref>` when declared), fetches when the commit to
check out or the ref is absent, then checks out, detached:

- the recorded `commit`;
- without one, when skills record a `tree`: the newest commit of the ref
  where every such skill's directory has its recorded tree, that is, the
  version that was installed. When no commit matches them all, the newest
  one matching the most, and the others are reported as changed since
  install (exit 4, accept with `import`);
- without either: a new clone stays at the ref's head, an existing clone
  on its ref stays where it is, and one off its ref moves to the ref's
  head.

Then it links each missing skill, and replaces a link pointing elsewhere,
into `~/.agents` for example, after the confirmation that also covers the
plugins. `--dry-run` prints the `git` commands and link changes. A recorded
`tree` that still differs afterwards is reported like a moved plugin (exit
4).

`apply` stops with exit 1 before any change when:

- a real file or directory is at a declared skill's link path (move it
  away, or remove the skill from the manifest);
- a clone in `sources/` has another `origin` than its declared source;
- a clone with local changes would have to move to another commit (a dirty
  clone already at its commit is only reported by `status`);
- another profile declares the same source name differently (see Shared
  clones).

`--prune` also removes, after the confirmation, the links into `sources/`
that the manifest does not list, and nothing else: no real directory, no
link elsewhere, no clone. claude-sync never modifies or removes anything in
`~/.agents`; once no profile links into it, remove it with the tool that
installed it. `init` and `uninstall` leave skills alone (see Migration).

## Migration

`init` moves an existing `~/.claude` and `~/.claude.json` into the default
profile (`default` in `config.toml`, else `perso`); `uninstall` moves them
back. Both rely on `pgrep` and `launchctl`, so they target macOS.

Before you start:

- Quit every Claude Code session and the desktop app. `init`, `uninstall`
  and `adopt` refuse, listing the processes, while `pgrep -x claude` or
  `pgrep -x Claude` finds one. A Claude Code binary running under another
  name is not seen: the backup is the safety net.
- Uninstall the plugins `init` cannot rebuild from a manifest: those
  installed at another scope than user, and those from a marketplace
  claude-sync does not manage (a file or claude.ai source). `init` refuses
  and lists them.
- Have the network: the plugins are reinstalled at the end.

```sh
claude-sync init --dry-run   # check the files, print the steps
claude-sync init             # check, print the steps, ask once, migrate
```

`init` also refuses, changing nothing, when `~/.claude` is missing or a
symbolic link, when `~/.claude.json` is missing, when
`~/.claude/.claude.json` exists, when the default profile directory exists,
when `~/.claude` and the profiles directory are on different file systems
(the move is a rename), or when the free space is smaller than the
configuration. `--dry-run` checks only these: it runs neither `pgrep` nor
`claude`.

Once confirmed, it runs, in order:

1. Back up `~/.claude` and `~/.claude.json` to
   `~/.config/claude-sync/backups/<UTC timestamp>.tar.gz` (gzip tar, mode
   600, symbolic links stored as links, sockets and FIFOs skipped and
   named). Backups are never deleted for you.
2. Read the installed plugins and marketplaces, and the skill links (see
   Skills), for `profile.toml`.
3. Rename `~/.claude` to `~/.config/claude-sync/profiles/<default>/`.
4. Write the migration record `.claude-sync-migration.json` in the profile,
   updated after each later step. `uninstall` works from it; it is not
   meant for Git, and an allowlist `.gitignore` does not let it through.
5. Rename `~/.claude.json` to the profile's `.claude.json`.
6. Make absolute the relative symbolic links whose target lies outside
   `~/.claude`, such as `skills/x -> ../../.agents/skills/x`; a link that
   reached back in through `../.claude/` gets a relative text to the same
   entry.
7. Replace `~/.claude` by the profile path in the string values of
   `settings.json`, in its absolute, `~/`, `$HOME/` and `${HOME}/`
   spellings; `~/.claude.json` and similar names are left. A changed file
   is written back with two-space indentation.
8. Append `!/profile.toml` to the profile's `.gitignore` when the profile
   is a git repository that ignores `profile.toml`.
9. Append this block to `~/.zshrc`, unless its first line is already
   there. An `eval` line you added yourself stays: keep one of the two.

   ```sh
   # >>> claude-sync >>>
   command -v claude-sync >/dev/null && eval "$(claude-sync shell-init zsh)"
   # <<< claude-sync <<<
   ```

10. Write `~/Library/LaunchAgents/io.github.ylepalud.claude-sync.env.plist`
    and load it with `launchctl bootstrap gui/<uid>`. At load and at every
    login it runs `launchctl setenv CLAUDE_CONFIG_DIR <profile>`, for the
    apps started outside a shell (the desktop app, IDEs): they use the
    default profile, whatever the directory. Apps already open keep their
    environment. Whether each app honours the variable is not documented.
11. Remove the plugin caches and lists (`plugins/cache`,
    `plugins/marketplaces`, `installed_plugins.json`,
    `known_marketplaces.json`; `plugins/data` stays), write `profile.toml`
    and run `claude-sync apply`, which installs them again (network). This
    apply converges plugins only: skill links stay as they are and no
    source is cloned until you run `claude-sync apply` yourself.
12. List the Markdown files that still name `~/.claude` (`projects/`,
    `plugins/` and `.git` are not searched). They are never rewritten: fix
    them by hand.

Then sign in again with `/login` in each profile: the login follows the
config dir.

A failure or an interrupt (Ctrl-C, exit 130) stops `init` and prints how to
recover at that point:

- before the migration record is written, nothing changed: a first rename
  is undone (when that fails too, rename it back by hand, or restore the
  backup);
- after it, `claude-sync uninstall` moves the configuration back, and
  `claude-sync uninstall --from-backup` restores the backup;
- a failing plugin rebuild is a warning (exit 4): the profile is migrated,
  run `claude-sync apply`.

### Uninstall

```sh
claude-sync uninstall --dry-run
claude-sync uninstall
```

`uninstall` reverses `init` from the migration record. It refuses when the
profile has no record, when `~/.claude` exists (move it aside, or bring it
in with `adopt`), or when `~/.claude.json` exists and the profile's own
would replace it. In order, it unloads and deletes the LaunchAgent and runs
`launchctl unsetenv CLAUDE_CONFIG_DIR`; removes the `~/.zshrc` block and
the `!/profile.toml` line, each only when `init` added it; puts `~/.claude`
back in `settings.json` (values added under the profile path since are
rewritten too) and gives the links `init` made absolute their original text
back; renames the profile to `~/.claude` and its `.claude.json` to
`~/.claude.json`; deletes the record. When `init` had removed the plugin
caches, it then removes them again and rebuilds them from `profile.toml`
with `CLAUDE_CONFIG_DIR` unset (network), which installs the current
upstream versions, and deletes `profile.toml`. A failing rebuild is a
warning (exit 4) and keeps `profile.toml`: install the plugins it lists
with `claude plugin install`. Skills are never cloned or relinked: the
skill links keep their targets. Other profiles, `config.toml`, the skill
sources and the backups stay.

A failure before the profile is moved back can be retried with
`uninstall`; after it, the message says what is left to finish by hand.

```sh
claude-sync uninstall --from-backup        # the latest backup
claude-sync uninstall --from-backup FILE   # that backup
```

`--from-backup` needs no record. It checks the whole archive first (only
`.claude` and `.claude.json`, no absolute or escaping names), unloads the
LaunchAgent, unsets the variable, removes the `~/.zshrc` block when a
readable record says `init` added it, then renames whatever exists of
`~/.claude`, `~/.claude.json` and the default profile directory with a
`.failed-<UTC timestamp>` suffix and extracts the backup into the home
directory. Nothing is deleted: remove the `.failed-*` entries yourself once
you have checked them. The plugins are not rebuilt; the backup holds their
caches.

### Adopt

A tool started without `CLAUDE_CONFIG_DIR` can recreate `~/.claude`. Once the
default profile exists, the shell integration then warns once per shell,
on standard error:

```text
claude-sync: ~/.claude exists again; claude-sync adopt moves it into a profile
```

```sh
claude-sync adopt --dry-run          # list the moves and conflicts
claude-sync adopt                    # into the default profile
claude-sync adopt --profile work
```

`adopt` moves each entry of `~/.claude` whose name the profile lacks into
it, searches a directory both have the same way, and reports any other
entry as a conflict, left in place. `~/.claude.json` becomes the profile's
`.claude.json` when the profile has none. Directories left empty, and
`~/.claude` itself when it ends empty, are removed. One confirmation covers
the moves and removals; when only conflicts remain, nothing changes and
nothing is asked: merge them by hand. `adopt` refuses when the profile
does not exist, or when `~/.claude` is a symbolic link or not a directory.

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
4. [x] `init` / `uninstall` with backup and migration, `adopt`.
5. What the profile's git repository cannot carry (`settings.json` and the
   profile's own skills stay in git):
   - [x] 5a. External skill sources.
   - [ ] 5b. MCP servers.
   - [ ] 5c. Machine `[tools]`.

## License

MIT
