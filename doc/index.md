# claude-sync documentation

claude-sync keeps several Claude Code user configurations, called
profiles, strictly isolated on one machine, and switches between them
automatically by directory.

Each profile is its own `CLAUDE_CONFIG_DIR` under
`~/.config/claude-sync/profiles/<name>/`, with its own settings, skills,
plugins, MCP servers, history and login. A declarative `profile.toml` in
each profile records what is installed, at which version, so that a
profile can be checked (`status`) and rebuilt (`apply`) from that file.

## Who it is for

- You use Claude Code with more than one account or context, for example
  a personal one (`perso`) and one for a job (`work`), and want nothing to
  leak from one to the other: not a plugin, not a skill, not an MCP
  server, not a login, not the history.
- You want the right profile to apply by itself when you `cd` into a
  project, and to see which one is active in your prompt.
- You want your plugins, external skills, MCP servers and command-line
  tools written down in a file you can version, compare and replay.

claude-sync targets macOS with zsh. The migration commands (`init`,
`uninstall`, `adopt`) rely on `pgrep` and `launchctl`, and `keychain:`
references on the macOS `security` tool.

## Reading path

1. [Concepts](concepts.md): profiles, `CLAUDE_CONFIG_DIR`, where files
   live, what is isolated and what is not.
2. [Installation](installation.md): install, upgrade and remove the tool.
3. Pick your start:
   - You already use Claude Code and have a `~/.claude`: read
     [Migration](migration.md) and run `claude-sync init`.
   - You start fresh, or add a second profile: read
     [Profiles](profiles.md) and run `claude-sync profile create`.
4. [Shell integration](shell-integration.md): the zsh snippet that sets
   the profile on every directory change.
5. [The manifest](manifest.md): `profile.toml`, `import`, `status` and
   `apply`, then the pages for each part of it:
   [Skills](skills.md), [MCP servers](mcp-servers.md), [Tools](tools.md).
6. [Security](security.md) before you store a secret reference.
7. Keep [CLI reference](cli-reference.md) and
   [Troubleshooting](troubleshooting.md) at hand.

## Pages

| Page | What it covers |
| ---- | -------------- |
| [Concepts](concepts.md) | Profiles, `CLAUDE_CONFIG_DIR`, directory layout, default profile, isolation and its limits |
| [Installation](installation.md) | Requirements, install with uv or `install.sh`, upgrade, removing the tool |
| [Profiles](profiles.md) | `config.toml`, the resolution rule, `which`, `list`, `config`, `map`, `unmap`, `set-default`, `profile create`, the account guide |
| [Shell integration](shell-integration.md) | The zsh snippet, its variables, the prompt segment, `claude-sync-use`, `claude-sync-reload`, the stray `~/.claude` warning |
| [The manifest](manifest.md) | Every table of `profile.toml`, `import`, `status`, `apply`, pinning and drift, marketplaces and plugins |
| [Skills](skills.md) | External skill sources, shared clones, pinning by commit or tree, import from links and the lock file |
| [MCP servers](mcp-servers.md) | `[[mcp]]` tables, `env:`, `keychain:` and `value:` references, import, status, apply |
| [Tools](tools.md) | `[[tool]]` tables, version checks, `doctor` and `doctor --fix` |
| [Migration](migration.md) | `init`, `uninstall`, `uninstall --from-backup`, `adopt`, every step and how to recover |
| [Security](security.md) | Where secrets end up, masking, what is never touched, the leak guard of this repository |
| [CLI reference](cli-reference.md) | Every command with synopsis, options, examples and exit codes, and the shared conventions |
| [Troubleshooting](troubleshooting.md) | Common error messages and what to do about them |
| [Development](development.md) | Repository layout, tests and their guards, OpenSpec workflow, CI, releasing |
| [Test run](test-run.md) | A test run of claude-sync, step by step (maintained as a separate page) |

The README at the root of the repository is the short overview; these
pages are the full reference. `claude-sync help --all` prints the help of
every command, which is the authoritative text for options.
