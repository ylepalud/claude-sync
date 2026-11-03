## Context

Roadmap step 4 (the migration), after step 3 delivered the manifest,
`import`, `status`, `apply` and `profile create`. Whole-project decisions:
`openspec/changes/archive/2026-11-02-add-cli-skeleton-and-leak-guardrails/design.md`;
step-4 decisions recorded in
`openspec/changes/archive/2026-11-02-add-plugin-manifest-and-apply/design.md`.

Facts on the maintainer's machine (2026-11-02): `~/.claude` is 517 MB
(`projects/` 345 MB, `plugins/` 143 MB of caches and marketplace clones,
`plugins/data` empty) and is a git repository with an allowlist
`.gitignore`; `~/.claude.json` is 204 KB; skills are relative symlinks
`../../.agents/skills/<name>`; `settings.json` has an absolute
`/Users/<user>/.claude/hooks/rtk-rewrite.sh` hook; zsh with oh-my-zsh; no
managed settings. Claude Code processes run as `claude` (`pgrep -x claude`).
`launchctl setenv` does not survive a reboot; a LaunchAgent with
`RunAtLoad` running it at login does. The Keychain entry follows the
config dir, so each profile needs `/login`.

## Goals / Non-Goals

**Goals:** a reversible, confirmed migration of `~/.claude` into the default
profile, its reverse, and a way to bring back a recreated `~/.claude`.

**Non-Goals:** skills/MCP/settings management and `[tools]` (step 5),
copying credentials, IDE integration beyond the LaunchAgent.

## Decisions

| Topic | Decision | Rejected |
|---|---|---|
| Backup | gzip tar of `~/.claude` + `~/.claude.json` in `backups/<UTC timestamp>.tar.gz`, mode 600, listed after writing; kept until the user deletes it | No backup; copying the tree |
| Move | `os.rename` (same file system required, checked first) | Copy then delete (slow, 517 MB, half-states) |
| Plugins | Remove caches and lists, rebuild with apply from the imported manifest | Rewriting plugin JSON paths |
| Symlinks | Relative links whose target existed before the move become absolute | Recomputed relative links |
| `settings.json` | Replace the old prefix in string values, recorded for uninstall | List only |
| Markdown | Listed, never rewritten | Automatic rewrite |
| Shell | Marked block in `~/.zshrc` (`# >>> claude-sync >>>` ... `# <<< claude-sync <<<`) | Asking the user to edit |
| GUI | LaunchAgent `io.github.ylepalud.claude-sync.env.plist` running `launchctl setenv CLAUDE_CONFIG_DIR <dir>` at load; loaded with `launchctl bootstrap gui/<uid>`; removed with `bootout` | `setenv` once |
| Uninstall | Move the current profile back, reverse the recorded rewrite, rebuild plugins; `--from-backup` extracts the tar | Always restoring the tar |
| Running Claude | Refuse while `pgrep -x claude` or `pgrep -x Claude` (desktop app) finds a process | Warning only |
| Unrebuildable plugins | Refuse and list them (non-user scope, unmanaged marketplace) | Listing them in the confirmation |
| Step order | Backup, import, renames, record, local rewrites, shell block, LaunchAgent, then plugin rebuild last (network) | Rebuild before the local rewrites |
| Shared CLAUDE.md | No injection or swapping: each profile already has its own; shared content is step 5 | Swapping content in a shared file (global state, the Q2 problem) |
| Stray `~/.claude` | Hook warning once per shell, `adopt` moves non-conflicting entries | Ignore |

### Modules
- `src/claude_sync/system.py`: `running_claude() -> list[tuple[str, int]]`
  (runs `pgrep -x claude` and `pgrep -x Claude`; exit 1 means none),
  `launchctl(*args)` (runs `launchctl`, raises `ClaudeSyncError` with
  stderr), `uid()`, `free_bytes(path)`, `device(path)` (`st_dev` of the
  nearest existing ancestor, resolved). Both external
  programs are found on PATH so tests can stub them.
- `src/claude_sync/migration.py`, pure file-system steps, each a small
  function tested alone: `backup(paths, dest) -> Path`,
  `remove_plugin_caches(profile_dir)`, `absolutize_symlinks(root,
  old_root) -> list[tuple[Path, str]]` (walks with `followlinks=False`, skips `.git`;
  rewrites only relative links whose target, resolved against the pre-move
  location and normalised, lies outside `old_root`; returns each link's
  relative path and original text for the record) and
  `relativize_symlinks(links, root)` for uninstall, which writes the exact
  original text back; `rewrite_settings(profile_dir, old, new) -> list[str]`
  (every occurrence of `old`, and of its `~/`, `$HOME/` and `${HOME}/`
  forms written in the same notation, inside string values, when preceded
  by the start of the value or a character that cannot be part of a path
  and followed by `/`, the end, or anything but a name character, `.` or
  `-`, so `old + ".json"`, `old + "-x"` and `/backup` + `old` are left; returns JSON Pointers; the
  reverse is the same call with `old` and `new` swapped, which also rewrites
  values added under the profile path since migration, the intended result
  after moving back; writes with
  `json.dumps(indent=2, ensure_ascii=False)` plus a trailing newline, the
  format Claude Code itself writes),
  `allow_manifest(profile_dir) -> bool` (uses `git check-ignore`),
  `markdown_mentions(root, old) -> list[Path]`, `zshrc_block_add(path)` /
  `zshrc_block_remove(path)` (edit in place: follow a symlink, keep the
  file mode, add a newline first when the file does not end with one; the
  block is `command -v claude-sync >/dev/null && eval "$(claude-sync
  shell-init zsh)"` between the markers), `launch_agent_plist(dir) -> str`
  (`Label` = `io.github.ylepalud.claude-sync.env`, `ProgramArguments` =
  `/bin/launchctl setenv CLAUDE_CONFIG_DIR <dir>`, `RunAtLoad` true),
  `unrebuildable(observed, listed) -> list[str]` (`listed` is the parsed
  `claude plugin list --json`, every scope), and `Record` saved as
  `.claude-sync-migration.json` (old root, steps done, settings key paths,
  rewritten links, plist path), excluded from the profile repository (it is
  in no allowlist). Backup: `tarfile` gzip with `compresslevel=6`,
  `dereference=False`, member names `.claude/...` and `.claude.json`, one
  progress line per 1000 members on stderr, special files (sockets, FIFOs)
  listed as skipped. `extract_backup(archive, dest)` validates the whole
  archive first (relative names without `..`, top-level names only
  `.claude` and `.claude.json`; only files, directories, symlinks and hard
  links to earlier file members), extracts member by
  member into a fresh staging directory inside `dest` (its parent, `/Users`,
  is not writable), checks before
  each member that the real path of its destination (and of a hard link's
  target) stays inside, and renames into place only when every member
  succeeded. Rejected: the `data` filter (refuses the absolute symlinks a
  real `~/.claude` can hold) and the `tar` filter alone (a symlink followed
  by a hard link and a file escapes it).
- `src/claude_sync/converge.py`: the body of the `apply` command extracted
  as `converge(profile_dir, ctx, prune=False) -> int` and
  `build_manifest(config_dir, account) -> Manifest` from `import`, so `init`
  and `uninstall` reuse them; `apply` and `import` call them unchanged.
- Commands: `init`, `uninstall` (`--from-backup [FILE]`), `adopt`
  (`--profile`), all mutate. `init` and `uninstall` build the full step
  list first, print it, confirm once, then run it; a failing final apply is
  a warning (exit 4, `run claude-sync apply`). LaunchAgent: `launchctl
  bootout gui/<uid>/<label>` first (its failure ignored), then `bootstrap
  gui/<uid> <plist>`; uninstall runs `bootout` then `unsetenv
  CLAUDE_CONFIG_DIR`. Uninstall's rebuild runs the `claude` CLI with
  `CLAUDE_CONFIG_DIR` unset (`~/.claude` is then the default), so it never
  creates `~/.claude/.claude.json`; `ClaudeCli` gains `config_dir=None` for
  that.

### Tests
- Stubs `tests/fake_pgrep.py` and `tests/fake_launchctl.py` (log calls to a
  file under the isolated HOME, `pgrep` answers from an env-controlled list);
  the autouse guard extends to `pgrep` and `launchctl` so a test can never
  run the real ones; fixtures install the stubs.
- The fake claude keeps its state in the config dir; the migration tests
  reset that state after `remove_plugin_caches` (the real CLI would then
  see nothing installed) and assert `install` calls in the stub log.
- A fixture builds a realistic fake `~/.claude` in the isolated HOME: a git
  repo with the allowlist `.gitignore`, `settings.json` with an absolute
  hook path, `skills/x -> ../../.agents/skills/x`, a rule file naming
  `~/.claude/hooks`, `projects/` content, plugin lists matching the fake
  claude state, and `~/.claude.json`.

## Risks / Trade-offs

- Network needed to rebuild plugins → it runs last; a failure leaves a
  migrated, usable profile without some plugins: `claude-sync apply`.
- `pgrep -x claude` can miss a renamed binary → documented; the backup is
  the safety net.
- LaunchAgent behaviour for the desktop app and IDEs is undocumented → kept
  by user choice; uninstall removes it.
