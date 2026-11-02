## Context

Roadmap step 2 of 5; the whole-project decisions live in
`openspec/changes/archive/2026-11-02-add-cli-skeleton-and-leak-guardrails/design.md`.
The CLI frame exists: `Command` registry (`src/claude_sync/registry.py`,
`COMMAND_MODULES`), `Context` with `confirm`/`emit`
(`src/claude_sync/context.py`), `ExitCode`, `ClaudeSyncError`, and the
`cli-conventions` spec every new command follows.

Facts: `claude-sync` starts in about 50 ms (measured), too slow for every
`cd`. The maintainer's zsh is 5.9 with oh-my-zsh (`prompt_subst` on, theme
without `RPROMPT`). GitHub's `ubuntu-latest` runner has no zsh by default.

## Goals / Non-Goals

**Goals:** the resolution rule and its reference implementation, commands to
read and edit the configuration, and a zsh snippet that applies the profile
on every directory change with no external process.

**Non-Goals:** creating profile directories or migrating `~/.claude`
(step 3), `launchctl setenv` for GUI apps and editing `~/.zshrc` (step 3,
with `init`), the Claude Code statusline (step 5), bash or fish.

## Decisions

| Topic | Decision | Rejected |
|---|---|---|
| Per-cd resolution | Matcher compiled into the zsh snippet, Python `which` is the reference, parity test | Calling `claude-sync` per cd (50 ms); a `claude` wrapper resolving at launch only (prompt could not show the profile) |
| Export | `CLAUDE_CONFIG_DIR` only when `profiles/<p>/` exists | Always export (empty profile before step 3) |
| Visibility | `claude:<p>` (`?` if not initialized) prepended to `RPROMPT`, opt-out `CLAUDE_SYNC_PROMPT=0` | Only for non-default profiles; variable only |
| Override | `claude-sync-use` / `claude-sync-reload` shell functions | A `claude-sync use` command (a child process cannot change its parent's environment) |
| Config edits | `map`, `unmap`, `set-default` commands | Hand-editing |
| Profile names | `^[a-z0-9][a-z0-9-]*$`: the decided `[a-z0-9-]+`, tightened so a name never starts with `-` (it would read as an option) | |
| `shell-init` and `--json` | Exempt like `help` (MODIFIED `cli-conventions`) | A JSON form of shell code |

### Modules
- `src/claude_sync/paths.py`: `config_home()` (`$XDG_CONFIG_HOME/claude-sync`
  or `~/.config/claude-sync`), `config_file()`, `profiles_root()`
  (`config_home()/profiles`), `profile_dir(name)`, `normalize(path) -> Path`
  (expand `~`, make absolute against cwd, `Path.resolve(strict=False)`),
  `display(path) -> str` (`~/...` when under `Path.home().resolve()`, so a
  symlinked HOME still abbreviates).
- `src/claude_sync/config.py`: `Config(default: str, matches: tuple[Match,
  ...])`, `Match(path: str, profile: str)` (path as stored, e.g. `~/Dev/work`),
  `load() -> Config` (absent file gives `Config("perso", ())`; `tomllib`;
  rejects unknown keys, missing fields, names not matching
  `^[a-z0-9][a-z0-9-]*$`, raising `ConfigError(ClaudeSyncError)` with the file
  path and the problem), `save(config)` (serializer for this fixed schema,
  values written as TOML basic strings with `\` and `"` escaped; directory
  created 700; temp file in the same directory, `chmod 600`, `os.replace`).
  `PROFILE_NAME` regex exported for reuse.
- `src/claude_sync/resolve.py`: `Resolution(profile, source, match,
  config_dir, initialized)` and `resolve(directory, config, override) ->
  Resolution`. Longest normalized match path equal to the directory or an
  ancestor (`dir == p or p in dir.parents`) wins. `override` comes from
  `CLAUDE_SYNC_OVERRIDE` (validated with `PROFILE_NAME`; invalid is a
  `ClaudeSyncError`).
- `src/claude_sync/zsh.py`: `render(config) -> str` producing the snippet.

### Commands (one module each under `src/claude_sync/commands/`)
- `which [DIR]` (read): text = profile name; JSON = `Resolution` fields,
  `config_dir` absolute, `match` as stored or null.
- `list` (read): JSON `{"profiles": [...]}`; profiles = default, mapped profiles, directory names under
  `profiles_root()` that match `PROFILE_NAME`, sorted; each `{name, default,
  initialized, paths}`. Text: one line per profile, `*` for the default,
  `(not initialized)` suffix, mapped paths.
- `config` (read): `{file, exists, default, matches: [{path, profile}]}`.
- `map DIR PROFILE` (mutate): `DIR` stored with `display(normalize(DIR))`;
  identical mapping is a no-op exit 0; a different profile for the same
  normalized path asks `ctx.confirm`; `--dry-run` prints
  `would map <path> -> <profile>` (or `would replace ...`).
- `unmap DIR` (mutate): removes the mapping whose normalized path equals
  `normalize(DIR)`; none found: `ClaudeSyncError`, exit 1. No confirmation.
  `--dry-run` prints `would unmap <path>`.
- `set-default PROFILE` (mutate): validates the name; no confirmation.
  `--dry-run` prints `would set default to <profile>`.
- After a real write, `map`, `unmap` and `set-default` print on standard
  error `run claude-sync-reload in open shells to apply`.
- `shell-init SHELL` (read, but `--json` is meaningless: kind `doc` like
  `help`): only `zsh`; argparse `choices=["zsh"]` gives exit 2 for others.
  Invalid config: message on stderr, empty stdout, exit 1.

### The zsh snippet
Generated values are quoted for zsh single quotes (`'` becomes `'\''`).
Structure (names are fixed so tests can call them):

```zsh
typeset -g _claude_sync_default='perso'
typeset -g _claude_sync_root='/abs/.config/claude-sync/profiles'
typeset -ga _claude_sync_matches=('/abs/Dev/work/oss' 'perso' '/abs/Dev/work' 'work')  # longest first
_claude_sync_resolve() {
  local dir=${1:-$PWD}; dir=${dir:A}; local i
  for (( i = 1; i < ${#_claude_sync_matches}; i += 2 )); do
    [[ $dir == "$_claude_sync_matches[i]" || $dir == "$_claude_sync_matches[i]"/* ]] \
      && { REPLY=$_claude_sync_matches[i+1]; return }
  done
  REPLY=$_claude_sync_default
}
_claude_sync_apply() { ... }   # override or resolve, export CLAUDE_SYNC_PROFILE,
                               # CLAUDE_CONFIG_DIR if dir exists, prompt segment
claude-sync-use() { ... }      # [[ $1 == --auto ]] or name =~ ^[a-z0-9][a-z0-9-]*$
claude-sync-reload() { eval "$(command claude-sync shell-init zsh)" }
autoload -Uz add-zsh-hook; add-zsh-hook chpwd _claude_sync_apply
_claude_sync_apply
```

- Matches are emitted with `normalize()` applied in Python, sorted by path
  length descending, so zsh compares already-resolved paths and `${dir:A}`
  resolves the current directory the same way.
- The match path is quoted in `[[ == ]]` for clarity (without `GLOB_SUBST`
  it is already literal; quoting keeps it literal if a user enables it).
- `CLAUDE_CONFIG_DIR` ownership: a value under `$_claude_sync_root/` is
  owned (this also covers a value inherited by a child shell, tmux pane or
  IDE terminal). At first evaluation, a set value not under the root is
  saved in the exported `CLAUDE_SYNC_USER_CONFIG_DIR` (only if that is not
  already set). `_claude_sync_apply`: profile initialized: export its
  directory; otherwise export `CLAUDE_SYNC_USER_CONFIG_DIR` when set, else
  unset `CLAUDE_CONFIG_DIR` when it is owned.
- Override: `claude-sync-use` exports `CLAUDE_SYNC_OVERRIDE`; `--auto`
  unsets it. `_claude_sync_apply` ignores, with one warning on stderr, an
  override that does not match the name regex (it may come from the
  environment).
- The `eval` line must come after oh-my-zsh and the theme are sourced in
  `.zshrc`, because the base `RPROMPT` is captured once.
- Prompt: at first evaluation (guard `_claude_sync_loaded`), save `RPROMPT`
  in `_claude_sync_rprompt_base`; `_claude_sync_apply` sets
  `RPROMPT="claude:${profile}${mark}${_claude_sync_rprompt_base:+ $_claude_sync_rprompt_base}"`
  unless `CLAUDE_SYNC_PROMPT=0`. The profile name is safe in a prompt (regex).
- Re-evaluation (reload) replaces the variables and functions;
  `add-zsh-hook` already ignores a duplicate.

### Parity test
`tests/test_zsh_parity.py` (skipped when `zsh` is absent, never skipped in
CI): builds a config with nested mappings, a component-boundary case and a
symlink, writes `render(config)` to a file, then for each directory runs
`zsh -f -c 'source snippet; _claude_sync_resolve DIR; print -r -- $REPLY'`
and compares with `resolve()`. Other zsh behaviour (exports, prompt,
override, user-owned `CLAUDE_CONFIG_DIR`, double evaluation, invalid
override) is tested the same way through `zsh -f -c`.

## Risks / Trade-offs

- The snippet embeds the config at evaluation time → `map` and `unmap` print
  a reminder to run `claude-sync-reload`; open shells keep the old table
  until then.
- A theme that rewrites `RPROMPT` in its own `precmd` would drop the
  segment → acceptable; opt-out exists, and the theme in use does not.
- `Path.resolve` and `${dir:A}` could differ on exotic paths (`..` through a
  symlink) → the parity test covers symlinks; others are not expected.
