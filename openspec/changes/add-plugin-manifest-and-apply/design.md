## Context

New roadmap step 3 (steps 3 and 4 swapped on 2026-11-02). Whole-project
decisions: `openspec/changes/archive/2026-11-02-add-cli-skeleton-and-leak-guardrails/design.md`.
Facts: `claude plugin list --json` and `claude plugin marketplace list --json`
give the installed state (plugin `id`, `version`, `scope`, `enabled`;
marketplace `name`, `source` github|directory, `repo` or `path`,
`installLocation`). `claude plugin marketplace add owner/repo#ref` pins a
ref; `claude plugin install <id> --scope user --yes` is non-interactive.
Some marketplace copies are not git clones (check with
`git -C <dir> rev-parse --show-toplevel` equal to `<dir>`, never a parent).
Plugin versions are semver or short shas.

## Decisions

| Topic | Decision | Rejected |
|---|---|---|
| Order | Manifest and apply before migration | Mini-reinstall in init; rewriting plugin JSON paths |
| Import target | `--source` / `--output` before migration; profile file only if the dir exists | Creating profiles/perso now |
| Pinning | Commit ref when the copy is a git repo, else `pinned = false`; versions always checked | Versions only |
| Apply | Converge, confirm re-pin and prune, version mismatch = exit 4 | Add only |
| Profiles | `profile create` + `[account] org_uuid` lock in settings.json | Later |
| Tests | Fake `claude` on PATH; opt-in e2e `CLAUDE_SYNC_E2E=1` | Calling real claude in unit tests |

## Decisions carried to step 4 (migration), settled 2026-11-02

- `/login` once per profile; the Keychain hash is undocumented and the
  published guess matched none of 14 local entries.
- Stray `~/.claude` recreated by tools: one warning per shell from the hook,
  `claude-sync adopt` moves it into a chosen profile (dry-run, confirmation).
- `launchctl setenv CLAUDE_CONFIG_DIR <perso>` kept (user choice) despite
  undocumented GUI behaviour and an IDE on a work folder using perso.
- The migration must handle relative skills symlinks
  (`../../.agents/skills/...`) and the absolute `~/.claude` hook path in
  `settings.json`; Claude sessions must be closed (refuse when running).

## Risks / Trade-offs

- Undocumented CLI JSON shapes may change → the adapter is one module with
  its own tests and fails loudly on unknown shapes.
