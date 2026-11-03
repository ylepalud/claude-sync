## ADDED Requirements

### Requirement: Stray configuration warning
When the default profile directory exists and `~/.claude` exists too, the
snippet SHALL print once per shell, on standard error, that `~/.claude`
exists again and that `claude-sync adopt` moves it into a profile. It SHALL
run no external process for this check.

#### Scenario: Warning once
- **WHEN** the default profile is initialized, `~/.claude` exists, and the shell changes directory twice
- **THEN** the warning is printed exactly once

#### Scenario: Before migration
- **WHEN** the default profile directory does not exist and `~/.claude` exists
- **THEN** no warning is printed
