## Purpose

Create profiles and bind a profile to an organization account, so a work
profile cannot be signed in with a personal account.

## ADDED Requirements

### Requirement: Create a profile
`claude-sync profile create NAME` SHALL create the profile directory with
mode 700, a `profile.toml` holding no marketplace and no plugin, and a git
repository in it whose `.gitignore` tracks only `profile.toml`,
`settings.json` and `.gitignore` itself. With `--org-uuid UUID` the manifest
gets `[account] org_uuid`. The name SHALL follow the profile name rule. An
existing directory SHALL make the command fail with exit code 1 and change
nothing. `--dry-run` SHALL print what would be created.

#### Scenario: Create the work profile
- **WHEN** the user runs `claude-sync profile create work --org-uuid 00000000-0000-0000-0000-000000000000`
- **THEN** `profiles/work/profile.toml` holds that org UUID, `profiles/work/.git` exists, and `claude-sync which` in a directory mapped to `work` reports it as initialized

#### Scenario: Existing profile
- **WHEN** `profiles/work/` already exists
- **THEN** `claude-sync profile create work` exits with code 1 and changes nothing

### Requirement: Account lock
When a manifest has `[account] org_uuid`, `apply` SHALL set
`forceLoginMethod` to `claudeai` and `forceLoginOrgUUID` to that UUID in the
profile's `settings.json`, creating the file if needed and keeping every
other key. Without `[account]`, apply SHALL not touch those keys. The UUID
SHALL be validated as a UUID.

#### Scenario: Lock written
- **WHEN** the manifest has `org_uuid` and `settings.json` holds other keys
- **THEN** after apply, `settings.json` has both lock keys and the other keys unchanged
