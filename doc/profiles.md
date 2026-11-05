# Profiles

This page covers the configuration file that maps directories to
profiles, the commands that read and edit it, `profile create`, and the
account guide that ties a profile to an organization.

## config.toml

The file is `$XDG_CONFIG_HOME/claude-sync/config.toml`, or
`~/.config/claude-sync/config.toml` when `XDG_CONFIG_HOME` is unset or
empty. It is optional: without it, the configuration is
`default = "perso"` with no mapping.

```toml
default = "perso"

[[match]]
path = "~/Dev/work"
profile = "work"

[[match]]
path = "~/Dev/work/oss"
profile = "perso"
```

| Key | Type | Meaning |
| --- | ---- | ------- |
| `default` | string, required | Profile used where no mapping applies |
| `[[match]]` | array of tables | Zero or more mappings |
| `match.path` | non-empty string, required | A directory; `~` is expanded |
| `match.profile` | string, required | The profile for that directory and everything below it |

Every command that reads the file fails with exit code 1, naming the file
and the problem, when it holds:

- invalid TOML or invalid UTF-8;
- an unknown key, at the top level or in a match;
- a missing `default`, or a match without `path` or `profile`;
- a profile name that does not match `[a-z0-9][a-z0-9-]*`;
- a mapping of the root directory `/`;
- two mappings whose paths are the same once normalized (`~/Dev/work` and
  `~/Dev/work/` for example).

Edit the file with `map`, `unmap` and `set-default` rather than by hand.
They write it atomically with mode 600 (its directory with mode 700),
keep every other entry, and store a path under the home directory with a
leading `~`.

## The resolution rule

The profile of a directory is, in order:

1. `CLAUDE_SYNC_OVERRIDE` when it is set (see
   [Shell integration](shell-integration.md)); `claude-sync which` fails
   with exit 1 when it is set to an invalid name;
2. the profile of the mapping whose path is the longest one equal to the
   directory or one of its parents;
3. the default profile.

Paths are compared as absolute paths, with `~` expanded and symbolic links
resolved, and a mapping matches whole path components only. With the file
above:

| Directory | Profile | Why |
| --------- | ------- | --- |
| `~/Dev/work` | `work` | Equal to a mapping |
| `~/Dev/work/api` | `work` | Below `~/Dev/work` |
| `~/Dev/work/oss/lib` | `perso` | `~/Dev/work/oss` is longer |
| `~/Dev/workshop` | `perso` (default) | `workshop` is not the component `work` |
| `~/w/api`, with `~/w` a link to `~/Dev/work` | `work` | Links are resolved |

The commands that act on "the profile of the current directory" (`status`,
`apply` and `import` without `--profile`) use this rule, override
included.

## which

```sh
claude-sync which                        # profile of the current directory
claude-sync which ~/Dev/work/api
claude-sync which ~/Dev/work/api --json
```

Prints the profile name. With `--json`:

```json
{"profile": "work", "source": "match", "match": "~/Dev/work",
 "config_dir": "/Users/me/.config/claude-sync/profiles/work",
 "initialized": false}
```

| Field | Meaning |
| ----- | ------- |
| `profile` | The resolved profile |
| `source` | `override`, `match` or `default` |
| `match` | The matching path as stored in the file, or `null` |
| `config_dir` | The profile directory (absolute) |
| `initialized` | Whether that directory exists |

## list

```sh
claude-sync list
claude-sync list --json
```

Lists every known profile: the default, every mapped profile, and every
directory under `profiles/` whose name is a valid profile name, sorted by
name. In text, `*` marks the default, `(not initialized)` a profile
without its directory, followed by its mapped paths:

```text
* perso
  work (not initialized) ~/Dev/work
```

`--json` prints `{"profiles": [{"name", "default", "initialized",
"paths"}]}`.

## config

```sh
claude-sync config
claude-sync config --json
```

Prints the file path, whether it exists, the default and the mappings:

```text
file: /Users/me/.config/claude-sync/config.toml
exists: true
default: perso
~/Dev/work -> work
```

`--json` prints `{"file", "exists", "default", "matches": [{"path",
"profile"}]}`. Without a file, `exists` is false and the defaults are
shown.

## map

```sh
claude-sync map ~/Dev/work work
claude-sync map ~/Dev/work work --dry-run   # would map ~/Dev/work -> work
claude-sync map ~/Dev/work other --yes      # replace without asking
```

Maps `DIR` and everything below it to `PROFILE`, creating the file when
needed.

- `PROFILE` must be a valid name (exit 1 otherwise). It does not need to
  exist yet.
- `DIR` must be an existing directory other than `/` (exit 1 otherwise,
  nothing written).
- The stored path is the directory's on-disk spelling: on a
  case-insensitive file system, `map ~/dev/work work` stores `~/Dev/work`,
  the spelling the shell sees in `$PWD`.
- Mapping a directory to the profile it already has prints
  `already mapped: ~/Dev/work -> work`, writes nothing and exits 0.
- Replacing the profile of a mapped directory asks
  `~/Dev/work is already mapped to work; replace it with other?`. Without
  a TTY and without `--yes`, it writes nothing and exits 3.
- `--dry-run` prints `would map <path> -> <profile>` or
  `would replace <path> -> <profile>` and writes nothing.

After a write it prints `run claude-sync-reload in open shells to apply`
on standard error.

## unmap

```sh
claude-sync unmap ~/Dev/work
claude-sync unmap ~/Dev/work --dry-run      # would unmap ~/Dev/work
```

Removes the mapping whose normalized path equals `DIR`. There is no
confirmation. A directory with no mapping is an error:
`no mapping for <path>`, exit 1. The directory does not need to exist.

## set-default

```sh
claude-sync set-default perso
claude-sync set-default work --dry-run      # would set default to work
```

Sets `default`, keeping the mappings, and creates the file when needed.
There is no confirmation. Remember that `init` and `uninstall` act on the
default profile.

## profile create

```sh
claude-sync profile create perso
claude-sync profile create work --org-uuid 00000000-0000-0000-0000-000000000000
claude-sync profile create work --dry-run
```

Creates `profiles/<name>/`:

- the profiles directory, when missing, and the profile directory, both
  with mode 700;
- `profile.toml` with no marketplace and no plugin: empty, or holding only
  `[account] org_uuid` with `--org-uuid`;
- a git repository (`git init`), with this `.gitignore`, so the
  repository tracks only `profile.toml` and `.gitignore`:

  ```text
  /*
  !/.gitignore
  !/profile.toml
  ```

No commit is made. The rest of the profile, `settings.json` and
`.claude.json` included, can hold tokens and stays out of git.

The name must follow the profile name rule, and `--org-uuid` must be a
UUID in its hyphenated form (`00000000-0000-0000-0000-000000000000`; no
braces, no `urn:uuid:` prefix).
An existing directory is an error (exit 1) and nothing changes. git must
be on `PATH`. `--dry-run` prints what would be created.

`profile` has one action, `create`. A new profile is empty: fill its
manifest by hand or with `import`, then run `apply` (see
[The manifest](manifest.md)), and sign in with `/login` in a shell where
the profile is active.

## The account guide and the organization check

A profile tied to an organization declares it in its manifest:

```toml
[account]
org_uuid = "00000000-0000-0000-0000-000000000000"
```

`apply` then writes two keys to the profile's `settings.json`, creating
the file when needed and keeping every other key:

```json
{
  "forceLoginMethod": "claudeai",
  "forceLoginOrgUUID": ["00000000-0000-0000-0000-000000000000"]
}
```

These keys steer the login screen of that profile to that organization.
Outside managed settings they do not prevent a sign-in to another
organization. `status` is the check:

- `guide account` drift when the keys are absent or point elsewhere
  (`forceLoginMethod` not `claudeai`, or `forceLoginOrgUUID` not a list
  of exactly that UUID);
- `org account` drift when the profile is signed in
  (`oauthAccount.organizationUuid` in the profile's `.claude.json`) to
  another organization. Before the first sign-in there is nothing to
  compare.

Without `[account]`, `apply` does not touch those keys. `import` keeps an
`[account]` table already in the file it overwrites.
