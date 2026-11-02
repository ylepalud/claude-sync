## Purpose

Apply the resolved profile to every zsh shell, at zero cost per directory
change, and keep it visible.

## ADDED Requirements

### Requirement: Shell snippet
`claude-sync shell-init zsh` SHALL print a zsh snippet meant for
`eval "$(claude-sync shell-init zsh)"` in `~/.zshrc`. The snippet SHALL
embed the current mappings and default, so that resolving the profile on a
directory change runs no external process. Evaluating it twice SHALL not
register its hooks twice. Any other shell name SHALL be a usage error. When
the configuration is invalid, the command SHALL print nothing on standard
output, explain on standard error, and exit with code 1, so the shell starts
unchanged.

#### Scenario: Unsupported shell
- **WHEN** the user runs `claude-sync shell-init fish`
- **THEN** the exit code is 2

#### Scenario: Same answer as which
- **WHEN** the snippet is evaluated in zsh and the shell changes to any directory
- **THEN** `CLAUDE_SYNC_PROFILE` equals the output of `claude-sync which` for that directory

### Requirement: Environment
On start and after every directory change, the snippet SHALL export
`CLAUDE_SYNC_PROFILE` with the resolved profile, and SHALL export
`CLAUDE_CONFIG_DIR` with the profile directory only when that directory
exists. A `CLAUDE_CONFIG_DIR` whose value lies under the profiles root is
owned by claude-sync, including one inherited from a parent shell. A value
set by the user (outside the profiles root) when the snippet is first
evaluated SHALL be remembered in the exported `CLAUDE_SYNC_USER_CONFIG_DIR`;
when the resolved profile is not initialized, the snippet SHALL restore that
value, or unset an owned value when there is none.

#### Scenario: Profile not initialized
- **WHEN** the resolved profile directory does not exist
- **THEN** `CLAUDE_SYNC_PROFILE` is set and `CLAUDE_CONFIG_DIR` is not set by the snippet

#### Scenario: Profile initialized
- **WHEN** the shell enters a directory mapped to `work` and `profiles/work/` exists
- **THEN** `CLAUDE_CONFIG_DIR` is the absolute path of `profiles/work`

#### Scenario: User value kept
- **WHEN** the user exported `CLAUDE_CONFIG_DIR` before the snippet ran and the resolved profile is not initialized
- **THEN** the user's value is unchanged

#### Scenario: User value restored
- **WHEN** the user exported `CLAUDE_CONFIG_DIR`, the shell entered an initialized profile, then a directory whose profile is not initialized
- **THEN** `CLAUDE_CONFIG_DIR` is the user's value again

#### Scenario: Nested shell
- **WHEN** a child zsh inherits a `CLAUDE_CONFIG_DIR` under the profiles root and changes to a directory whose profile is not initialized
- **THEN** the child unsets `CLAUDE_CONFIG_DIR`

### Requirement: Prompt segment
The snippet SHALL show `claude:<profile>` at the start of `RPROMPT`, followed
by `?` when the profile is not initialized, keeping any existing `RPROMPT`
content after it. Setting `CLAUDE_SYNC_PROMPT=0` before evaluating the
snippet SHALL disable the segment.

#### Scenario: Segment shown
- **WHEN** the shell is in a directory resolving to `work`, not initialized
- **THEN** `RPROMPT` starts with `claude:work?`

#### Scenario: Segment disabled
- **WHEN** `CLAUDE_SYNC_PROMPT=0` is set before the snippet is evaluated
- **THEN** `RPROMPT` is not modified

### Requirement: Override and reload
The snippet SHALL define `claude-sync-use PROFILE`, which validates the name,
exports `CLAUDE_SYNC_OVERRIDE` (so `claude-sync which` agrees) and applies it
at once, `claude-sync-use --auto`, which unsets the override and resolves
again, and `claude-sync-reload`, which evaluates a fresh snippet so
configuration changes apply without a new shell. An inherited
`CLAUDE_SYNC_OVERRIDE` that is not a valid profile name SHALL be ignored with
a warning.

#### Scenario: Override in one shell
- **WHEN** the user runs `claude-sync-use perso` in a directory mapped to `work`
- **THEN** `CLAUDE_SYNC_PROFILE` is `perso` until `claude-sync-use --auto`

#### Scenario: Reload applies a new mapping
- **WHEN** the configuration gains a mapping after the snippet was evaluated and the user runs `claude-sync-reload`
- **THEN** the new mapping applies in that shell and the chpwd hook is registered once

#### Scenario: Invalid override
- **WHEN** the user runs `claude-sync-use Bad!`
- **THEN** an error is printed, the function returns non-zero, and nothing changes
