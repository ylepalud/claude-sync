# CLI reference

`claude-sync help --all` prints the help of every command; this page
gathers it with the behaviour behind each option. Commands are listed in
the order of `help`.

## Global conventions

### Synopsis

```text
claude-sync [-h] [--version] COMMAND ...
```

- `claude-sync` with no argument prints the top-level help and exits 0.
- `claude-sync --version` prints `claude-sync <version>`.
- `claude-sync COMMAND --help` and `claude-sync help COMMAND` print the
  same text: a one-line summary, a description, every option, examples
  and the exit codes the command can return.
- `python -m claude_sync` is the same program.

### Kinds of commands

| Kind | Commands | Options added |
| ---- | -------- | ------------- |
| Read | `version`, `which`, `list`, `config`, `status` | `--json` |
| Mutate | `map`, `unmap`, `set-default`, `profile`, `import`, `apply`, `init`, `uninstall`, `adopt`, `doctor` | `--dry-run`, `--yes` |
| Documentation | `help`, `shell-init` | none |

- `--json` prints exactly one JSON document on standard output, and
  nothing else there. `doctor` is a mutating command that also accepts
  `--json`.
- `--dry-run` prints the planned actions and changes nothing. Some dry
  runs still read state through `claude`, `git` or `security` to plan.
- `--yes` answers every confirmation. A command that never asks
  (`unmap`, `set-default`, `profile create`) accepts it and ignores it.
- `help` and `shell-init` print documentation or shell code, not state:
  they have no `--json` (passing it is a usage error, exit 2).

### Confirmations

A mutating command that needs a confirmation:

- with `--yes`, goes on;
- with a TTY on standard input, asks `<question> [y/N]`; anything but `y`
  or `yes` prints `cancelled` (most commands) and exits 0, changing
  nothing;
- without a TTY and without `--yes`, never prompts: it prints the
  question on standard error as `claude-sync: error: <question>`,
  followed by `rerun with --yes`, and exits 3, changing nothing.

Exception: a `script:` recipe of `doctor --fix` needs an answer typed on
a terminal even with `--yes` (see [Tools](tools.md)).

### Errors

Errors go to standard error, prefixed with `claude-sync: error:`. An
unexpected internal error prints
`claude-sync: error: internal error, rerun with CLAUDE_SYNC_DEBUG=1 for
details`, without a traceback, and exits 1. With `CLAUDE_SYNC_DEBUG=1`,
the traceback of any error is printed before the message.

### Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | Success |
| 1 | Runtime error |
| 2 | Usage error (unknown command, bad option, invalid choice) |
| 3 | Confirmation required but not given (rerun with `--yes`) |
| 4 | Drift detected: state differs from what is declared |
| 130 | `init` or `uninstall` interrupted with Ctrl-C (the recovery is printed) |

Each command below lists the codes it can return.

### Environment variables read

| Variable | Read by | Effect |
| -------- | ------- | ------ |
| `XDG_CONFIG_HOME` | every command | Base of the configuration directory (`$XDG_CONFIG_HOME/claude-sync`) |
| `HOME` | every command | Home directory: `~`, `~/.claude`, `~/.claude.json`, `~/.zshrc`, `~/.agents` |
| `CLAUDE_SYNC_OVERRIDE` | `which`, and `status`, `apply`, `import` without `--profile` | Profile that wins over the mappings |
| `CLAUDE_SYNC_DEBUG` | every command | `1` prints tracebacks |
| `PATH` | commands running `claude`, `git`, `pgrep`, `launchctl`, `security`, tools and managers | Where those programs are found |
| `CLAUDE_CONFIG_DIR` | never read; removed or replaced for every `claude` command | |

The shell snippet reads more variables; see
[Shell integration](shell-integration.md).

## version

```text
claude-sync version [-h] [--json]
```

Prints the installed version.

```sh
claude-sync version          # claude-sync 0.1.0
claude-sync version --json   # {"version": "0.1.0", "python": "3.13.1"}
```

Exit codes: 0.

## help

```text
claude-sync help [-h] [--all] [COMMAND]
```

| Option | Meaning |
| ------ | ------- |
| `COMMAND` | Command to describe (default: the top-level help) |
| `--all` | Print the top-level help, then the help of every command, separated by a rule |

```sh
claude-sync help
claude-sync help version     # same as claude-sync version --help
claude-sync help --all
```

Exit codes: 0, 2 (unknown command).

## which

```text
claude-sync which [-h] [--json] [DIR]
```

Prints the profile that applies to `DIR` (default: the current
directory). See [Profiles](profiles.md#which).

| Option | Meaning |
| ------ | ------- |
| `DIR` | Directory to resolve (default `.`); it need not exist |
| `--json` | `{"profile", "source", "match", "config_dir", "initialized"}` |

```sh
claude-sync which
claude-sync which ~/Dev/work/api --json
```

Exit codes: 0, 1 (invalid configuration, invalid `CLAUDE_SYNC_OVERRIDE`),
2.

## list

```text
claude-sync list [-h] [--json]
```

Lists every known profile: the default, every mapped profile and every
directory under the profiles root. `*` marks the default.

```sh
claude-sync list
claude-sync list --json      # {"profiles": [{"name", "default", "initialized", "paths"}]}
```

Exit codes: 0, 1, 2.

## config

```text
claude-sync config [-h] [--json]
```

Shows the configuration file path, whether it exists, the default and
the mappings.

```sh
claude-sync config
claude-sync config --json    # {"file", "exists", "default", "matches": [{"path", "profile"}]}
```

Exit codes: 0, 1, 2.

## map

```text
claude-sync map [-h] [--dry-run] [--yes] DIR PROFILE
```

Maps `DIR` and everything below it to `PROFILE`. See
[Profiles](profiles.md#map).

| Option | Meaning |
| ------ | ------- |
| `DIR` | An existing directory other than `/`; stored with its on-disk spelling, `~` for the home directory |
| `PROFILE` | A profile name (`[a-z0-9][a-z0-9-]*`) |
| `--dry-run` | Print `would map ...` or `would replace ...`, write nothing |
| `--yes` | Replace an existing mapping without asking |

```sh
claude-sync map ~/Dev/work work
claude-sync map ~/dev/work work        # stored as ~/Dev/work on a case-insensitive disk
claude-sync map ~/Dev/work other --yes
claude-sync map ~/Dev/work work --dry-run
```

Exit codes: 0 (also `already mapped`), 1, 2, 3.

## unmap

```text
claude-sync unmap [-h] [--dry-run] [--yes] DIR
```

Removes the mapping whose path is `DIR`.

| Option | Meaning |
| ------ | ------- |
| `DIR` | A mapped directory; it need not exist |
| `--dry-run` | Print `would unmap <path>`, write nothing |

```sh
claude-sync unmap ~/Dev/work
claude-sync unmap ~/Dev/work --dry-run
```

Exit codes: 0, 1 (no mapping for `DIR`), 2.

## set-default

```text
claude-sync set-default [-h] [--dry-run] [--yes] PROFILE
```

Sets the profile used outside every mapped directory; mappings are kept.

```sh
claude-sync set-default perso
claude-sync set-default work --dry-run   # would set default to work
```

Exit codes: 0, 1, 2.

`map`, `unmap` and `set-default` print
`run claude-sync-reload in open shells to apply` on standard error after
a write.

## shell-init

```text
claude-sync shell-init [-h] SHELL
```

Prints the zsh snippet. `SHELL` must be `zsh`. See
[Shell integration](shell-integration.md).

```sh
eval "$(claude-sync shell-init zsh)"     # in ~/.zshrc
claude-sync shell-init zsh               # review it
```

Exit codes: 0, 1 (invalid configuration: nothing on standard output),
2 (another shell, `--json`).

## profile

```text
claude-sync profile [-h] [--org-uuid UUID] [--dry-run] [--yes] ACTION NAME
```

`profile create NAME` creates a profile. See
[Profiles](profiles.md#profile-create).

| Option | Meaning |
| ------ | ------- |
| `ACTION` | `create` (the only action) |
| `NAME` | Profile name |
| `--org-uuid UUID` | Write `[account] org_uuid` to the new manifest |
| `--dry-run` | Print what would be created |

```sh
claude-sync profile create perso
claude-sync profile create work --org-uuid 00000000-0000-0000-0000-000000000000
claude-sync profile create work --dry-run
```

Exit codes: 0, 1 (invalid name or UUID, existing profile, git missing or
failing), 2.

## import

```text
claude-sync import [-h] [--source DIR] [--output FILE] [--profile NAME]
                   [--dry-run] [--yes]
```

Writes a manifest from the installed marketplaces, plugins, skill links
and MCP servers. See [The manifest](manifest.md#import).

| Option | Meaning |
| ------ | ------- |
| `--source DIR` | Read the configuration in `DIR` instead of the target profile (`claude` runs with `CLAUDE_CONFIG_DIR=DIR`) |
| `--output FILE` | Write to `FILE`; `-` writes the manifest alone to standard output |
| `--profile NAME` | Profile to read and write (default: the profile of the current directory) |
| `--dry-run` | Read everything, print `would write <file>`, write nothing |
| `--yes` | Overwrite an existing file without asking |

```sh
claude-sync import --source ~/.claude --output -
claude-sync import --profile work
claude-sync import --profile work --yes
claude-sync import --output manifest.toml --dry-run
```

Exit codes: 0, 1, 2, 3.

## status

```text
claude-sync status [-h] [--profile NAME] [--json]
```

Compares a profile with its manifest. See
[The manifest](manifest.md#status).

| Option | Meaning |
| ------ | ------- |
| `--profile NAME` | Profile to check (default: the profile of the current directory) |
| `--json` | `{"profile", "drift", "differences": [{"kind", "subject", "expected", "actual", "drift"}]}` |

```sh
claude-sync status
claude-sync status --profile work
claude-sync status --profile work --json
```

Exit codes: 0 (no drift), 1, 2, 4 (drift).

## apply

```text
claude-sync apply [-h] [--profile NAME] [--prune] [--dry-run] [--yes]
```

Converges a profile to its manifest. See
[The manifest](manifest.md#apply).

| Option | Meaning |
| ------ | ------- |
| `--profile NAME` | Profile to converge (default: the profile of the current directory) |
| `--prune` | Also remove the plugins, marketplaces, skill links and MCP servers the manifest does not list (after the confirmation) |
| `--dry-run` | Print the `claude` and `git` commands and link changes, secret values masked, run none |
| `--yes` | Answer the confirmation |

```sh
claude-sync apply --profile work
claude-sync apply --profile work --dry-run
claude-sync apply --profile work --prune
claude-sync apply --profile work --prune --yes
```

Exit codes: 0, 1 (tools not ok, refusal, failing command), 2, 3, 4 (a
version, commit or tree still differs afterwards).

## init

```text
claude-sync init [-h] [--dry-run] [--yes]
```

Moves `~/.claude` and `~/.claude.json` into the default profile. See
[Migration](migration.md#init).

| Option | Meaning |
| ------ | ------- |
| `--dry-run` | Check the file conditions only (no `pgrep`, no `claude`) and print the steps |
| `--yes` | Migrate without asking |

```sh
claude-sync init --dry-run
claude-sync init
claude-sync init --yes
```

Exit codes: 0, 1, 2, 3, 4 (plugin rebuild failed or moved upstream; the
profile is migrated), 130 (interrupted).

## uninstall

```text
claude-sync uninstall [-h] [--from-backup [FILE]] [--dry-run] [--yes]
```

Moves the default profile back to `~/.claude`. See
[Migration](migration.md#uninstall).

| Option | Meaning |
| ------ | ------- |
| `--from-backup [FILE]` | Restore a backup instead; without `FILE`, the latest in `backups/` |
| `--dry-run` | Check the conditions (no `pgrep`, no `claude`) and print the steps |
| `--yes` | Proceed without asking |

```sh
claude-sync uninstall --dry-run
claude-sync uninstall
claude-sync uninstall --from-backup --yes
claude-sync uninstall --from-backup ~/.config/claude-sync/backups/20261104T101500Z.tar.gz
```

Exit codes: 0, 1, 2, 3, 4 (plugin rebuild failed or installed other
versions), 130 (interrupted).

## adopt

```text
claude-sync adopt [-h] [--profile NAME] [--dry-run] [--yes]
```

Moves a recreated `~/.claude` (and `~/.claude.json`) into a profile. See
[Migration](migration.md#adopt).

| Option | Meaning |
| ------ | ------- |
| `--profile NAME` | Profile to move into (default: the default profile) |
| `--dry-run` | List the moves, conflicts and removals only (no `pgrep`) |
| `--yes` | Move without asking |

```sh
claude-sync adopt --dry-run
claude-sync adopt
claude-sync adopt --profile work --yes
```

Exit codes: 0 (also nothing to adopt, or only conflicts), 1, 2, 3.

## doctor

```text
claude-sync doctor [-h] [--fix] [--json] [--dry-run] [--yes]
```

Checks the tools every profile requires. See [Tools](tools.md#doctor).

| Option | Meaning |
| ------ | ------- |
| `--fix` | Install or upgrade the missing and too old tools that have a recipe |
| `--json` | `{"tools": [...], "conflicts": [...], "ok": bool}`; with `--fix`, requires `--yes` and prints the progress on standard error |
| `--dry-run` | With `--fix`: print the commands, run none |
| `--yes` | With `--fix`: answer the confirmation (a `script:` recipe still asks on a terminal, or is skipped) |

```sh
claude-sync doctor
claude-sync doctor --json
claude-sync doctor --fix --dry-run
claude-sync doctor --fix
claude-sync doctor --fix --yes
```

Exit codes: 0 (every tool ok, no conflict), 1, 2 (`--fix --json` without
`--yes`), 3, 4 (a tool not ok, or a conflict).

## Shell functions

Defined by the snippet, not by the `claude-sync` program:

| Function | Effect |
| -------- | ------ |
| `claude-sync-use PROFILE` | Export `CLAUDE_SYNC_OVERRIDE=PROFILE` and apply it in this shell; returns 1 on an invalid name |
| `claude-sync-use --auto` | Unset the override and resolve again |
| `claude-sync-reload` | Evaluate a fresh snippet; keeps the current one when `claude-sync` fails |
