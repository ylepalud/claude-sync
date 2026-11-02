#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "install.sh: uv is required but was not found on PATH." >&2
  echo "Install it first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

uv tool install --force "${CLAUDE_SYNC_SOURCE:-git+https://github.com/ylepalud/claude-sync}"
claude-sync --version
