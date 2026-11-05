# Shell integration (zsh)

The shell integration applies the profile of the current directory to
every zsh shell, at no cost per directory change, and shows it in the
prompt. Only zsh is supported.

## The snippet

Add this line to `~/.zshrc`, after oh-my-zsh and your theme are loaded:

```sh
eval "$(claude-sync shell-init zsh)"
```

The snippet captures the theme's `RPROMPT` once, when it is first
evaluated, which is why it comes after the theme. `claude-sync init`
appends an equivalent block for you:

```sh
# >>> claude-sync >>>
command -v claude-sync >/dev/null && eval "$(claude-sync shell-init zsh)"
# <<< claude-sync <<<
```

Keep one of the two: an `eval` line you added yourself is not removed by
`init`. Evaluating the snippet twice is harmless (the hook is registered
once), but it is wasted work.

What the snippet is:

- `claude-sync shell-init zsh` prints zsh code that embeds the current
  default profile, the profile name rule, the profiles directory and the
  mappings (paths already normalized, longest first). Resolving the profile
  on a directory change then runs no external process: `claude-sync`
  takes tens of milliseconds to start, too slow for every `cd`.
- It registers `_claude_sync_apply` as a `chpwd` hook with
  `add-zsh-hook`, and runs it once at load.
- Its matcher gives the same answer as `claude-sync which` for every
  directory: it resolves `$PWD` with `${dir:A}` and compares whole path
  components. The test suite checks this parity with a real zsh.
- The functions run with `emulate -L zsh`, `setopt case_match` and, where
  the profile name is checked, `LC_ALL=C`, so your shell options and
  locale do not change the result.

`shell-init` accepts only `zsh`; any other shell name is a usage error
(exit 2), and it has no `--json` form. When the configuration file is
invalid, it prints nothing on standard output, explains on standard error
and exits 1: the `eval` then evaluates nothing and the shell starts
unchanged.

Print the snippet to review it:

```sh
claude-sync shell-init zsh
```

## Environment variables

| Variable | Set by | Meaning |
| -------- | ------ | ------- |
| `CLAUDE_SYNC_PROFILE` | The snippet | The profile resolved for the current directory, always exported |
| `CLAUDE_CONFIG_DIR` | The snippet, when it owns it | The profile directory, exported only when it exists |
| `CLAUDE_SYNC_OVERRIDE` | `claude-sync-use` | A profile that wins over the mappings in this shell |
| `CLAUDE_SYNC_USER_CONFIG_DIR` | The snippet | Your own `CLAUDE_CONFIG_DIR`, remembered at first evaluation |
| `CLAUDE_SYNC_PROMPT` | You | `0` before the `eval` line disables the prompt segment |
| `CLAUDE_SYNC_DEBUG` | You | `1` prints the traceback of an error (any command) |

### CLAUDE_SYNC_PROFILE

Exported on start and after every directory change with the resolved
profile, whether or not that profile is initialized. Scripts and prompts
can read it.

### CLAUDE_CONFIG_DIR and who owns it

On start and after every directory change:

- when the resolved profile directory exists, the snippet exports
  `CLAUDE_CONFIG_DIR` with its absolute path;
- when it does not exist (the profile is not initialized), the snippet
  gives back your own value (`CLAUDE_SYNC_USER_CONFIG_DIR`) when there is
  one, or else unsets a value it owns, and otherwise leaves the variable
  alone.

A value under the profiles directory (`~/.config/claude-sync/profiles/`)
is owned by claude-sync, including one inherited from a parent shell, a
tmux pane or an IDE terminal. A value outside it, present when the
snippet is first evaluated, is yours: the snippet remembers it in the
exported `CLAUDE_SYNC_USER_CONFIG_DIR` (unless that is already set) and
restores it whenever the resolved profile is not initialized.

Examples:

- A child zsh inherits `CLAUDE_CONFIG_DIR=~/.config/claude-sync/profiles/work`
  and changes to a directory whose profile is not initialized: the child
  unsets `CLAUDE_CONFIG_DIR`.
- You exported `CLAUDE_CONFIG_DIR=~/claude-test` before the snippet ran,
  entered an initialized profile, then a directory whose profile is not
  initialized: `CLAUDE_CONFIG_DIR` is `~/claude-test` again.

### CLAUDE_SYNC_OVERRIDE

Set by `claude-sync-use`, read by the snippet and by every claude-sync
command that resolves a profile (`which`, and `status`, `apply`, `import`
without `--profile`). In the snippet, an inherited value that is not a
valid profile name is ignored, with one warning per value per shell:

```text
claude-sync: ignoring invalid CLAUDE_SYNC_OVERRIDE 'Bad!' (expected [a-z0-9][a-z0-9-]*)
```

`claude-sync which` and the other commands do not ignore it: they fail
with `invalid CLAUDE_SYNC_OVERRIDE ...` and exit 1.

### CLAUDE_SYNC_PROMPT

Set `CLAUDE_SYNC_PROMPT=0` before the `eval` line to leave `RPROMPT`
alone. Any other value, or none, shows the segment.

## The prompt segment

The snippet puts `claude:<profile>` at the start of `RPROMPT`, followed by
`?` when the profile is not initialized, then the `RPROMPT` your theme had
when the snippet was first evaluated:

```text
claude:perso
claude:work?
claude:work <your theme's RPROMPT>
```

A theme that rewrites `RPROMPT` in its own `precmd` hook can drop the
segment; set `CLAUDE_SYNC_PROMPT=0` and show `$CLAUDE_SYNC_PROFILE`
yourself in that case.

## claude-sync-use

```sh
claude-sync-use work     # use work in this shell, whatever the directory
claude-sync-use --auto   # back to the mappings
```

`claude-sync-use PROFILE` checks the name (ASCII rule, whatever the
locale), exports `CLAUDE_SYNC_OVERRIDE` and applies it at once:
`CLAUDE_SYNC_PROFILE`, `CLAUDE_CONFIG_DIR` and the prompt follow. An
invalid name prints `claude-sync-use: invalid profile name ...` and
returns 1, changing nothing. The override lasts until
`claude-sync-use --auto`, which unsets it and resolves again, and it is
inherited by child shells.

It is a shell function, not a `claude-sync` command, because a child
process cannot change its parent shell's environment.

## claude-sync-reload

```sh
claude-sync-reload
```

Evaluates a fresh snippet in the current shell, so a change made with
`map`, `unmap` or `set-default` applies without opening a new shell. Those
commands remind you with `run claude-sync-reload in open shells to apply`.
When `claude-sync` fails (not installed, invalid configuration), the
current snippet is kept. The `chpwd` hook stays registered once.

Open shells keep the mappings they were started with until you run it.

## The stray ~/.claude warning

Once the default profile directory exists, `~/.claude` should not. A tool
started without `CLAUDE_CONFIG_DIR` can recreate it. When the default
profile is initialized and `~/.claude` exists, the snippet prints, once
per shell, on standard error:

```text
claude-sync: ~/.claude exists again; claude-sync adopt moves it into a profile
```

The check runs no external process. Before the migration (no default
profile directory yet) there is no warning. See `adopt` in
[Migration](migration.md).

## Apps started outside a shell

The snippet only affects zsh shells and what they start. For the desktop
app and IDEs, `init` installs a LaunchAgent that sets `CLAUDE_CONFIG_DIR`
to the default profile at login (see [Migration](migration.md)). An IDE
terminal that runs zsh with your `~/.zshrc` gets the snippet like any
other shell.
