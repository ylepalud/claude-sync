"""The zsh snippet printed by `claude-sync shell-init zsh`."""

from claude_sync import paths
from claude_sync.config import PROFILE_NAME, Config

FUNCTIONS = r"""
_claude_sync_resolve() {
  emulate -L zsh; setopt case_match  # whatever options the caller set
  local dir=${1:-$PWD}; dir=${dir:A}; local i
  for (( i = 1; i < ${#_claude_sync_matches}; i += 2 )); do
    [[ $dir == "$_claude_sync_matches[i]" || $dir == "$_claude_sync_matches[i]"/* ]] \
      && { REPLY=$_claude_sync_matches[i+1]; return }
  done
  REPLY=$_claude_sync_default
}

_claude_sync_apply() {
  emulate -L zsh; setopt case_match  # whatever options the caller set
  local LC_ALL=C  # ASCII ranges in =~, whatever the locale
  local REPLY
  if (( ! ${+CLAUDE_SYNC_OVERRIDE} )); then
    _claude_sync_resolve
  elif [[ $CLAUDE_SYNC_OVERRIDE =~ $_claude_sync_name_re ]]; then
    REPLY=$CLAUDE_SYNC_OVERRIDE
  else
    # It may come from the environment: warn once per value, then ignore it.
    if [[ ${_claude_sync_warned-} != "$CLAUDE_SYNC_OVERRIDE" ]]; then
      typeset -g _claude_sync_warned=$CLAUDE_SYNC_OVERRIDE
      print -ru2 -- "claude-sync: ignoring invalid CLAUDE_SYNC_OVERRIDE" \
        "${(qq)CLAUDE_SYNC_OVERRIDE} (expected $_claude_sync_name_rule)"
    fi
    _claude_sync_resolve
  fi
  export CLAUDE_SYNC_PROFILE=$REPLY
  local dir=$_claude_sync_root/$REPLY mark=
  if [[ -d $dir ]]; then
    export CLAUDE_CONFIG_DIR=$dir
  else
    mark='?'
    # Not initialized: give back the user's value, or drop one we own.
    if [[ -n ${CLAUDE_SYNC_USER_CONFIG_DIR-} ]]; then
      export CLAUDE_CONFIG_DIR=$CLAUDE_SYNC_USER_CONFIG_DIR
    elif [[ ${CLAUDE_CONFIG_DIR-} == "$_claude_sync_root"/* ]]; then
      unset CLAUDE_CONFIG_DIR
    fi
  fi
  [[ ${CLAUDE_SYNC_PROMPT-} == 0 ]] ||
    RPROMPT="claude:${REPLY}${mark}${_claude_sync_rprompt_base:+ $_claude_sync_rprompt_base}"
}

claude-sync-use() {
  emulate -L zsh; setopt case_match  # whatever options the caller set
  local LC_ALL=C  # ASCII ranges in =~, whatever the locale
  if [[ $1 == --auto ]]; then
    unset CLAUDE_SYNC_OVERRIDE
  elif [[ $1 =~ $_claude_sync_name_re ]]; then
    export CLAUDE_SYNC_OVERRIDE=$1
  else
    print -ru2 -- "claude-sync-use: invalid profile name ${(qq)1}" \
      "(expected $_claude_sync_name_rule)"
    return 1
  fi
  _claude_sync_apply
}

claude-sync-reload() {
  # A failing claude-sync (missing, invalid config) keeps the current snippet.
  local code
  code=$(command claude-sync shell-init zsh) || return
  eval "$code"
}
"""

HOOK = r"""
if (( ! ${+_claude_sync_loaded} )); then
  typeset -g _claude_sync_loaded=1
  typeset -g _claude_sync_rprompt_base=${RPROMPT-}
  # A value outside the profiles root was set by the user: remember it.
  if [[ -n ${CLAUDE_CONFIG_DIR-} && $CLAUDE_CONFIG_DIR != "$_claude_sync_root"/* \
        && -z ${CLAUDE_SYNC_USER_CONFIG_DIR-} ]]; then
    export CLAUDE_SYNC_USER_CONFIG_DIR=$CLAUDE_CONFIG_DIR
  fi
fi
autoload -Uz add-zsh-hook
add-zsh-hook chpwd _claude_sync_apply
_claude_sync_apply
"""


def quote(value: str) -> str:
    """Quote `value` for zsh single quotes."""
    return "'" + value.replace("'", "'\\''") + "'"


def render(config: Config) -> str:
    # Normalized here so zsh compares resolved paths; longest first so the first
    # hit is the longest match (applying matches are a chain of ancestors).
    # The sort is stable, so equal paths keep the config order, as in resolve().
    matches = sorted(
        ((str(paths.key(m.path)), m.profile) for m in config.matches),
        key=lambda pair: -len(pair[0]),
    )
    words = " ".join(f"{quote(path)} {quote(profile)}" for path, profile in matches)
    header = (
        f"typeset -g _claude_sync_default={quote(config.default)}\n"
        f"typeset -g _claude_sync_name_rule={quote(PROFILE_NAME.pattern)}\n"
        f"typeset -g _claude_sync_name_re={quote('^' + PROFILE_NAME.pattern + '$')}\n"
        f"typeset -g _claude_sync_root={quote(str(paths.profiles_root()))}\n"
        f"typeset -ga _claude_sync_matches=({words})\n"
    )
    return header + FUNCTIONS + HOOK
