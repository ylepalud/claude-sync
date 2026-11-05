## Why

Writing the reference documentation compared every spec with the code and
found eight places where the specs no longer describe what claude-sync
does, plus two behaviours the specs never stated. The specs are the
durable contract; they must match the code.

## What Changes

- Align the specs with the code: MCP fields per transport, init's
  preconditions, step order and settings rewrite rule, the 130 exit code
  on interrupt and quiet exit on a closed pipe, skills apply without a
  pin, tool name rule, leak-guard history locations, `which` with an
  invalid override, and `import --source ~/.claude` running the CLI with
  `CLAUDE_CONFIG_DIR` unset (from the fix in #9).
- Fix init's printed plan, which listed the migration record and the
  `~/.claude.json` rename in the wrong order.

## Capabilities

### New Capabilities

None.

### Modified Capabilities
- `mcp-servers`, `migration`, `cli-conventions`, `skill-sources`,
  `tool-requirements`, `leak-guard`, `profile-resolution`,
  `plugin-manifest`: requirement text aligned with the code.

## Impact

- Specs only, plus the order of init's printed plan and its test.
- Depends on #9 for the `import --source` and closed-pipe behaviour.
