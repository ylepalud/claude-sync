# Tools

A profile can declare the command-line tools it needs: a hook calls
`jq`, a skill expects `gh`, an MCP server runs through `npx`. Tools live
on the machine, not in the profile, so claude-sync only checks them, and
installs or upgrades them when you ask with `claude-sync doctor --fix`.

## Tables

```toml
[[tool]]
name = "jq"
version = "1.7"
install = "brew:jq"

[[tool]]
name = "gh"
check = "gh version"
install = "brew:gh"

[[tool]]
name = "example-cli"
install = "script:curl -fsSL https://example.invalid/install.sh | sh"
```

| Key | Required | Value |
| --- | -------- | ----- |
| `name` | yes | `[A-Za-z0-9][A-Za-z0-9._-]*`, unique in the file |
| `version` | no | A minimum, never a pin: dotted numbers with two or more parts (`1.7`, `0.20.0`) |
| `check` | no | The command line that proves the tool is there; its first word must be `name`. Default: `<name> --version` |
| `install` | no | A recipe (below) |

Recipes:

| Recipe | Value |
| ------ | ----- |
| `brew:<formula>` | A Homebrew formula |
| `npm:<package>` | A global npm package |
| `uv:<package>` | A uv tool |
| `cargo:<crate>` | A cargo crate |
| `script:<command>` | A shell command line, run by `/bin/sh -c` |

- A formula, package or crate matches `[A-Za-z0-9@][A-Za-z0-9@._/+-]*`
  (scoped npm packages such as `@scope/pkg` and tap formulas such as
  `owner/tap/formula` fit).
- A `script:` is a single line without control characters.
- Any other kind (`apt:jq`, for example) is an error that names the
  allowed kinds.
- `check` must parse as a command line (`shlex`), and its first word must
  be the tool's name, so a profile you pull cannot make `doctor` run an
  arbitrary program as its check.

Unknown keys, invalid values and duplicate names make the commands that
read the manifest fail with exit 1, naming the file.

## How a tool is checked

- The check command is split like a shell would (`shlex`), and runs
  without a shell, with standard input from `/dev/null` and a 10 second
  timeout.
- The tool is present when the command exits 0. A timeout, a missing
  binary or another exit code makes it `missing`.
- The installed version is the first dotted number with two or more
  components in its **standard output**: `rtk 0.20.0` gives `0.20.0`,
  `gh version 2.101.0 (date)` gives `2.101.0`, `jq-1.6` gives `1.6`.
- Versions compare as integers, part by part, missing parts counting as
  0: `0.20.0` is newer than `0.8`, `1.7` equals `1.7.0`.
- With a `version`, a lower installed version, or one that cannot be read,
  is `too-old`. Without a `version`, any present tool is `ok`.

Only standard output is read, and there is no shell to redirect: a tool
that prints its version on standard error, or prints no dotted number,
needs a `check` with other arguments that print one (`gh version`), or no
`version`.

Tools are looked up on the `PATH` of the process running claude-sync. A
tool installed through nvm, pyenv or a similar manager is found only
where their `PATH` entries or shims are set up by your shell's startup
files: a shell or script without them reports the tool missing, or finds
another copy.

## doctor

```sh
claude-sync doctor                   # exit 4 when a tool is not ok
claude-sync doctor --json
claude-sync doctor --fix --dry-run   # print the install commands
claude-sync doctor --fix
claude-sync doctor --fix --yes
```

`doctor` reads the `profile.toml` of every directory in `profiles/` that
has one (and a valid profile name), not only the current profile, and
merges the tools by name:

- the highest minimum `version` wins;
- `check` and `install` each come from the first profile, in name order,
  that declares them;
- a different recipe in another profile is a conflict:
  `conflict gh: perso brew:gh; work script:install-gh`.

It lists each tool with its status (`ok`, `missing` or `too-old`), the
installed and required versions, the profiles requiring it, its recipe
and the absolute path of the binary found first on `PATH`:

```text
missing  jq  installed -  required 1.7  by work  recipe brew:jq  path -
ok       gh  installed 2.101.0  required -  by perso, work  recipe brew:gh  path /opt/homebrew/bin/gh
```

With no tool declared anywhere it prints `no tools declared`. It exits 0
when every tool is ok and there is no conflict, 4 otherwise. An invalid
manifest in any profile makes it fail with exit 1.

`--json` prints:

```json
{"tools": [{"name": "jq", "status": "missing", "installed": null,
  "required": "1.7", "profiles": ["work"], "recipe": "brew:jq",
  "path": null}], "conflicts": [], "ok": false}
```

A conflict is `{"name": ..., "recipes": [{"profile": ..., "recipe":
...}]}`.

## doctor --fix

`--fix` builds one command per missing or too old tool that has a recipe.
Each command installs or upgrades the tool whatever its state, so it also
upgrades a tool that is too old:

| Recipe | Command |
| ------ | ------- |
| `brew:<formula>` | `brew install <formula>`, or `brew upgrade <formula>` when `brew list <formula>` succeeds |
| `npm:<package>` | `npm install -g <package>@latest` |
| `uv:<package>` | `uv tool install --upgrade <package>` |
| `cargo:<crate>` | `cargo install --force <crate>` |
| `script:<command>` | `/bin/sh -c <command>` |

- Each manager is found on `PATH` and shown by its absolute path
  (`/opt/homebrew/bin/brew install jq`). A manager that is not there
  stops `doctor` with exit 1 (`brew not found on PATH, needed by
  brew:jq`).
- `brew list <formula>` runs with a 30 second timeout; a timeout or an
  exit code other than 0 or 1 stops `doctor` with exit 1.
- A tool without a recipe is only reported.

Then:

1. `doctor` prints the table, then asks one confirmation listing every
   command (`These commands will run: ... Continue?`). Nothing to run
   asks nothing. `--yes` answers it; without a TTY and without `--yes` it
   exits 3; answering no prints `cancelled` and exits 0.
2. It runs the commands in order, printing `run: <command>` before each.
   The first failing command stops it with exit 1, showing the command
   and its error output.
3. It checks again and prints the table, then `still missing: <name>`
   for each missing tool and, for a tool still too old,
   `still too-old: <name> <version>, found first at <path>` (often an
   older copy that shadows the one just installed). It exits 0 when every
   tool is ok and there is no conflict, 4 otherwise.

`--dry-run` prints `would run: <command>` for each command and runs none
(exit 0). Building the command can still run `brew list`.

### script: recipes

A `script:` recipe runs arbitrary shell, and it may come from a profile
you pulled. It always needs a confirmation typed on a terminal:

- with `--yes`, the managers run without a prompt, then `doctor` asks
  again, on the terminal, for the scripts;
- without a TTY, and with `--json`, scripts are skipped and reported
  (`skipped (needs an interactive confirmation): example-cli`), so the
  tool stays missing and `doctor` exits 4.

### --fix with --json

`--fix --json` requires `--yes` (otherwise
`claude-sync: error: doctor --fix --json requires --yes`, exit 2). It
prints the progress on standard error and the final JSON document on
standard output. `--fix --json --dry-run` needs `--yes` too, and prints
`{"planned": [{"name", "command"}], "skipped": [...]}`.

## apply and import

`apply` checks the tools its own profile declares before any action,
dry run included, and refuses with exit 1 when one is not ok:

```text
claude-sync: error: profile 'work' needs tools that are not ok:
  jq: too-old (installed 1.6, required 1.7)
run `claude-sync doctor --fix` to install or upgrade them
```

Only `apply` checks: `init`, `uninstall` and `status` do not. `import`
cannot see tools, so it keeps the `[[tool]]` tables of the manifest it
replaces.
