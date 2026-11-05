#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "install.sh: uv is required but was not found on PATH." >&2
  echo "Install it first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

# --reinstall: the version rarely changes, and uv would reuse a wheel it
# already built for it, installing stale code from a local clone.
uv tool install --force --reinstall "${CLAUDE_SYNC_SOURCE:-git+https://github.com/ylepalud/claude-sync}"
claude-sync --version
