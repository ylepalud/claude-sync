## Purpose

Declare the command-line tools a profile needs, check them on the machine,
and install or upgrade them on request.

## ADDED Requirements

### Requirement: Tool tables
The profile manifest SHALL accept zero or more `[[tool]]` tables with a
unique `name` (letters, digits, `.`, `_`, `-`), an optional `version` (a
minimum, dotted numbers), an optional `check` (a command line whose first
word is the tool's name; default `<name> --version`) and an optional
`install` recipe: `brew:<formula>`, `npm:<package>`, `uv:<package>`,
`cargo:<crate>` or `script:<command>` (a single line without control
characters). An
invalid table SHALL make commands that read the manifest fail with exit
code 1, naming the file and the problem.

#### Scenario: Unknown recipe kind
- **WHEN** a tool declares `install = "apt:jq"`
- **THEN** the manifest is invalid and the error names the allowed kinds

### Requirement: Checking a tool
A tool SHALL be present when its check command runs and exits 0. Its
installed version SHALL be the first dotted number (two or more numeric
components) in the check command's standard output. The tool and each
package manager SHALL be resolved to an absolute path on the current `PATH`
and shown by doctor. A tool with a minimum version whose
installed version is lower, or cannot be read, SHALL be too old. The check
command SHALL run without a shell, with a timeout of 10 seconds (a timeout
counts as missing).

#### Scenario: Version parsed
- **WHEN** `rtk --version` prints `rtk 0.20.0` and the requirement is `version = "0.8"`
- **THEN** the tool is present at `0.20.0` and not too old

### Requirement: Doctor
`claude-sync doctor` SHALL read the manifests of every profile, merge the
requirements by tool name (the highest minimum version wins; the check
command and the recipe are each taken from the first profile, in name
order, that declares them; other different recipes are reported as
conflicts), check each tool, and list
for each its status (`ok`, `missing`, `too-old`), installed version,
required version, requiring profiles, recipe and resolved path. It SHALL exit 0 when every
tool is ok and there is no conflict, 4 otherwise, and support `--json`.

#### Scenario: Missing tool
- **WHEN** profile `work` requires `jq` and it is not installed
- **THEN** doctor lists `jq` as missing, required by `work`, and exits with code 4

#### Scenario: Conflicting recipes
- **WHEN** `perso` declares `gh` with `brew:gh` and `work` with `script:install-gh`
- **THEN** doctor reports the conflict and exits with code 4

### Requirement: Fix
`claude-sync doctor --fix` SHALL build, for every missing or too old tool
with a recipe, a command that installs or upgrades it whatever its current
state (`brew install` or `brew upgrade <formula>` depending on `brew list
<formula>`, `npm install -g <package>@latest`, `uv tool install --upgrade
<package>`, `cargo install --force <crate>`, or the script run by
`/bin/sh -c`), with each manager shown by its absolute path; print them all
and ask one confirmation (exit 3 without a TTY and without `--yes`), except
that `script:` recipes SHALL always need an interactive confirmation on a
TTY and are skipped and reported without one, even with `--yes`. It SHALL
run the commands in order, stop at the first failure with exit code 1
showing the command and its error output, then check again and exit 0 when
every tool is ok, 4 otherwise (a tool still too old names the binary found
first on `PATH`). Tools without a recipe SHALL only be reported. When there
is nothing to run, it SHALL ask nothing. `--dry-run` SHALL print the
commands and run nothing. `--json` with `--fix` SHALL require `--yes`.

#### Scenario: Install a missing tool
- **WHEN** `jq` is missing with `install = "brew:jq"` and the user confirms `claude-sync doctor --fix`
- **THEN** `brew install jq` runs and doctor then reports `jq` as ok

#### Scenario: Script with --yes and no TTY
- **WHEN** a missing tool has a `script:` recipe and the user runs `claude-sync doctor --fix --yes` without a TTY
- **THEN** the script does not run, it is reported as skipped, and the exit code is 4

#### Scenario: No recipe
- **WHEN** a missing tool has no `install`
- **THEN** `doctor --fix` runs nothing for it and reports it as still missing

### Requirement: Apply requires the tools
The `claude-sync apply` command (not init or uninstall) SHALL check the
tools its profile declares before any action, and refuse with exit code 1, naming each missing or too old tool and
suggesting `claude-sync doctor --fix`, when one is not ok.

#### Scenario: Apply refuses
- **WHEN** the profile requires `jq` at `1.7` and `jq --version` prints `jq-1.6`
- **THEN** apply exits with code 1, names `jq`, and changes nothing

### Requirement: Import keeps tools
`claude-sync import` SHALL keep the `[[tool]]` tables of the manifest it
replaces, since tools cannot be observed from the profile.

#### Scenario: Tools survive import
- **WHEN** profile.toml declares a tool and the user runs `claude-sync import`
- **THEN** the rewritten profile.toml still declares that tool
