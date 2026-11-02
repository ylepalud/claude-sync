## Why

A profile is only reproducible if what it installs is declared. Today the
plugins and marketplaces of a Claude Code configuration exist only on disk,
with absolute paths that break when the directory moves. This step makes them
declarative (`profile.toml`) and lets claude-sync rebuild them in any profile,
which the migration of `~/.claude` (next step) relies on. It also lets the
user create and lock a work profile before touching the personal one.

## What Changes

- `profile.toml` in each profile: `[[marketplace]]` (name, source, optional
  branch or tag `ref`, recorded `commit`), `[[plugin]]` (id, version,
  enabled), optional `[account] org_uuid`.
- `claude-sync import`: reads the installed state through `claude plugin list
  --json` and `claude plugin marketplace list --json` and writes a manifest;
  `--source DIR` and `--output FILE` work before any profile exists.
- `claude-sync status`: shows the difference between the manifest and the
  profile (including upstream movement and a sign-in to another
  organization), exit 4 on drift, `--json`.
- `claude-sync apply`: converges the profile to its manifest (install
  missing, sync enabled state, re-pin with confirmation, `--prune` to remove),
  never approves marketplace commands on the user's behalf, and writes the
  account guide keys into the profile's `settings.json`.
- `claude-sync profile create NAME [--org-uuid UUID]`: a new profile
  directory with a minimal manifest and its own git repository.
- Non-goals: migrating `~/.claude`, login, `adopt`, `launchctl` (step 4);
  skills, MCP, general settings, `[tools]` (step 5).
- Roadmap: steps 3 and 4 swap; the migration becomes step 4.

## Capabilities

### New Capabilities
- `plugin-manifest`: the manifest format for plugins and marketplaces, and
  the import, status and apply commands.
- `profile-management`: creating a profile and tying it to an
  organization account (login guide and detection).

### Modified Capabilities

None.

## Impact

- New modules for the manifest, the `claude` CLI adapter and the commands;
  a fake `claude` executable for tests and an opt-in end-to-end test.
- No change to `~/.claude`: commands act on a profile directory or on an
  explicit `--source`.
- README: manifest, commands, roadmap order.

Reviewed against 39abea2 by fable on 2026-11-02
