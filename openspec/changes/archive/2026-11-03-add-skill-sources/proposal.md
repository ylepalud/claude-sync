## Why

A profile's own skills live in its git repository, but external skill sets
(for example a public collection of engineering skills) are installed today
by a third-party tool as copies in a shared `~/.agents/skills`, linked into
`~/.claude/skills`. Nothing records which skills a profile uses or at which
version, and nothing can rebuild them on another machine. This change makes
external skills declarative, pinned to a commit and per profile.

## What Changes

- `profile.toml` gains `[[skill_source]]` (`name`, `source`, optional
  `ref`, `commit`) and `[[skill]]` (`id` = `<skill>@<source>`, `path` in the
  repository).
- Sources are cloned once per machine under
  `~/.config/claude-sync/sources/<name>/`; each profile links the skills it
  declares into its `skills/` directory with absolute links.
- `import` records the profile's linked external skills, reading the
  third-party lock file `~/.agents/.skill-lock.json` when present.
- `status` reports skill differences; `apply` clones or fetches, checks out
  the recorded commit, creates and repairs links (replacing a link that
  points elsewhere after a confirmation) and, with `--prune`, removes links
  into the sources directory the manifest does not list.
- Non-goals: MCP servers (5b), machine tools (5c), the profile's own skills
  (git), touching `~/.agents`.

## Capabilities

### New Capabilities
- `skill-sources`: declaring, importing, checking and applying external
  skill sources.

### Modified Capabilities
- `plugin-manifest`: the manifest format admits the skill tables; apply
  converges skills too, with one confirmation and git commands in the dry
  run.
- `migration`: init and uninstall converge plugins only and leave skill
  links alone.

## Impact

- New modules for skill sources and their git operations; manifest,
  import, status and apply extended; tests with local git repositories as
  upstreams (no network).
- README: a Skills section.

Reviewed against f09ead0 by fable on 2026-11-03
