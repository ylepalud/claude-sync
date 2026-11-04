## Why

A profile depends on command-line tools that live outside Claude Code (a
token-saving proxy, a spec workflow CLI, the GitHub CLI, uv...). Nothing
records which ones a profile needs, at which version, or how to install
them, so a new machine or a new profile breaks in ways that are only seen
when a hook or skill fails. This last roadmap step declares tool
requirements in each profile and checks, and on request installs, them.

## What Changes

- `profile.toml` gains `[[tool]]` tables: `name`, optional minimum
  `version`, optional `check` command, optional `install` recipe
  (`brew:`, `npm:`, `uv:`, `cargo:` or `script:`).
- `claude-sync doctor` merges the requirements of every profile, checks
  each tool, and reports missing, too old and conflicting recipes
  (`--json`, exit 4 when something is wrong).
- `claude-sync doctor --fix` installs missing tools and upgrades too old
  ones with their recipes after one confirmation that shows every command.
- `apply` refuses a profile whose required tools are missing or too old.
- Non-goals: version pinning beyond minimums, uninstalling tools, Linux
  package managers.

## Capabilities

### New Capabilities
- `tool-requirements`: declaring, checking and installing the command-line
  tools profiles need.

### Modified Capabilities
- `plugin-manifest`: the manifest format admits `[[tool]]`.

## Impact

- New modules for tool checks and recipes, a `doctor` command, apply's
  pre-check; fake `brew`, `npm`, `uv`, `cargo` and tool stubs with a guard
  blocking the real managers in tests.
- README: a Tools section; roadmap complete.

Reviewed against b06382a by fable on 2026-11-04
