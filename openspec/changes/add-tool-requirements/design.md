## Context

Roadmap step 5c, the last one. Builds on the manifest and converge
(`openspec/changes/archive/2026-11-02-add-plugin-manifest-and-apply/design.md`,
and the 5a/5b archives). Facts (2026-11-04, maintainer's machine): `rtk`
0.20.0 in `/usr/local/bin` (installed outside a package manager), `gh` and
`uv` from Homebrew, `openspec` 1.12.0 as a global npm package under nvm,
`git` and `zsh` from macOS, `python3` from pyenv, `claude` from its native
installer. Version outputs vary: `rtk 0.20.0`, `gh version 2.101.0
(date)`, `uv 0.11.7 (Homebrew ...)`, `1.12.0`, `jq-1.6`.

## Goals / Non-Goals

**Goals:** declared tool requirements per profile, a machine-wide check,
installation and upgrade on request, apply refusing a profile whose tools
are not ok.

**Non-Goals:** exact version pinning, uninstalling, Linux managers,
installing claude-sync itself.

## Decisions

| Topic | Decision | Rejected |
|---|---|---|
| Where | `[[tool]]` in each `profile.toml` (versioned with the profile) | Untracked `machine.toml`; a shared file in the perso repo |
| Merge | Highest minimum wins; first profile in name order gives check and recipe; different recipes reported | Last writer wins |
| Recipes | `brew:`, `npm:`, `uv:`, `cargo:` built by claude-sync, `script:` run by `/bin/sh -c`; all shown and confirmed | Free-form only; report only |
| Version | First `\d+(\.\d+)+` in the check output; minimum comparison by integer tuples | Full specifier grammar |
| Check | Argument list from `shlex.split(check)`, no shell, 10 s timeout | Shell execution |
| Upgrade | `--fix` also upgrades too-old tools | Install only |
| Apply | Pre-check of the profile's tools before any action | Warning |

### Modules
- `manifest.py`: `Tool(name, version, check, install)`, validation per
  spec, rendered after MCP servers, sorted by name.
- `tools.py`: `parse_version(text) -> tuple[int, ...] | None`,
  `check(tool) -> ToolStatus(name, status, installed, required)` (runs the
  check command via `subprocess.run` with `timeout=10`),
  `merge(manifests_by_profile) -> (requirements, conflicts)`,
  `install_command(recipe) -> list[str]`, `upgrade_command(recipe) ->
  list[str]`, `all_profiles()` (every profile directory with a
  `profile.toml`).
- `commands/doctor.py`: read command with `--json`, and `--fix` with
  `--dry-run`/`--yes` (the registry gives read commands `--json` only:
  register `doctor` as `mutate` and add `--json` in `configure`, or add a
  kind; say which in the report).
- `converge.py`: before building any plan, check the profile's tools and
  raise `ClaudeSyncError` listing the failures with the `doctor --fix`
  hint.

### Tests
- Executable stubs for tools (`jq`, `rtk`-like) printing a configurable
  version from a JSON file in the isolated HOME, and for `brew`, `npm`,
  `uv`, `cargo` that log their argv and "install" a tool stub; the autouse
  guard blocks the real `brew`, `npm`, `uv` and `cargo` (and `sh` scripts
  run only in tests through the stubs). The real `uv` is used by the test
  runner itself: block it only inside the PATH given to commands under
  test, not for the test process.

## Risks / Trade-offs

- `script:` runs arbitrary shell: shown in full and confirmed, never run
  without `--fix` and the confirmation.
- A tool whose `--version` prints no dotted number (or needs another flag)
  needs `check`; documented.
- Upgrading through a manager can affect other users of the tool on the
  machine; the confirmation lists each command.
