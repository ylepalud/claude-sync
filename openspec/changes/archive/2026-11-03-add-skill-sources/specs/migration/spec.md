## ADDED Requirements

### Requirement: Skills during migration
When `init` and `uninstall` converge the profile, they SHALL converge
plugins only: `init` records the imported skill tables in `profile.toml` and
leaves every skill link as it is; `uninstall` restores links as recorded and
never clones or relinks skills. The user converges skills later with
`claude-sync apply`.

#### Scenario: Init leaves skill links
- **WHEN** `~/.claude/skills/tdd` links to `~/.agents/skills/tdd` and the user confirms `claude-sync init`
- **THEN** `profile.toml` declares the skill, the link still resolves to `~/.agents/skills/tdd`, and no source is cloned
