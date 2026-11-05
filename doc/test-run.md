# claude-sync acceptance test run

A step-by-step acceptance test ("recette") that exercises every part of the
claude-sync CLI end to end, from profiles built from scratch, against the
real Claude Code CLI and real public sources. You run it by hand, in a
terminal, outside any Claude Code session. Count about two hours.

Every section has the same shape:

- **Goal**: what the section proves.
- **Commands**: copy-paste ready, for the sandbox `zsh -f` shell.
- **Expected**: the output or exit code to see.
- **Check**: commands that confirm the result.

Each section also says whether it was **rehearsed**: run by the author of
this document on 2026-11-04 (macOS, Claude Code 2.1.316, claude-sync 0.1.0)
in a sandbox `HOME`, without a login and with Claude sessions running. The
sections marked "not rehearsed" need a login, need every Claude process
quit (`init`, `uninstall`, `adopt`), or touch `launchctl` or the Keychain:
their expected output comes from the specs and the code, so read it with
more care. Known deviations found during the rehearsal are listed in
section 25; the steps that hit them say so.

Exit code legend (every command): 0 success, 1 runtime error, 2 usage
error, 3 confirmation required but not given, 4 drift detected.

## Contents

1. What reaches the real machine
2. One-time preparation (normal environment)
3. Enter the sandbox
4. Version, help and exit codes
5. Configuration: config, map, unmap, set-default
6. Resolution: which and list
7. Profile creation
8. Shell integration
9. Sign-in inside the profiles
10. Plugins: import an existing profile
11. Plugins: converge a profile from a manifest
12. Plugins: ref change, enabled state, prune, upstream moved, errors
13. Skills: import from a skills lock file, apply, pin
14. Skills: conflicts and prune
15. MCP servers: declare and apply
16. MCP servers: Keychain references
17. MCP servers: replace, import a literal, failing add, prune
18. Tools and doctor
19. Migration: build a legacy `~/.claude`
20. Migration: init
21. Migration: adopt
22. Migration: uninstall and round trip
23. Migration: uninstall --from-backup
24. Leak safety sweep
25. Findings of the rehearsal
26. Cleanup
27. Checklist

## 1. What reaches the real machine

Everything happens under `$SANDBOX`, a throwaway directory. A sandbox `HOME`
holds the claude-sync configuration (`~/.config/claude-sync`) and the Claude
Code state (`~/.claude`, `~/.claude.json`, profiles), so the real
`~/.claude`, `~/.claude.json`, `~/.config/claude-sync`, `~/.zshrc` and
`~/.agents` are never read or written. The shell integration runs in a
`zsh -f` subshell, which reads no startup file.

A few things are not sandboxed by `HOME`. Know them before you start:

- **login Keychain**: the items `claude-sync-test-run` (accounts `token`
  and `mcp-secret`), created in section 2. Undo: `security
  delete-generic-password`, section 26.
- **launchd**: init (section 20) writes a LaunchAgent in the sandbox
  `HOME` and loads it into your real GUI session, where it runs
  `launchctl setenv CLAUDE_CONFIG_DIR <sandbox profile>`. Undo:
  `claude-sync uninstall` (section 22) runs `launchctl bootout` and
  `launchctl unsetenv CLAUDE_CONFIG_DIR`; by hand, section 26.
- **network**: clones of public GitHub repositories, sections 10 to 23.
  Claude Code clones marketplaces over SSH with your real `~/.ssh`
  (ssh ignores `HOME`). Nothing to undo: the clones live in `$SANDBOX`.
- **package managers**: `doctor --fix`, section 18. Only `--dry-run` and
  a manager-free plan run by default; the optional real fix installs
  `ruff` with uv into the sandbox `HOME`.
- **your Claude account**: the sandbox reuses it through a long-lived
  token (sections 2 and 9). Undo: delete the Keychain item, close the
  terminal, revoke the token if your account settings offer it.

While the LaunchAgent is loaded (between sections 20 and 22), every GUI app
you start gets `CLAUDE_CONFIG_DIR` pointing into the sandbox. Do not open
GUI apps (the Claude desktop app, an IDE, a new Terminal app instance)
until section 22 ran, or until you ran the manual undo of section 26.
Applications already running are not affected. A logout also clears it,
since the agent was loaded from a path launchd does not scan at login.

The sandbox `HOME` also hides your global git configuration (identity,
proxy settings). If your network needs a proxy, export `HTTPS_PROXY` in
the sandbox shell.

## 2. One-time preparation (normal environment)

Rehearsed: partly (the commands exist; the token was not created and no
Keychain item was written).

**Goal**: install the tools, build claude-sync, check that the real machine
holds no claude-sync launchd state, and store a reusable token for the
current Claude account.

**Commands** (a normal terminal, your real `HOME`, outside Claude Code):

```zsh
# Tools the test run uses.
for t in uv git jq zsh claude security launchctl; do
  print -r -- "$t: $(command -v $t)"
done
claude --version

# Build claude-sync from the clone (creates .venv, nothing global).
export CS_REPO=~/Dev/perso/my-projects/claude-sync
(cd $CS_REPO && uv sync)
$CS_REPO/.venv/bin/claude-sync --version

# The real machine must hold no claude-sync launchd state.
launchctl print gui/$(id -u)/io.github.ylepalud.claude-sync.env
launchctl getenv CLAUDE_CONFIG_DIR
security list-keychains -d user

# The token commands exist.
claude setup-token --help
claude auth --help
claude auth status --help
```

**Expected**: every tool has a path; `claude-sync 0.1.0` (or later);
`launchctl print` says `Could not find service ... in domain for user gui`;
`launchctl getenv` prints an empty line; `security list-keychains`
prints your login keychain. Write down those two last outputs: section 26
compares them.

If `launchctl print` finds the service or `getenv` prints a path, this
machine already runs a real claude-sync migration: the test run would
replace that agent and unset the variable. Stop here, or plan to run
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.github.ylepalud.claude-sync.env.plist`
after section 26 to restore it.

Then create the token and the Keychain items. The token is a secret that
signs in as you: never paste it into a file, a chat, an issue or a
command line. `claude setup-token` prints it once (it needs a Claude
subscription); `security ... -w` with no value prompts for it, so it never
reaches your shell history.

```zsh
claude setup-token
# Copy the token it prints, then paste it at the password prompt:
security add-generic-password -s claude-sync-test-run -a token -w
# Clear the terminal scrollback now (Cmd+K in Terminal).

# A fake test secret for the MCP keychain: references (not a real secret).
security add-generic-password -s claude-sync-test-run -a mcp-secret \
  -w kc-test-value-31
```

**Check**:

```zsh
security find-generic-password -s claude-sync-test-run -a token >/dev/null
echo $?            # 0 (attributes only, the token is not printed)
security find-generic-password -s claude-sync-test-run -a mcp-secret \
  >/dev/null; echo $?   # 0
```

## 3. Enter the sandbox

Rehearsed: yes (without the token).

**Goal**: a `zsh -f` shell whose `HOME` is a fresh directory, with
claude-sync on `PATH` and the token in the environment.

`init`, `uninstall` and `adopt` refuse while any Claude Code CLI
(`pgrep -x claude`) or the desktop app (`pgrep -x Claude`) runs, and a
Claude Code session also leaks its own login into child processes through
`CLAUDE_CODE_*` variables. So use a terminal that is not inside Claude
Code, and check:

```zsh
env | grep -E '^(CLAUDE|ANTHROPIC)' | cut -d= -f1   # expect nothing
```

**Commands** (still in the normal terminal):

```zsh
export CS_REPO=~/Dev/perso/my-projects/claude-sync
export REAL_HOME=$HOME
export SANDBOX=$(cd "$(mktemp -d)" && pwd -P)
export CLAUDE_CODE_OAUTH_TOKEN=$(security find-generic-password \
  -s claude-sync-test-run -a token -w)
print -r -- "sandbox: $SANDBOX, token length: ${#CLAUDE_CODE_OAUTH_TOKEN}"
zsh -f
```

`pwd -P` gives the physical path (`/private/var/...`), so claude-sync
prints `~/...` paths consistently. Then, inside the `zsh -f` shell:

```zsh
setopt interactive_comments
export HOME=$SANDBOX/home
mkdir -p $HOME $SANDBOX/bin && cd ~
path=($SANDBOX/bin $HOME/.local/bin $path)
export DISABLE_AUTOUPDATER=1 PYTHONDONTWRITEBYTECODE=1
unset CLAUDE_CONFIG_DIR XDG_CONFIG_HOME CLAUDE_SYNC_OVERRIDE \
  CLAUDE_SYNC_PROFILE CLAUDE_SYNC_USER_CONFIG_DIR
ln -s $CS_REPO/.venv/bin/claude-sync $SANDBOX/bin/claude-sync

# security(1) cannot see the login keychain under another HOME (it finds
# only the System keychain, exit 44). This shim names the login keychain
# for the lookups claude-sync makes; it changes nothing else.
cat > $SANDBOX/bin/security <<EOF
#!/bin/sh
if [ "\$1" = find-generic-password ]; then
  exec /usr/bin/security "\$@" "$REAL_HOME/Library/Keychains/login.keychain-db"
fi
exec /usr/bin/security "\$@"
EOF
chmod +x $SANDBOX/bin/security

# A test MCP "server": records its arguments and environment, then exits.
cat > $SANDBOX/bin/envdump-mcp <<EOF
#!/bin/sh
{ echo "args: \$*"; env | sort; } > "$SANDBOX/envdump.out"
exit 0
EOF
chmod +x $SANDBOX/bin/envdump-mcp
```

**Expected**: no output.

**Check**:

```zsh
print -r -- $HOME; command -v claude-sync security claude
ls -A ~                      # empty
/usr/bin/security find-generic-password -s claude-sync-test-run \
  -a mcp-secret >/dev/null 2>&1; echo $?   # 44: hidden without the shim
security find-generic-password -s claude-sync-test-run \
  -a mcp-secret >/dev/null; echo $?        # 0: found through the shim
claude auth status --json | jq '{loggedIn, authMethod}'
```

`claude auth status` should report `loggedIn: true` through the token (not
rehearsed: the `authMethod` value is not documented here). If it says
`false`, fix the token before going on: sections 9 and 19 to 23 need it.

## 4. Version, help and exit codes

Rehearsed: yes, all outputs as below.

**Goal**: the conventions every command shares (`cli-conventions`).

**Commands**:

```zsh
claude-sync --version; echo $?
claude-sync version --json; echo $?
claude-sync >/dev/null; echo $?
claude-sync help --all | grep -c '^usage: claude-sync'
diff <(claude-sync help version) <(claude-sync version --help) && echo same
claude-sync does-not-exist; echo $?
claude-sync shell-init zsh --json; echo $?
claude-sync shell-init fish; echo $?
claude-sync version --help | grep -E '^(Examples|Exit codes):'
```

**Expected**:

- `claude-sync 0.1.0`, exit 0.
- `{"version": "0.1.0", "python": "3.x.y"}`, exit 0.
- No command: the top-level help, exit 0.
- `help --all`: 18 usage lines (top level and 17 commands).
- `same`.
- `does-not-exist`: `invalid choice` on stderr, exit 2.
- `shell-init zsh --json`: `unrecognized arguments: --json`, exit 2.
- `shell-init fish`: `invalid choice: 'fish' (choose from zsh)`, exit 2.
- Both `Examples:` and `Exit codes:` lines.

**Check**: `claude-sync version --json | jq -e '.version and .python'`
prints `true`.

## 5. Configuration: config, map, unmap, set-default

Rehearsed: yes.

**Goal**: the configuration file is optional, created on the first write
with safe modes, and edited only through the commands.

**Commands**:

```zsh
cd ~
mkdir -p ~/Dev/work/api ~/Dev/work/oss/lib ~/Dev/workshop ~/Dev/lab
claude-sync config; claude-sync config --json
claude-sync map ~/Dev/missing work --yes; echo $?
claude-sync map / work --yes; echo $?
claude-sync map ~/Dev/work work --dry-run; echo $?; ls ~/.config
claude-sync map ~/Dev/work work </dev/null; echo $?
claude-sync map ~/Dev/work work; echo $?
claude-sync map ~/Dev/work other </dev/null; echo $?
claude-sync map ~/Dev/work/oss perso; echo $?
claude-sync set-default work --dry-run; echo $?
claude-sync set-default perso; echo $?
claude-sync unmap ~/Dev/work/oss --dry-run; echo $?
claude-sync unmap ~/Dev/work/oss; echo $?
claude-sync unmap ~/Dev/work/oss; echo $?
```

**Expected**:

- `config`: `exists: false`, `default: perso`; JSON `"matches": []`.
- `map ~/Dev/missing`: `not an existing directory`, exit 1.
- `map /`: `cannot map the root directory /`, exit 1.
- `--dry-run`: `would map ~/Dev/work -> work`, exit 0, and `ls` says
  `~/.config` does not exist.
- The real `map` (new mapping, no confirmation needed): `run
  claude-sync-reload in open shells to apply`, exit 0.
- Again: `already mapped: ~/Dev/work -> work`, exit 0.
- Replace without `--yes` and without a TTY: `~/Dev/work is already
  mapped to work; replace it with other?` then `rerun with --yes`, exit 3.
- `set-default work --dry-run`: `would set default to work`, exit 0.
- `unmap --dry-run`: `would unmap ~/Dev/work/oss`; the real one exit 0;
  the second `unmap`: `no mapping for ~/Dev/work/oss`, exit 1.

**Check**:

```zsh
stat -f '%Lp %N' ~/.config/claude-sync ~/.config/claude-sync/config.toml
cat ~/.config/claude-sync/config.toml
```

Modes 700 and 600; the file holds `default = "perso"` and one `[[match]]`
with `path = "~/Dev/work"` and `profile = "work"`.

## 6. Resolution: which and list

Rehearsed: yes.

**Goal**: the longest mapped prefix wins, whole path components only,
after `~` expansion, symbolic link resolution and on-disk letter case;
`CLAUDE_SYNC_OVERRIDE` wins; an invalid file fails naming itself.

**Commands**:

```zsh
claude-sync map ~/Dev/work/oss perso
claude-sync which ~/Dev/work/oss/lib          # longest prefix
claude-sync which ~/Dev/work/api
claude-sync which ~/Dev/workshop --json       # component boundary
ln -s ~/Dev/work ~/w
claude-sync which ~/w/api --json              # symbolic link
claude-sync which ~/dev/WORK/api              # wrong case
mkdir -p ~/Dev/perso
claude-sync map ~/dev/PERSO perso --dry-run   # on-disk spelling
claude-sync list; claude-sync list --json
CLAUDE_SYNC_OVERRIDE=perso claude-sync which ~/Dev/work/api --json
CLAUDE_SYNC_OVERRIDE='Bad!' claude-sync which ~/Dev/work/api; echo $?
claude-sync unmap ~/Dev/work/oss

# Invalid files.
C=~/.config/claude-sync/config.toml; cp $C $C.bak
printf 'default = "perso"\n[[match]]\npath = "~/Dev/work"\nprofile = "work"\n[[match]]\npath = "~/Dev/work/"\nprofile = "perso"\n' > $C
claude-sync which; echo $?
claude-sync shell-init zsh | wc -c; echo ${pipestatus[1]}
printf 'default = "perso"\n[[match]]\npath = "~/Dev/work"\nprofile = "Work!"\n' > $C
claude-sync which; echo $?
mv $C.bak $C
```

**Expected**:

- `perso`, `work`.
- workshop: `"profile": "perso", "source": "default", "match": null`.
- `~/w/api`: `"profile": "work", "source": "match", "match":
  "~/Dev/work"`, `config_dir` ending in `claude-sync/profiles/work`,
  `"initialized": false`.
- `~/dev/WORK/api`: `work`.
- `would map ~/Dev/perso -> perso` (stored with the disk's spelling).
- `list`: `* perso (not initialized) ~/Dev/work/oss` and `work (not
  initialized) ~/Dev/work`; JSON with `default`, `initialized` and
  `paths` for each.
- Override: `"source": "override"`; an invalid override: `invalid
  CLAUDE_SYNC_OVERRIDE 'Bad!'`, exit 1.
- Duplicate path: `<file>: match path '~/Dev/work/' duplicates
  '~/Dev/work'`, exit 1; `shell-init` prints 0 bytes and exits 1.
- Bad name: `invalid profile name 'Work!' for match profile`, exit 1.

**Check**: `claude-sync which` prints `perso` again (file restored).

## 7. Profile creation

Rehearsed: yes.

**Goal**: `profile create` makes a private directory, an empty or
`[account]`-only manifest and a git repository that tracks only the
manifest.

**Commands**:

```zsh
claude-sync profile create work --org-uuid not-a-uuid; echo $?
claude-sync profile create Work; echo $?
claude-sync profile create work \
  --org-uuid 00000000-0000-0000-0000-000000000000 --dry-run; echo $?
claude-sync profile create work \
  --org-uuid 00000000-0000-0000-0000-000000000000; echo $?
claude-sync profile create work; echo $?
claude-sync profile create perso; echo $?
export PROFILES=~/.config/claude-sync/profiles
export W=$PROFILES/work P=$PROFILES/perso
```

**Expected**: invalid UUID: `invalid organization UUID`, exit 1; `Work`:
`invalid profile name`, exit 1; dry run: `would create ... (git
repository, profile.toml)` and `would set org_uuid ...`, exit 0, nothing
created; then `created ...`, exit 0; again: `profile 'work' already
exists`, exit 1; `perso` created.

**Check**:

```zsh
stat -f '%Lp %N' $PROFILES $W
cat $W/profile.toml $W/.gitignore
git -C $W status --short
claude-sync which ~/Dev/work/api --json | jq .initialized
claude-sync list
```

Modes 700; `[account]` with `org_uuid`; `.gitignore` is `/*`,
`!/.gitignore`, `!/profile.toml`; git shows only those two untracked
files, no commit; `true`; `list` shows `* perso` and `work ~/Dev/work`
without `(not initialized)`.

## 8. Shell integration

Rehearsed: yes, every expectation below, through `zsh -f -c` scripts.

**Goal**: the snippet sets `CLAUDE_SYNC_PROFILE` and `CLAUDE_CONFIG_DIR` on
every directory change with no external process, shows the prompt
segment, and owns only the `CLAUDE_CONFIG_DIR` values under the profiles
root.

**Commands** (a nested `zsh -f`, so this shell stays clean):

```zsh
mkdir -p ~/Dev/solo && claude-sync map ~/Dev/solo solo
zsh -f
setopt interactive_comments
RPROMPT='%T'
eval "$(claude-sync shell-init zsh)"
eval "$(claude-sync shell-init zsh)"     # twice: hooks registered once
p() { print -r -- "profile=$CLAUDE_SYNC_PROFILE" \
  "cfg=${CLAUDE_CONFIG_DIR-<unset>}" "which=$(claude-sync which)" \
  "RPROMPT=$RPROMPT"; }
print -r -- $chpwd_functions
cd ~; p
cd ~/Dev/work/api; p
cd ~/Dev/workshop; p
cd ~/w/api; p
cd ~/dev/WORK/api; p
cd ~/Dev/solo; p
cd ~/Dev/work; claude-sync-use perso; p
claude-sync which --json | jq -r .source
claude-sync-use 'Bad!'; echo $?
claude-sync-use --auto; p
```

**Expected**:

- `_claude_sync_apply` once in `chpwd_functions`.
- `~`: `profile=perso`, `cfg=` the perso profile directory,
  `RPROMPT=claude:perso %T`.
- `~/Dev/work/api`, `~/w/api` and `~/dev/WORK/api`: `profile=work`,
  `cfg=` `.../profiles/work`, `which=work`, `RPROMPT=claude:work %T`.
- `~/Dev/workshop`: `perso`.
- `~/Dev/solo`: `profile=solo`, `cfg=<unset>`, `RPROMPT=claude:solo? %T`
  (profile not initialized).
- `claude-sync-use perso` in `~/Dev/work`: `profile=perso`, and `which`
  agrees (`override`).
- `Bad!`: `claude-sync-use: invalid profile name 'Bad!'`, exit 1,
  nothing changes.
- `--auto`: back to `work`.

Each line's `profile=` equals its `which=`.

Then, still in that shell:

```zsh
# Nested shell: an inherited value under the profiles root is owned.
cd ~/Dev/work/api
zsh -f -c 'eval "$(claude-sync shell-init zsh)"; cd ~/Dev/solo;
  print -r -- "child: $CLAUDE_SYNC_PROFILE ${CLAUDE_CONFIG_DIR-<unset>}"'

# Reload applies a new mapping in this shell.
cd ~/Dev/lab; print $CLAUDE_SYNC_PROFILE
claude-sync map ~/Dev/lab work
cd ~/Dev/lab; print $CLAUDE_SYNC_PROFILE
claude-sync-reload; print $CLAUDE_SYNC_PROFILE ${#chpwd_functions}
claude-sync unmap ~/Dev/lab; claude-sync-reload
exit
```

**Expected**: `child: solo <unset>`; `perso`, `perso` (no reload yet),
then `work 1`.

```zsh
# A value set by the user is remembered and restored.
CLAUDE_CONFIG_DIR=$HOME/my-claude zsh -f -c '
  eval "$(claude-sync shell-init zsh)"
  cd ~/Dev/work; print -r -- "$CLAUDE_CONFIG_DIR"
  cd ~/Dev/solo; print -r -- "$CLAUDE_CONFIG_DIR $CLAUDE_SYNC_USER_CONFIG_DIR"'
# The prompt segment can be disabled.
zsh -f -c 'RPROMPT=keep; CLAUDE_SYNC_PROMPT=0
  eval "$(claude-sync shell-init zsh)"; print -r -- $RPROMPT'
# An invalid inherited override is ignored, with one warning.
CLAUDE_SYNC_OVERRIDE='Bad!' zsh -f -c 'eval "$(claude-sync shell-init zsh)"
  cd /; cd ~; print -r -- $CLAUDE_SYNC_PROFILE'
# Stray ~/.claude after the default profile exists: one warning.
mkdir ~/.claude
zsh -f -c 'eval "$(claude-sync shell-init zsh)"; cd ~/Dev; cd ~; print ok'
rmdir ~/.claude
```

**Expected**: `.../profiles/work`, then `<sandbox>/home/my-claude` twice;
`keep`; one `claude-sync: ignoring invalid CLAUDE_SYNC_OVERRIDE 'Bad!'`
line then `perso`; exactly one `claude-sync: ~/.claude exists again;
claude-sync adopt moves it into a profile` line, then `ok`.

**Check**: the prompt, live. In an interactive `zsh -f` with the snippet,
`cd ~/Dev/work` and look at the right prompt: `claude:work`.

## 9. Sign-in inside the profiles

Rehearsed: no (needs the token).

**Goal**: the token signs in every sandbox profile without `/login`, and
`status` checks the signed-in organization against `org_uuid`.

**Commands**:

```zsh
for p in perso work; do
  CLAUDE_CONFIG_DIR=$PROFILES/$p claude auth status --json |
    jq -c '{loggedIn, authMethod, orgId}'
done
CLAUDE_CONFIG_DIR=$P claude -p 'Reply with the single word OK'
jq -r '.oauthAccount.organizationUuid // "absent"' $W/.claude.json
claude-sync status --profile work; echo $?
```

**Expected**: `loggedIn: true` in both; `OK`. The `org_uuid` of `work` is
the all-zero UUID, so when the profile's `.claude.json` records
`oauthAccount.organizationUuid` (your real organization), `status`
reports the organization mismatch and exits 4 (spec "Wrong
organization"). With token sign-in Claude Code may not record
`oauthAccount`: then the `jq` prints `absent` and status has nothing to
compare (README, Account). Note which case you saw.

**Check**: put your real `orgId` in `$W/profile.toml` (`[account]`), run
`claude-sync status --profile work`: no organization line. Then put the
all-zero UUID back.

## 10. Plugins: import an existing profile

Rehearsed: yes.

**Goal**: a profile filled through the Claude Code CLI is recorded by
`import`, with the marketplace commit.

Sources: the public marketplace `anthropics/claude-plugins-official` and
its small local plugin `commit-commands` (version 1.0.1 on 2026-11-04).

**Commands**:

```zsh
git ls-remote https://github.com/anthropics/claude-plugins-official HEAD
CLAUDE_CONFIG_DIR=$P claude plugin marketplace add \
  anthropics/claude-plugins-official
CLAUDE_CONFIG_DIR=$P claude plugin install \
  commit-commands@claude-plugins-official --scope user </dev/null
claude-sync import --profile perso --output -; echo $?
claude-sync import --profile perso </dev/null; echo $?
claude-sync import --profile perso --dry-run; echo $?
claude-sync import --profile perso --yes; echo $?
claude-sync status --profile perso; echo $?
claude-sync status --profile perso --json
(cd ~/Dev/workshop && claude-sync status; echo $?)
claude-sync status --profile nope; echo $?
```

**Expected**:

- `ls-remote` prints a commit; the CLI says `Successfully added
  marketplace` and `Successfully installed plugin`.
- `--output -`: a manifest with `[[marketplace]]` `name =
  "claude-plugins-official"`, `source =
  "github:anthropics/claude-plugins-official"`, `commit = "<40 hex>"`,
  and `[[plugin]]` `id = "commit-commands@claude-plugins-official"`,
  `version = "1.0.1"`, `enabled = true`; exit 0.
- Without `--yes` (the file exists, even empty): `profile.toml exists;
  overwrite it?`, `rerun with --yes`, exit 3.
- `--dry-run`: `would write .../profiles/perso/profile.toml`, exit 0.
- `--yes`: `wrote ...`, exit 0.
- `status`: `profile perso: no drift`, exit 0; JSON `{"profile":
  "perso", "drift": false, "differences": []}`.
- From `~/Dev/workshop` (default profile): the same, exit 0.
- `nope`: `profile 'nope' does not exist (...): run claude-sync profile
  create nope`, exit 1.

**Check**:

```zsh
CLAUDE_CONFIG_DIR=$P claude plugin list --json |
  jq -c '.[] | {id, version, scope, enabled}'
git -C $P/plugins/marketplaces/claude-plugins-official rev-parse HEAD
grep commit $P/profile.toml
```

The plugin is at user scope and the two commits are equal.

## 11. Plugins: converge a profile from a manifest

Rehearsed: yes.

**Goal**: a hand-written manifest converges an empty profile; the
`[account]` table writes the login guide keys.

**Commands**:

```zsh
cd ~/Dev/work
cat >> $W/profile.toml <<'EOF'

[[marketplace]]
name = "claude-plugins-official"
source = "github:anthropics/claude-plugins-official"

[[plugin]]
id = "commit-commands@claude-plugins-official"
version = "1.0.1"
enabled = true
EOF
claude-sync status; echo $?
claude-sync apply --dry-run; echo $?
ls $W
claude-sync apply </dev/null; echo $?
claude-sync status; echo $?
```

**Expected**:

- `status` (the profile of `~/Dev/work`): `drift: missing
  claude-plugins-official`, `drift: missing commit-commands@...`,
  `drift: guide account`, `info: unpinned claude-plugins-official`,
  exit 4.
- Dry run: `would run: claude plugin marketplace add
  anthropics/claude-plugins-official`, `would run: claude plugin install
  commit-commands@claude-plugins-official --scope user`, `would write
  forceLoginMethod and forceLoginOrgUUID to ...`, exit 0; no plugin
  directory in `ls`.
- `apply`: no confirmation needed, silent, exit 0.
- `status`: `no drift` with the `info: unpinned` line, exit 0.

**Check**:

```zsh
jq '{forceLoginMethod, forceLoginOrgUUID}' $W/settings.json
CLAUDE_CONFIG_DIR=$W claude plugin list --json | jq -r '.[].id'
```

`"claudeai"` and a one-element list holding the all-zero UUID; the
plugin id.

## 12. Plugins: ref change, enabled state, prune, upstream moved, errors

Rehearsed: yes.

**Goal**: a re-pin and a prune need a confirmation listing what they
destroy; a moved upstream exits 4 with the `import` hint; invalid
manifests fail naming the file.

**Commands** (in `~/Dev/work`):

```zsh
# Ref change: remove and add again, after confirmation.
sed -i '' 's#^source = "github:anthropics/claude-plugins-official"#&\nref = "main"#' \
  $W/profile.toml
claude-sync status; echo $?
claude-sync apply --dry-run; echo $?
claude-sync apply </dev/null; echo $?
claude-sync apply --yes; echo $?
CLAUDE_CONFIG_DIR=$W claude plugin marketplace list --json |
  jq -c '.[] | {name, ref}'

# Enabled state.
sed -i '' 's/^enabled = true/enabled = false/' $W/profile.toml
claude-sync apply --dry-run; claude-sync apply; echo $?
sed -i '' 's/^enabled = false/enabled = true/' $W/profile.toml
claude-sync apply; echo $?

# Prune.
CLAUDE_CONFIG_DIR=$W claude plugin install \
  code-simplifier@claude-plugins-official --scope user </dev/null
claude-sync status; echo $?
claude-sync apply; echo $?; claude-sync status >/dev/null; echo $?
claude-sync apply --prune --dry-run; echo $?
claude-sync apply --prune </dev/null; echo $?
claude-sync apply --prune --yes; echo $?

# Upstream moved (simulated by an older declared version).
cp $W/profile.toml $W/profile.toml.bak
sed -i '' 's/^version = "1.0.1"/version = "0.9.0"/' $W/profile.toml
claude-sync status; echo $?
claude-sync apply; echo $?

# Invalid manifests.
cp $W/profile.toml.bak $W/profile.toml
printf '\n[[plugin]]\nid = "x@market"\nversion = "1.0"\nenabled = true\n' \
  >> $W/profile.toml
claude-sync status; echo $?
cp $W/profile.toml.bak $W/profile.toml
printf '\n[[marketplace]]\nname = "local"\nsource = "path:~/Dev/lab"\nref = "main"\n' \
  >> $W/profile.toml
claude-sync status; echo $?
mv $W/profile.toml.bak $W/profile.toml
claude-sync status; echo $?
```

**Expected**:

- Ref: `drift: ref claude-plugins-official: expected 'main', found
  None`, exit 4. Dry run: `marketplace remove`, `marketplace add
  'anthropics/claude-plugins-official#main'`, `install`. Without
  `--yes`: `These changes need your approval:` listing the remove with
  `(removes a marketplace: uninstalls its plugins, deletes their data)`,
  exit 3, nothing changed. With `--yes`: exit 0, and the marketplace
  list shows `"ref":"main"`.
- Enabled: `would run: claude plugin disable
  commit-commands@claude-plugins-official --scope user`; apply exit 0
  both ways.
- Prune: `drift: unlisted code-simplifier@claude-plugins-official`,
  exit 4; `apply` without `--prune` exits 0 and status still exits 4;
  `--prune --dry-run`: `would run: claude plugin uninstall
  code-simplifier@... --scope user`; without `--yes`: exit 3; with:
  exit 0.
- Upstream moved: status `drift: version commit-commands@...: expected
  '0.9.0', found '1.0.1'`, exit 4; apply prints the same line and
  `accept with: claude-sync import`, exit 4.
- Errors: `plugin 'x@market' uses undeclared marketplace 'market'`,
  exit 1; `a path source cannot have a ref or commit ('local')`, exit 1;
  restored: exit 0.

**Check**: `CLAUDE_CONFIG_DIR=$W claude plugin list --json | jq -r
'.[].id'` lists only `commit-commands@claude-plugins-official`.

## 13. Skills: import from a skills lock file, apply, pin

Rehearsed: yes, with the exact commits below.

**Goal**: skills installed by a third-party skills CLI (links into
`~/.agents/skills`, described by `~/.agents/.skill-lock.json`) are
imported, then apply clones the source once, pins it to the commit that
matches the recorded trees and relinks.

Source: the public repository `anthropics/skills`, skills
`skills/mcp-builder` and `skills/pdf`. Commit `C` below is the parent of
the latest change to `mcp-builder` (2026-10-28), so `mcp-builder` has
another tree at the head of `main` than at `C`, and `pdf` the same: apply
must pick `C`, not the head.

**Commands**:

```zsh
cd ~
git ls-remote https://github.com/anthropics/skills HEAD
mkdir -p $SANDBOX/probe
git clone -q --filter=blob:none https://github.com/anthropics/skills \
  $SANDBOX/probe/skills
export PROBE=$SANDBOX/probe/skills
export C=dbd4588f9e1033efb41dad4bef2f7947c8993d44
git -C $PROBE cat-file -t $C
git -C $PROBE log -3 --format='%h %cs %s' -- skills/mcp-builder
T1=$(git -C $PROBE rev-parse "${C}:skills/mcp-builder")
T2=$(git -C $PROBE rev-parse "${C}:skills/pdf")
print -r -- $T1 $T2 $(git -C $PROBE rev-parse HEAD:skills/mcp-builder)

# What the skills CLI would have installed.
mkdir -p ~/.agents/skills
for s in mcp-builder pdf; do
  git -C $PROBE archive $C skills/$s |
    tar -x -C ~/.agents/skills --strip-components=1
done
jq -n --arg t1 $T1 --arg t2 $T2 '{version: 3, skills: {
  "mcp-builder": {source: "anthropics/skills", sourceType: "github",
    sourceUrl: "https://github.com/anthropics/skills.git",
    skillPath: "skills/mcp-builder/SKILL.md", skillFolderHash: $t1,
    pluginName: "example-skills"},
  "pdf": {source: "anthropics/skills", sourceType: "github",
    sourceUrl: "https://github.com/anthropics/skills.git",
    skillPath: "skills/pdf/SKILL.md", skillFolderHash: $t2,
    pluginName: "document-skills"}}}' > ~/.agents/.skill-lock.json

# The profile's skills: two lock links, one own skill, one stray link.
mkdir -p $P/skills/my-own && print own > $P/skills/my-own/SKILL.md
ln -s ~/.agents/skills/mcp-builder $P/skills/mcp-builder
ln -s ~/.agents/skills/pdf $P/skills/pdf
ln -s /tmp $P/skills/stray

claude-sync import --profile perso --yes; echo $?
sed -n '/skill_source/,$p' $P/profile.toml
claude-sync status --profile perso; echo $?
claude-sync apply --profile perso --dry-run; echo $?
claude-sync apply --profile perso </dev/null; echo $?
claude-sync apply --profile perso --yes; echo $?
claude-sync status --profile perso; echo $?
claude-sync import --profile perso --yes; echo $?
claude-sync status --profile perso; echo $?
```

**Expected**:

- `cat-file`: `commit`; the log shows `ca45fc4 2026-10-28 Update
  mcp-builder skill ...` first; trees `b866bcf...` and `6369f46...`,
  and a head tree for mcp-builder that differs from `b866bcf...`.
- Import: `warning: skipped ~/.config/claude-sync/profiles/perso/
  skills/stray: /private/tmp is not a skill source`, exit 0; the
  manifest has `[[skill_source]]` `name = "example-skills"` (first
  `pluginName` in file order), `source = "github:anthropics/skills"`,
  no `commit`, and two `[[skill]]`: `mcp-builder@example-skills` with
  `path = "skills/mcp-builder"` and `tree = "<T1>"`, `pdf@example-skills`
  with `tree = "<T2>"`. No `my-own` (a real directory).
- Status: `clone-missing example-skills`, two `skill-elsewhere` lines
  (found under `~/.agents/skills`), `info: skill-unpinned`, exit 4.
- Dry run: `would run: git clone https://github.com/anthropics/skills.git
  ~/.config/claude-sync/sources/example-skills`, `would run: git -C ...
  checkout --detach <newest commit matching the recorded trees>`, two
  `would replace` lines, exit 0, and `ls ~/.config/claude-sync` shows no
  `sources`.
- Without `--yes`: the two `replace` lines in `These changes need your
  approval:`, exit 3.
- With `--yes`: exit 0. Status: `no drift` plus `info: skill-unpinned
  example-skills: ... found '<C>'`, exit 0.
- After the second import: `commit = "<C>"` recorded, status `no
  drift`, exit 0.

**Check**:

```zsh
git -C ~/.config/claude-sync/sources/example-skills rev-parse HEAD  # = C
git -C ~/.config/claude-sync/sources/example-skills status -sb | head -1
ls -l $P/skills
ls ~/.agents/skills; jq .version ~/.agents/.skill-lock.json
```

HEAD is `C`, detached (`## HEAD (no branch)`); `mcp-builder` and `pdf`
are absolute links into `sources/example-skills/skills/`; `my-own` and
`stray` untouched; `~/.agents` untouched.

## 14. Skills: conflicts and prune

Rehearsed: yes.

**Goal**: one source name means one clone at one commit on the machine; a
real directory and a dirty clone stop apply before any change; prune
removes only unlisted links into `sources/`.

**Commands**:

```zsh
cd ~/Dev/work
cp $W/profile.toml $W/profile.toml.noskills
cat >> $W/profile.toml <<'EOF'

[[skill_source]]
name = "example-skills"
source = "github:anthropics/skills"
commit = "ca45fc496a3436251f191354091d557da31c15b5"

[[skill]]
id = "pdf@example-skills"
path = "skills/pdf"
EOF
# Two profiles disagree.
claude-sync apply --yes; echo $?
sed -i '' "s/ca45fc496a3436251f191354091d557da31c15b5/$C/" $W/profile.toml

# Real directory in the way.
mkdir -p $W/skills/pdf && print mine > $W/skills/pdf/SKILL.md
claude-sync status; echo $?
claude-sync apply --yes; echo $?
cat $W/skills/pdf/SKILL.md
rm -rf $W/skills/pdf

# Shared clone.
claude-sync apply --yes; echo $?
ls ~/.config/claude-sync/sources; readlink $W/skills/pdf

# Dirty clone.
S=~/.config/claude-sync/sources/example-skills
print '# local edit' >> $S/skills/pdf/SKILL.md
claude-sync status --profile perso; echo $?
cp $P/profile.toml $P/profile.toml.bak; cp $W/profile.toml $W/profile.toml.bak
sed -i '' "s/$C/ca45fc496a3436251f191354091d557da31c15b5/" \
  $P/profile.toml $W/profile.toml
claude-sync apply --profile perso --yes; echo $?
git -C $S rev-parse HEAD
mv $P/profile.toml.bak $P/profile.toml; mv $W/profile.toml.bak $W/profile.toml
git -C $S checkout -- skills/pdf/SKILL.md

# Tree drift.
cp $P/profile.toml $P/profile.toml.bak
sed -i '' "s/^tree = \"$T2\"/tree = \"$(printf '0%.0s' {1..40})\"/" \
  $P/profile.toml
claude-sync status --profile perso; echo $?
mv $P/profile.toml.bak $P/profile.toml

# Prune: drop pdf from perso.
cp $P/profile.toml $P/profile.toml.bak
python3 -I - $P/profile.toml <<'EOF'
import re, sys
path = sys.argv[1]
text = open(path).read()
text = re.sub(r'\n\[\[skill\]\]\nid = "pdf@example-skills"\n[^\[]*', '\n', text)
open(path, 'w').write(text)
EOF
claude-sync status --profile perso; echo $?
claude-sync apply --profile perso --yes; echo $?; ls $P/skills
claude-sync apply --profile perso --prune --dry-run
claude-sync apply --profile perso --prune --yes; echo $?
ls $P/skills; ls ~/.agents/skills
mv $P/profile.toml.bak $P/profile.toml
claude-sync apply --profile perso --yes; claude-sync status --profile perso
```

**Expected**:

- Disagree: `skill source 'example-skills': profile 'work' declares
  github:anthropics/skills at ca45fc4..., profile 'perso' declares
  github:anthropics/skills at dbd4588...; they would share
  ~/.config/claude-sync/sources/example-skills: align them, or rename
  the source in one profile`, exit 1.
- Real directory: status `drift: skill-conflict pdf@example-skills`,
  exit 4; apply `~/.config/claude-sync/profiles/work/skills/pdf is not
  a link: move it away to install pdf@example-skills, or remove the
  skill from the manifest`, exit 1; the file still says `mine`.
- Shared clone: exit 0, one `example-skills` directory, and the link
  points into it.
- Dirty: `drift: clone-dirty example-skills: expected False, found True`,
  exit 4; apply `~/.config/claude-sync/sources/example-skills has local
  changes: commit or discard them, then apply again`, exit 1; HEAD is
  still `C`.
- Tree: `drift: skill-tree pdf@example-skills: expected '000...',
  found '<T2>'`, exit 4.
- Prune: `drift: skill-unlisted pdf`, exit 4; apply without `--prune`
  keeps the link; `would remove ~/.config/.../perso/skills/pdf ->
  ...`; after `--prune --yes`, `pdf` is gone from `$P/skills`, while
  `my-own`, `stray`, the clone and `~/.agents/skills/pdf` remain.
- Restored: `no drift`.

**Check**: `claude-sync status --profile work; echo $?` exits 0 (both
profiles share the clone at `C`).

## 15. MCP servers: declare and apply

Rehearsed: yes.

**Goal**: `env:` stays a placeholder, `value:` is literal, values are
masked in every command shown, and Claude Code expands the placeholders
when it starts the server.

**Commands**:

```zsh
cd ~/Dev/work
cp $W/profile.toml $W/profile.toml.premcp
cat >> $W/profile.toml <<EOF

[[mcp]]
name = "envdump"
transport = "stdio"
command = "$SANDBOX/bin/envdump-mcp"
args = ["--mode", "\${DUMP_MODE:-fast}"]
[mcp.env]
DUMP_PLAIN = "value:not-a-secret"
DUMP_TOKEN = "env:CS_TEST_TOKEN"

[[mcp]]
name = "docs"
transport = "http"
url = "https://docs.example.invalid/mcp"
[mcp.headers]
Authorization = "value:Bearer \${DOCS_TOKEN}"
EOF
claude-sync status; echo $?
claude-sync apply --dry-run; echo $?
claude-sync apply </dev/null; echo $?
claude-sync status; echo $?
```

**Expected**:

- `drift: mcp-missing envdump: expected 'stdio'` and `mcp-missing
  docs`, exit 4.
- Dry run: two `would run: claude mcp add-json ... --scope user` lines,
  with `"env": {"DUMP_PLAIN": "***", "DUMP_TOKEN": "***"}` and
  `"headers": {"Authorization": "***"}`; `command`, `args` and `url`
  shown as they are; exit 0.
- Apply: exit 0 (adding needs no confirmation); status `no drift`,
  exit 0.

**Check**:

```zsh
jq '.mcpServers' $W/.claude.json
CS_TEST_TOKEN=fake-token-123 DUMP_MODE=slow CLAUDE_CONFIG_DIR=$W \
  claude mcp get envdump
grep -E '^(args|DUMP_)' $SANDBOX/envdump.out
```

`.claude.json` holds `"DUMP_TOKEN": "${CS_TEST_TOKEN}"`, `"DUMP_PLAIN":
"not-a-secret"`, the args with `${DUMP_MODE:-fast}` and the header
`"Bearer ${DOCS_TOKEN}"`. `claude mcp get` lists the server (`Failed to
connect` is expected: the script is not a real MCP server). The dump
shows `args: --mode slow`, `DUMP_TOKEN=fake-token-123`: Claude Code
expanded the placeholders.

## 16. MCP servers: Keychain references

Rehearsed: partly. The missing-item refusal was rehearsed; the resolved
value needs the Keychain item of section 2 (not created during the
rehearsal).

**Goal**: `keychain:` references are read from the Keychain, written in
clear only to the profile's `.claude.json`, and a missing item stops
apply before any change.

**Commands**:

```zsh
cp $W/profile.toml $W/profile.toml.mcp1
sed -i '' 's#^DUMP_TOKEN = "env:CS_TEST_TOKEN"#&\nDUMP_MISSING = "keychain:claude-sync-test-run/no-such-account"#' \
  $W/profile.toml
claude-sync status; echo $?
claude-sync apply --yes; echo $?
cp $W/profile.toml.mcp1 $W/profile.toml
sed -i '' 's#^DUMP_TOKEN = "env:CS_TEST_TOKEN"#&\nDUMP_SECRET = "keychain:claude-sync-test-run/mcp-secret"#' \
  $W/profile.toml
claude-sync status 2>&1 | tee $SANDBOX/kc-status.out; echo ${pipestatus[1]}
claude-sync apply --dry-run 2>&1 | tee $SANDBOX/kc-dry.out
claude-sync apply --yes 2>&1 | tee $SANDBOX/kc-apply.out
claude-sync status; echo $?
```

**Expected**:

- Missing item: status `drift: mcp-secret envdump: expected
  'env.DUMP_MISSING', found 'keychain:claude-sync-test-run/no-such-account:
  Keychain item not found'`, exit 4; apply `MCP server 'envdump':
  env.DUMP_MISSING: keychain:claude-sync-test-run/no-such-account:
  Keychain item not found`, exit 1, `.claude.json` unchanged.
- Present item: macOS may show a dialog asking to let `security` use the
  item (allow it; `--yes` does not answer it). Status `mcp-changed
  envdump: ... found 'env.DUMP_SECRET'`, exit 4; the dry run shows
  `"DUMP_SECRET": "***"`; apply replaces the stdio server without
  confirmation; status exit 0.

**Check**:

```zsh
jq -r '.mcpServers.envdump.env.DUMP_SECRET' $W/.claude.json |
  grep -c kc-test-value-31                    # 1: in clear, mode 600 file
stat -f '%Lp' $W/.claude.json                 # 600
grep -c kc-test-value-31 $W/profile.toml $SANDBOX/kc-*.out   # all 0
git -C $W check-ignore .claude.json           # ignored
```

## 17. MCP servers: replace, import a literal, failing add, prune

Rehearsed: yes (the failing add with a `value:` header instead of the
`keychain:` one below).

**Goal**: replacing an http server needs a confirmation (it drops its
OAuth sign-in), a stdio one does not; import turns a literal into an
`env:` reference without writing or printing it; a failing `claude`
command is shown masked; prune removes unlisted servers but never an
unmanaged one.

**Commands**:

```zsh
cp $W/profile.toml.mcp1 $W/profile.toml; claude-sync apply --yes
sed -i '' 's#https://docs.example.invalid/mcp#https://docs.example.invalid/v2/mcp#; s#value:not-a-secret#value:still-not-a-secret#' \
  $W/profile.toml
claude-sync status; echo $?
claude-sync apply </dev/null; echo $?
claude-sync apply --yes; echo $?

# Import a literal.
CLAUDE_CONFIG_DIR=$W claude mcp add-json literal \
  "{\"type\":\"stdio\",\"command\":\"$SANDBOX/bin/envdump-mcp\",\"env\":{\"API_KEY\":\"s3cr3t-test-value-42\"}}" \
  --scope user
claude-sync import --yes 2> $SANDBOX/import.err; echo $?
cat $SANDBOX/import.err
sed -n '/name = "literal"/,/^$/p' $W/profile.toml
claude-sync status 2>&1 | tee $SANDBOX/status.out; echo ${pipestatus[1]}
claude-sync apply --yes; echo $?
jq -c '.mcpServers.literal.env' $W/.claude.json

# A failing add, masked (a read-only profile makes the CLI fail).
cp $W/profile.toml $W/profile.toml.mcp2
cat >> $W/profile.toml <<'EOF'

[[mcp]]
name = "failing"
transport = "stdio"
command = "envdump-mcp"
[mcp.env]
X_TEST = "keychain:claude-sync-test-run/mcp-secret"
EOF
chmod 444 $W/.claude.json; chmod 500 $W
claude-sync apply --yes > $SANDBOX/fail.out 2>&1; echo $?
chmod 700 $W; chmod 600 $W/.claude.json
cat $SANDBOX/fail.out
claude-sync apply --yes; echo $?

# Prune, and an unmanaged server.
cp $W/profile.toml.mcp2 $W/profile.toml
CLAUDE_CONFIG_DIR=$W claude mcp add-json odd \
  '{"type":"stdio","command":"envdump-mcp","timeout":5}' --scope user
claude-sync status; echo $?
claude-sync apply --prune </dev/null; echo $?
claude-sync apply --prune --yes; echo $?
jq -c '.mcpServers | keys' $W/.claude.json
claude-sync import --output - 2>&1 >/dev/null
```

**Expected**:

- `mcp-changed envdump: ... found 'env.DUMP_PLAIN'` and `mcp-changed
  docs: ... found 'url'`, no value printed, exit 4. Without `--yes`:
  only the http server needs approval, `run: claude mcp remove docs -s
  user  (removes an http server: drops its OAuth sign-in)` and its
  masked `add-json`, exit 3, nothing changed. With `--yes`: exit 0.
- Import: stderr `claude-sync: export these variables in the shell
  that starts Claude Code:` then `LITERAL_API_KEY`; the manifest has
  `"API_KEY" = "env:LITERAL_API_KEY"`; `DUMP_PLAIN` keeps its `value:`
  reference (it resolves to the observed value). Status: `drift:
  mcp-changed literal: expected None, found 'env.API_KEY'`, exit 4.
  After apply, `.claude.json` holds `{"API_KEY":"${LITERAL_API_KEY}"}`:
  the literal is gone from disk.
- Failing add: exit 1, `claude-sync: error: \`claude mcp add-json
  failing '{... "env": {"X_TEST": "***"}}' --scope user\` failed: MCP
  server "failing" was not saved to ... (run apply again)`. Then apply
  succeeds, exit 0.
- Prune: `drift: mcp-unlisted failing` and `info: mcp-unmanaged odd:
  ... found 'timeout'`, exit 4; without `--yes`: `run: claude mcp
  remove failing -s user`, exit 3; with: exit 0, keys `docs`,
  `envdump`, `literal`, `odd` (the unmanaged one stays).
- The last import warns `skipped MCP server 'odd': fields claude-sync
  does not manage: timeout` (see also finding F3 in section 25 for the
  variables this `--output -` lists).

**Check**:

```zsh
grep -c -e s3cr3t-test-value-42 -e kc-test-value-31 \
  $W/profile.toml $SANDBOX/import.err $SANDBOX/status.out $SANDBOX/fail.out
```

All counts are 0.

## 18. Tools and doctor

Rehearsed: yes, except the optional real fix.

**Goal**: tool requirements of every profile are merged, checked,
reported, fixed on request, and enforced by apply.

**Commands**:

```zsh
cd ~
cp $P/profile.toml $P/profile.toml.pretools
cp $W/profile.toml $W/profile.toml.pretools
cat >> $P/profile.toml <<'EOF'

[[tool]]
name = "git"
version = "2.0"

[[tool]]
name = "ruff"
install = "uv:ruff"

[[tool]]
name = "cs-test-script-tool"
install = "script:echo installing cs-test-script-tool"
EOF
cat >> $W/profile.toml <<'EOF'

[[tool]]
name = "jq"
version = "99.0"

[[tool]]
name = "cs-test-no-recipe"

[[tool]]
name = "ruff"
install = "brew:ruff"
EOF
command -v ruff; echo $?                 # must be 1: ruff absent
claude-sync doctor; echo $?
claude-sync doctor --json | jq -c '.tools[] | [.name, .status, .installed,
  .required, .profiles, .recipe]'
claude-sync doctor --json | jq -c '.conflicts, .ok'
claude-sync doctor --fix --dry-run; echo $?
claude-sync doctor --fix </dev/null; echo $?
claude-sync doctor --fix --json </dev/null; echo $?
claude-sync apply --profile work --dry-run; echo $?
claude-sync import --profile perso --yes 2>/dev/null
grep -c '^\[\[tool\]\]' $P/profile.toml
printf '\n[[tool]]\nname = "x"\ninstall = "apt:x"\n' >> $W/profile.toml
claude-sync doctor; echo $?
cp $W/profile.toml.pretools $W/profile.toml
```

**Expected**:

- `doctor`: `missing cs-test-no-recipe ... by work recipe -`, `missing
  cs-test-script-tool ... by perso`, `ok git installed 2.x required 2.0
  ... path /usr/bin/git`, `too-old jq installed 1.7.1 required 99.0`,
  `missing ruff ... by perso, work recipe uv:ruff`, and `conflict ruff:
  perso uv:ruff; work brew:ruff`; exit 4.
- JSON: the same statuses, the conflict `{"name":"ruff","recipes":[...]}`
  and `false`.
- `--fix --dry-run`: `would run: /bin/sh -c 'echo installing
  cs-test-script-tool'` and `would run: /opt/homebrew/bin/uv tool
  install --upgrade ruff` (managers by absolute path), exit 0.
- `--fix` without a TTY and without `--yes`: exit 3, nothing run (not
  rehearsed: the rehearsal ran no `--fix` that could reach a manager).
- `--fix --json` without `--yes`: `doctor --fix --json requires --yes`,
  exit 2.
- `apply --profile work`: `profile 'work' needs tools that are not ok:`
  listing `jq: too-old (installed 1.7.1, required 99.0)`,
  `cs-test-no-recipe: missing`, `ruff: missing`, then `run claude-sync
  doctor --fix ...`, exit 1, even with `--dry-run`.
- Import keeps the 3 `[[tool]]` tables.
- `apt:x`: `<file>: invalid install 'apt:x' for 'x' (brew:, npm:, uv:,
  cargo: or script:)`, exit 1.

Then the script recipe without a TTY, with nothing else to run:

```zsh
cp $P/profile.toml $P/profile.toml.tools
python3 -I - $P/profile.toml <<'EOF'
import sys
path = sys.argv[1]
text = open(path).read()
text = text.replace('\n[[tool]]\nname = "ruff"\ninstall = "uv:ruff"\n', '')
open(path, 'w').write(text)
EOF
cp $W/profile.toml.pretools $W/profile.toml
claude-sync doctor --fix --yes </dev/null; echo $?
```

**Expected**: `skipped (needs an interactive confirmation):
cs-test-script-tool`, `still missing: cs-test-script-tool`, exit 4, and
no `installing` line (the script did not run). Run the same command on
the terminal (no `</dev/null`): it asks for the script itself even with
`--yes`; answer no.

Optional real fix (not rehearsed; installs `ruff` with uv into the
sandbox `HOME`, nothing global). First check that uv points into the
sandbox:

```zsh
uv tool dir; uv tool dir --bin     # both under $SANDBOX/home
cp $P/profile.toml.tools $P/profile.toml
cp $W/profile.toml.pretools $W/profile.toml
claude-sync doctor --fix           # answer yes for uv, no for the script
command -v ruff; claude-sync doctor; echo $?
```

**Expected**: `uv tool install --upgrade ruff` runs, `ruff` resolves to
`$SANDBOX/home/.local/bin/ruff` and shows `ok`; doctor still exits 4 for
the script tool.

**Check** (restore for the next sections):

```zsh
cp $P/profile.toml.pretools $P/profile.toml
cp $W/profile.toml.pretools $W/profile.toml
claude-sync doctor; echo $?        # no tools declared, 0
```

## 19. Migration: build a legacy `~/.claude`

Rehearsed: yes, except `claude -p` (needs the token).

**Goal**: a second sandbox `HOME` with a pre-claude-sync configuration
made by the real Claude Code: a plugin, a relative skill link pointing
outside `~/.claude`, one pointing inside, an MCP server holding a
literal, absolute and `~` hook paths in `settings.json`, and a rule
mentioning `~/.claude`.

**Commands** (leave the nested shells; start from the section 3 shell):

```zsh
export HOME=$SANDBOX/home-mig
mkdir -p $HOME && cd ~
unset CLAUDE_CONFIG_DIR CLAUDE_SYNC_PROFILE CLAUDE_SYNC_OVERRIDE
env | grep CLAUDE_CONFIG_DIR               # nothing
claude -p 'Reply with the single word OK'  # creates ~/.claude.json
claude plugin marketplace add anthropics/claude-plugins-official
claude plugin install commit-commands@claude-plugins-official \
  --scope user </dev/null
claude mcp add-json legacy-tool \
  "{\"type\":\"stdio\",\"command\":\"$SANDBOX/bin/envdump-mcp\",\"env\":{\"API_KEY\":\"legacy-s3cr3t-99\"}}" \
  --scope user
mkdir -p ~/shared-skills/hello ~/.claude/skills ~/.claude/my-skills/inner \
  ~/.claude/hooks ~/.claude/rules
printf -- '---\nname: hello\ndescription: Say hello.\n---\nSay hello.\n' \
  > ~/shared-skills/hello/SKILL.md
printf -- '---\nname: inner\ndescription: Inner.\n---\nInner.\n' \
  > ~/.claude/my-skills/inner/SKILL.md
ln -s ../../shared-skills/hello ~/.claude/skills/hello
ln -s ../my-skills/inner ~/.claude/skills/inner
printf '#!/bin/sh\nexit 0\n' > ~/.claude/hooks/check.sh
chmod +x ~/.claude/hooks/check.sh
print 'Hooks live in ~/.claude/hooks.' > ~/.claude/rules/hooks.md
jq --arg abs "$HOME/.claude/hooks/check.sh" '.hooks = {PreToolUse: [
  {matcher: "Bash", hooks: [{type: "command", command: $abs},
  {type: "command", command: "~/.claude/hooks/check.sh --tilde"}]}]}' \
  ~/.claude/settings.json > ~/.claude/settings.new
mv ~/.claude/settings.new ~/.claude/settings.json
ls -a ~/.claude; ls ~/.config
```

**Expected**: `OK`; marketplace and plugin installed; `Added stdio MCP
server legacy-tool to user config`; `~/.claude` has no `.claude.json`
(Claude Code keeps it in `~/.claude.json` when `CLAUDE_CONFIG_DIR` is
unset); `~/.config` does not exist.

Do not run `claude-sync import --source ~/.claude` here. Known bug B1
(section 25): it runs `claude` with `CLAUDE_CONFIG_DIR=~/.claude`, which
creates `~/.claude/.claude.json` (and `~/.claude/backups`), and `init`
then refuses. A fix is on its way; until it lands, the preview of the
legacy manifest is the dry run of `init` in section 20, and the manifest
init writes is checked after the migration.

**Check**:

```zsh
ls -l ~/.claude.json; ls ~/.claude/.claude.json   # the second: No such file
readlink ~/.claude/skills/hello ~/.claude/skills/inner
jq -r '.mcpServers["legacy-tool"].env.API_KEY | length' ~/.claude.json  # 16
```

Snapshot for the round trip (sections 22 and 23):

```zsh
snap() {
  emulate -L zsh; setopt extended_glob null_glob
  cd ~ || return
  print -l -- .claude/**/*~.claude/(plugins|backups)(|/*)(D) \
    .claude.json(N) | LC_ALL=C sort
  local l
  for l in .claude/**/*(@D); do print -r -- "$l -> $(readlink $l)"; done
  jq -S . .claude/settings.json
  jq -S '.mcpServers | map_values(if .env then
    .env |= map_values(length) else . end)' .claude.json
  env -u CLAUDE_CONFIG_DIR claude plugin list --json |
    jq -c '[.[] | {id, version, enabled}]'
}
```

The snapshot lists every file except the plugin caches and Claude Code's
own `backups/`, the links with their text, `settings.json`, the MCP
servers (secret lengths only) and the installed plugins. Take it after
section 20's refusal tests.

## 20. Migration: init

Rehearsed: no. `init` was not run (Claude sessions were running, and it
loads a LaunchAgent). Quit every Claude Code CLI and the desktop app for
sections 20 to 23: `pgrep -x claude; pgrep -x Claude` prints nothing.

**Goal**: the refusals change nothing; a confirmed init moves the
configuration into the default profile `perso` and performs every step.

**Commands** (refusals first):

```zsh
cd ~
claude-sync profile create perso >/dev/null
claude-sync init --dry-run; echo $?        # profile exists
rm -rf ~/.config/claude-sync/profiles/perso
# In another terminal, start any `claude` session, then:
claude-sync init --yes; echo $?            # Claude running
# Quit that session, then:
claude-sync init </dev/null; echo $?       # no TTY, no --yes
ls -a ~ ~/.config/claude-sync
snap > $SANDBOX/before.txt; snap > $SANDBOX/before2.txt
diff $SANDBOX/before.txt $SANDBOX/before2.txt && echo stable
claude-sync init --dry-run; echo $?
```

**Expected**:

- `profile 'perso' already exists (...)`, exit 1.
- `Claude is running (claude <pid>): quit it first`, exit 1.
- No TTY: the 12 planned steps, then `rerun with --yes`, exit 3;
  `~/.claude` and `~/.claude.json` still there, no profile directory
  (only `backups/` may be absent too).
- `stable` (if not, find which file Claude Code rewrites on each run and
  ignore it in the comparisons).
- Dry run: `init would migrate the configuration into the profile
  'perso':` with steps 1 to 12 (backup, read plugins, rename
  `~/.claude`, rename `~/.claude.json`, record, symbolic links,
  `settings.json`, `.gitignore`, `~/.zshrc` block, LaunchAgent, plugin
  caches and apply, Markdown list), then `a real run also checks that
  Claude is not running ...`, exit 0.

Right before the migration, check that nothing created
`~/.claude/.claude.json` (bug B1; init would refuse with `~/.claude/
.claude.json exists and would clash with ~/.claude.json`):

```zsh
[[ -e ~/.claude/.claude.json ]] && print 'STOP: B1 hit' || print clean
pgrep -x claude; pgrep -x Claude           # nothing
```

**Expected**: `clean`, and no process id. If you see `STOP`, something
ran `claude` with `CLAUDE_CONFIG_DIR=~/.claude`: note it in the
checklist, remove the file, and take the snapshots again.

Then the migration (the LaunchAgent is loaded from here on: open no GUI
app until section 22):

```zsh
claude-sync init --yes 2>&1 | tee $SANDBOX/init.out; echo ${pipestatus[1]}
```

**Expected**: `backup written: ~/.config/claude-sync/backups/<UTC
timestamp>.tar.gz`, the export hint for `LEGACY_TOOL_API_KEY`, the plugin
rebuild, `these Markdown files still name ~/.claude; fix them by hand:`
listing `~/.config/claude-sync/profiles/perso/rules/hooks.md`, `migrated
~/.claude into ~/.config/claude-sync/profiles/perso`, and `sign in again
with /login in each profile ...`. Exit 0, or 4 if the marketplace moved
upstream since section 19 (then `accept with: claude-sync import`).

**Check** (each spec point of "Migration"):

```zsh
export PM=~/.config/claude-sync/profiles/perso
ls -ld ~/.claude ~/.claude.json            # both: No such file
ls -A $PM | sort                           # .claude.json, record, toml...
jq . $PM/.claude-sync-migration.json | head -20
B=$(ls ~/.config/claude-sync/backups/*.tar.gz | tail -1)
stat -f '%Lp %N' ~/.config/claude-sync/backups $B   # 700, 600
tar -tzf $B | head -3        # relative: .claude/..., .claude.json
tar -tvzf $B | grep '^l'                   # the two links, stored as links
readlink $PM/skills/hello    # absolute: $HOME/shared-skills/hello
readlink $PM/skills/inner                  # still ../my-skills/inner
ls $PM/skills/hello/SKILL.md               # resolves
jq -r '.hooks.PreToolUse[0].hooks[].command' $PM/settings.json
cat $PM/rules/hooks.md                     # unchanged
grep -c '^# >>> claude-sync >>>' ~/.zshrc  # 1
zsh -i -c 'print -r -- $CLAUDE_SYNC_PROFILE $CLAUDE_CONFIG_DIR'
P_AGENT=~/Library/LaunchAgents/io.github.ylepalud.claude-sync.env.plist
plutil -p $P_AGENT
launchctl print gui/$(id -u)/io.github.ylepalud.claude-sync.env | head -5
launchctl getenv CLAUDE_CONFIG_DIR         # = $PM
CLAUDE_CONFIG_DIR=$PM claude plugin list --json | jq -r '.[].id'
sed -n '/\[\[mcp\]\]/,$p' $PM/profile.toml
jq -r '.mcpServers["legacy-tool"].env.API_KEY' $PM/.claude.json |
  grep -c legacy-s3cr3t-99                 # 1: init leaves servers alone
claude-sync status --profile perso; echo $?
```

Expected: the hook commands are `<HOME>/.config/claude-sync/profiles/
perso/hooks/check.sh` and `~/.config/claude-sync/profiles/perso/hooks/
check.sh --tilde`; the interactive shell prints `perso` and `$PM`; the
plist runs `/bin/launchctl setenv CLAUDE_CONFIG_DIR <PM>` with
`RunAtLoad`; the plugin is installed again; the manifest declares
`legacy-tool` with `env:LEGACY_TOOL_API_KEY` while `.claude.json` still
holds the literal; status reports `mcp-changed legacy-tool` (the
literal, until `apply`) and exits 4. Do not run `apply` here: the round
trip compares the servers as they were.

## 21. Migration: adopt

Rehearsed: no (adopt was not run; the stray-warning part of section 8 was).

**Goal**: entries a tool writes to a recreated `~/.claude` move into the
profile; conflicts stay; `~/.claude` goes once empty.

**Commands**:

```zsh
mkdir -p ~/.claude/skills/new-skill
printf -- '---\nname: new-skill\ndescription: New.\n---\nNew.\n' \
  > ~/.claude/skills/new-skill/SKILL.md
print '{}' > ~/.claude/settings.json
zsh -i -c 'cd /; cd ~; true'               # one stray warning
claude-sync uninstall --dry-run; echo $?   # refuses: ~/.claude exists
claude-sync adopt --dry-run; echo $?
claude-sync adopt </dev/null; echo $?
claude-sync adopt --yes; echo $?
ls -A ~/.claude; ls $PM/skills
rm ~/.claude/settings.json
claude-sync adopt --yes; echo $?
ls -ld ~/.claude
claude-sync adopt; echo $?
```

**Expected**:

- One `claude-sync: ~/.claude exists again; claude-sync adopt moves it
  into a profile` line.
- `uninstall --dry-run`: refuses because `~/.claude` exists, naming
  `claude-sync adopt`, exit 1.
- Dry run: `move ~/.claude/skills/new-skill to
  ~/.config/claude-sync/profiles/perso/skills/new-skill`, `conflict:
  ~/.claude/settings.json stays, ~/.config/.../perso/settings.json
  exists`, `remove the empty directory ~/.claude/skills`, exit 0.
- Without `--yes`: exit 3, nothing moved.
- With `--yes`: exit 0, `~/.claude is kept: merge or remove the
  conflicting entries by hand`; `~/.claude` holds only `settings.json`;
  `new-skill` is in the profile.
- Second adopt: `remove the empty directory ~/.claude`, exit 0;
  `~/.claude` is gone.
- Last: `nothing to adopt: neither ~/.claude nor ~/.claude.json exists`,
  exit 0.

**Check**: `rm -rf $PM/skills/new-skill` (so the round trip compares like
with like).

## 22. Migration: uninstall and round trip

Rehearsed: no.

**Goal**: uninstall reverses init from its record, restores launchd, and
gives back the same files and links.

**Commands**:

```zsh
claude-sync uninstall --dry-run; echo $?
claude-sync uninstall </dev/null; echo $?
claude-sync uninstall --yes 2>&1 | tee $SANDBOX/uninstall.out
echo ${pipestatus[1]}
snap > $SANDBOX/after.txt
diff $SANDBOX/before.txt $SANDBOX/after.txt && echo identical
```

**Expected**: the dry run lists the steps (unload and delete the
LaunchAgent then `launchctl unsetenv CLAUDE_CONFIG_DIR`, remove the
`~/.zshrc` block, settings and links back, renames, delete the record,
rebuild the plugin caches) and `other profiles and the backups stay in
place`, exit 0; without `--yes`: exit 3; with: `moved
~/.config/claude-sync/profiles/perso back to ~/.claude`, exit 0 (4 if the
rebuild drifted). `identical`.

**Check**:

```zsh
launchctl print gui/$(id -u)/io.github.ylepalud.claude-sync.env 2>&1 |
  head -2                                  # Could not find service
launchctl getenv CLAUDE_CONFIG_DIR         # empty line
ls ~/Library/LaunchAgents                  # no claude-sync plist
grep -c 'claude-sync' ~/.zshrc             # 0
ls -a ~/.claude | grep -E 'profile.toml|claude-sync-migration'  # nothing
readlink ~/.claude/skills/hello            # ../../shared-skills/hello
ls ~/.config/claude-sync/profiles          # empty (perso moved back)
ls ~/.config/claude-sync/backups           # the backup is kept
```

## 23. Migration: uninstall --from-backup

Rehearsed: no.

**Goal**: the backup restores the pre-init state, setting aside (never
deleting) what is in place.

**Commands**:

```zsh
claude-sync uninstall --from-backup --dry-run; echo $?
claude-sync uninstall --from-backup </dev/null; echo $?
claude-sync uninstall --from-backup --yes; echo $?
ls -d ~/.claude* ~/.config/claude-sync/profiles/perso* 2>/dev/null
snap > $SANDBOX/restored.txt
diff $SANDBOX/before.txt $SANDBOX/restored.txt && echo identical
```

**Expected**: the dry run: `uninstall would restore a backup:` with
`unload and delete ...plist, then run launchctl unsetenv
CLAUDE_CONFIG_DIR`, `rename ~/.claude to ~/.claude.failed-<UTC
timestamp>`, the same for `~/.claude.json`, and `extract <backup> into
~`, exit 0. Without `--yes`: exit 3. With: `restored ~/.claude and
~/.claude.json from ...`, exit 0. `ls` shows `~/.claude`,
`~/.claude.json` and their `.failed-<timestamp>` copies. `identical`.

**Check**: `launchctl getenv CLAUDE_CONFIG_DIR` prints an empty line.

## 24. Leak safety sweep

Rehearsed: yes for the rehearsed sections: no test secret in any
manifest or output; the only file holding one was the legacy
`~/.claude.json`, which is expected (its literal stays until `apply`).

**Goal**: no test secret reached a manifest, an output file or a git
repository, and the token reached no file.

**Commands**:

```zsh
grep -rl --include=profile.toml --include='*.out' --include='*.err' \
  --include='*.txt' -e s3cr3t-test-value-42 -e kc-test-value-31 \
  -e legacy-s3cr3t-99 $SANDBOX
[[ -n $CLAUDE_CODE_OAUTH_TOKEN ]] &&
  grep -rlF -f <(print -r -- $CLAUDE_CODE_OAUTH_TOKEN) $SANDBOX
for d in $SANDBOX/home/.config/claude-sync/profiles/*(/); do
  git -C $d status --short
done
```

**Expected**: both `grep` print nothing (the token is passed through a
file descriptor, never as an argument). Each profile repository shows
only `?? .gitignore` and `?? profile.toml`.

**Check**: `grep -c legacy-s3cr3t-99 $SANDBOX/home-mig/.claude.json`
prints 1: the literal stays in Claude Code's own state file until an
`apply` converges the server, as the README says.

## 25. Findings of the rehearsal

- **B1, bug, fix pending** (sections 19 and 20): `claude-sync import
  --source ~/.claude` creates `~/.claude/.claude.json` and
  `~/.claude/backups`. It runs the `claude` CLI with
  `CLAUDE_CONFIG_DIR=~/.claude` (`converge.build_manifest` defaults to
  `ClaudeCli(config_dir)`), and any `claude plugin` command writes those
  in its config directory. This breaks the spec scenario "Import before
  migration" (no file created) and makes the next `init` refuse. `init`
  itself uses `ClaudeCli(None)` and is not affected. This test run never
  runs `import --source` on the sandbox `~/.claude` and checks the file
  is absent right before `init`. Once the fix lands, add the step back
  in section 19 and expect `~/.claude/.claude.json` to stay absent.
- **B2, minor bug**: when the reader of standard output closes early
  (`claude-sync help --all | python3 -c 'import sys;
  sys.stdin.close()'`), Python prints `Exception ignored while flushing
  sys.stdout: BrokenPipeError` and the exit code is 120, outside the
  documented 0 to 4.
- **F3, observation**: `import --output -` reads no previous manifest, so
  its preview differs from what `import` writes into `profile.toml`: a
  `value:` or `keychain:` reference shows as a new `env:` one and is
  listed among the variables to export, and `[account]` is absent.
- **F4, observation**: under a `HOME` other than the real one,
  `security find-generic-password` sees only the System keychain, so
  `keychain:` references fail with "Keychain item not found". This test
  run works around it with a `security` shim (section 3).
- **F5, observation**: `apply --dry-run` says `would write
  forceLoginMethod and forceLoginOrgUUID to <profile directory>`, not
  `<profile directory>/settings.json`; a successful `apply` prints
  nothing.

## 26. Cleanup

**Commands** (leave every sandbox shell with `exit` first, then in the
normal terminal, real `HOME`):

```zsh
# launchd: only if section 22 or 23 did not run to the end.
launchctl print gui/$(id -u)/io.github.ylepalud.claude-sync.env \
  >/dev/null 2>&1 && launchctl bootout \
  gui/$(id -u)/io.github.ylepalud.claude-sync.env
[[ -n $(launchctl getenv CLAUDE_CONFIG_DIR) ]] &&
  launchctl unsetenv CLAUDE_CONFIG_DIR   # only if section 2 showed it empty

# Keychain items.
security delete-generic-password -s claude-sync-test-run -a token
security delete-generic-password -s claude-sync-test-run -a mcp-secret

# The token in this terminal, and the sandbox.
unset CLAUDE_CODE_OAUTH_TOKEN
rm -rf $SANDBOX
```

Then close this terminal window (its environment held the token). If your
Claude account settings let you revoke long-lived tokens, revoke the one
`claude setup-token` created.

**Check**:

```zsh
launchctl print gui/$(id -u)/io.github.ylepalud.claude-sync.env 2>&1 |
  head -1                                  # Could not find service
launchctl getenv CLAUDE_CONFIG_DIR         # as in section 2
security find-generic-password -s claude-sync-test-run >/dev/null 2>&1
echo $?                                    # 44
security list-keychains -d user            # as in section 2
ls -ld ~/.claude ~/.claude.json ~/.config/claude-sync  # as before
grep -c claude-sync ~/.zshrc               # as before
```

The repository keeps only its `.venv` (from `uv sync`).

## 27. Checklist

Tick each line when its section matched the expected result. Note any
difference next to it.

```text
[ ]  2  tools present, no real launchd state, token and items stored
[ ]  3  sandbox shell, shim works, claude auth status: loggedIn
[ ]  4  version, help, --json, exit codes 0/2
[ ]  5  config absent, map/unmap/set-default, modes 700/600, exit 3
[ ]  6  longest prefix, boundary, symlink, case, override, invalid file
[ ]  7  profile create: modes, manifest, git, refusals
[ ]  8  shell: env, prompt, use, reload, nested, user value, warnings
[ ]  9  token sign-in in both profiles; organization check
[ ] 10  import of an existing profile, commit recorded, status 0
[ ] 11  apply from a manifest, account keys, status 0
[ ] 12  re-pin (3, then --yes), enable, prune, upstream moved, errors
[ ] 13  skills: lock import, status 4, apply 3 then --yes, pin to C
[ ] 14  skills: disagree, real dir, shared clone, dirty, tree, prune
[ ] 15  MCP: env:/value:, masked dry run, expansion by Claude Code
[ ] 16  MCP: keychain missing (1), present (clear only in .claude.json)
[ ] 17  MCP: http confirm, literal import, failing add masked, prune
[ ] 18  doctor: ok/missing/too-old/conflict, json, fix dry run, script
[ ] 19  legacy ~/.claude built by the real claude, no ~/.claude/.claude.json
[ ] 20  init refusals, B1 pre-check clean, init, every post-init check
[ ] 21  adopt: moves, conflict, removal, nothing to adopt
[ ] 22  uninstall: launchd clean, zshrc clean, round trip identical
[ ] 23  uninstall --from-backup: set aside, restored identical
[ ] 24  no secret in manifests, outputs or profile repositories
[ ] 26  cleanup: launchd, Keychain, token, sandbox, real state intact
```
