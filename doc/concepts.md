# Concepts

## Profiles

A profile is one complete Claude Code user configuration: settings,
`CLAUDE.md`, rules, hooks, skills, plugins, user-scope MCP servers,
session history and the login. claude-sync gives each profile its own
directory and makes Claude Code use it.

A profile has a name that matches `[a-z0-9][a-z0-9-]*`: lower-case ASCII
letters, digits and `-`, never starting with `-` (it would read as an
option). `perso`, `work` and `client-a` are valid; `Work`, `-x` and
`my_profile` are not.

A profile is *initialized* when its directory exists. A name can be known
(it is the default, or a directory is mapped to it) before its directory
exists: `claude-sync list` shows it as `(not initialized)` and the prompt
segment shows it with a `?`.

## CLAUDE_CONFIG_DIR

Claude Code reads its user configuration from `~/.claude` and keeps its
state (account, MCP servers, per-project data) in `~/.claude.json`. When
the environment variable `CLAUDE_CONFIG_DIR` is set, everything moves into
that directory, `.claude.json` included, and the login is stored under a
Keychain entry that follows the directory. claude-sync relies on that: a
profile is nothing more than a value of `CLAUDE_CONFIG_DIR`.

So that the variable is set without you thinking about it:

- the zsh snippet (see [Shell integration](shell-integration.md)) exports
  it on start and after every directory change, from the profile mapped to
  the current directory;
- after `claude-sync init`, a LaunchAgent sets it at login for the apps
  started outside a shell, to the default profile (see
  [Migration](migration.md)).

Because each profile has its own login, run `/login` once in each profile.

## The configuration directory

Everything claude-sync owns lives in one directory:
`$XDG_CONFIG_HOME/claude-sync/`, or `~/.config/claude-sync/` when
`XDG_CONFIG_HOME` is unset or empty. These pages write
`~/.config/claude-sync/` for short.

```text
~/.config/claude-sync/
  config.toml                           default profile and mappings (600)
  profiles/                             mode 700
    perso/                              one CLAUDE_CONFIG_DIR per profile
      profile.toml                      the manifest (600)
      .gitignore                        lets only profile.toml through
      .git/                             the profile's own repository
      settings.json, .claude.json, skills/, plugins/, projects/, ...
      .claude-sync-migration.json       only in a profile init migrated
    work/
  sources/
    <name>/                             one shared clone per skill source
  backups/                              mode 700
    <UTC timestamp>.tar.gz              written by init (600)
```

- `config.toml` is optional. claude-sync writes it with mode 600 in a
  directory of mode 700 when you run `map`, `unmap` or `set-default`.
- `profiles/<name>/` is created by `claude-sync profile create <name>`, or
  by `claude-sync init` for the default profile (the old `~/.claude`
  renamed).
- `sources/<name>/` holds the git clone of an external skill source,
  shared by every profile that declares a source of that name (see
  [Skills](skills.md)).
- `backups/` holds the archives `init` writes before it moves anything.
  claude-sync never deletes them.

Outside that directory, claude-sync writes only:

- a marked block in `~/.zshrc` (`init` adds it, `uninstall` removes it);
- the LaunchAgent
  `~/Library/LaunchAgents/io.github.ylepalud.claude-sync.env.plist`
  (`init` writes and loads it, `uninstall` unloads and deletes it);
- `~/.claude` and `~/.claude.json`, only when `init`, `uninstall` or
  `adopt` move them.

It reads, and never changes, `~/.agents/.skill-lock.json` and the links
into `~/.agents/skills/` that a third-party skills CLI installed.

## The default profile

The default profile applies to every directory that no mapping covers.
It is `default` in `config.toml`, and `perso` when there is no
configuration file. Change it with `claude-sync set-default <name>`.

The default profile also has two special roles:

- `init` migrates `~/.claude` into it, and `uninstall` moves it back;
- the LaunchAgent written by `init` points GUI apps at it.

## Resolution in one paragraph

A directory gets the profile of the longest mapped path that is the
directory itself or one of its parents, comparing whole path components
after `~` expansion and symbolic link resolution; otherwise the default
profile. `CLAUDE_SYNC_OVERRIDE`, set by `claude-sync-use`, wins over both.
The details are in [Profiles](profiles.md).

## The manifest

Each profile can describe itself in `profile.toml`: the marketplaces and
plugins it uses, its external skills, its user-scope MCP servers, the
command-line tools it needs and the organization it belongs to. The
manifest holds no secret, only references, and it is the one file the
profile's git repository tracks. `import` writes it from what is
installed, `status` compares, `apply` converges. See
[The manifest](manifest.md).

## Isolation guarantees

Within the shells that evaluate the snippet, and the processes they
start:

- each profile has its own settings, `CLAUDE.md`, rules, hooks, own
  skills, plugins and plugin data, user-scope MCP servers, history and
  login, because Claude Code reads all of them from `CLAUDE_CONFIG_DIR`;
- nothing is shared between profiles through links or a common base:
  copying something from one profile to another is a manual act;
- the profile repository created by `profile create` tracks only
  `profile.toml`, so `settings.json` and `.claude.json`, which can hold
  tokens, stay out of git;
- a `CLAUDE_CONFIG_DIR` you set yourself, outside the profiles directory,
  is remembered and given back when you enter a directory whose profile
  is not initialized.

## Limits of the isolation

- **Only zsh shells with the snippet.** A shell without it, a script run
  from cron, or any program started with a clean environment gets no
  `CLAUDE_CONFIG_DIR`, so Claude Code falls back to `~/.claude` and
  `~/.claude.json`, and may recreate them. The snippet warns once per
  shell when `~/.claude` exists again; `claude-sync adopt` brings it back
  into a profile.
- **GUI apps get the default profile.** After `init`, the LaunchAgent sets
  `CLAUDE_CONFIG_DIR` to the default profile at login, whatever directory
  an app later opens. Apps already open keep their environment. Whether
  each app honours the variable is not documented.
- **The account guide is not enforcement.** `[account] org_uuid` steers
  the login screen of a profile; it does not stop a sign-in to another
  organization. `status` detects such a sign-in and reports drift.
- **Project-level configuration is not per profile.** What a repository
  carries itself (a project `.mcp.json`, a project `.claude/` directory,
  project or local scope plugins) belongs to the repository, not to a
  profile. claude-sync manages user-scope plugins and MCP servers only.
- **The machine is shared.** Command-line tools, environment variables
  exported in your shell, Keychain items and `~/.agents` are the same for
  every profile. `[[tool]]` tables only check and install tools; they do
  not give a profile its own copy.
- **Skill clones are shared.** Two profiles that declare a skill source of
  the same name share one clone at one commit. To use two commits of one
  repository, give the sources two names.
- **Process detection is by name.** `init`, `uninstall` and `adopt`
  refuse while `pgrep -x claude` or `pgrep -x Claude` finds a process. A
  Claude Code binary running under another name is not seen; the backup
  `init` writes is the safety net.
- **Open shells keep their mappings.** The snippet embeds the
  configuration when it is evaluated. After `map`, `unmap` or
  `set-default`, run `claude-sync-reload` in each open shell.
