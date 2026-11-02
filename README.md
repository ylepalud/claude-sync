# claude-sync

Keep several Claude Code user configurations (profiles) strictly isolated on
one machine, and switch between them automatically by directory.

Each profile is a separate `CLAUDE_CONFIG_DIR` under
`~/.config/claude-sync/profiles/<name>/`, with its own settings, skills,
plugins, MCP servers, history and login. A declarative `profile.toml` in each
profile records what is installed, at which version.

Status: under construction. See `openspec/changes/` for the planned work.

## License

MIT
