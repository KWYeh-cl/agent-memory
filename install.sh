#!/usr/bin/env bash
# install.sh — one command to set up agent-memory after cloning.
# Installs deps, then wires the MCP server + hooks + skill + always-on rules
# into your CLI, resolving all paths from this repo. Idempotent; safe to re-run.
#
# The installer initializes the single root memory store at
# ./agent_memory.db and imports known legacy stores. All CLIs/apps use that
# install-root DB unless AGENT_MEMORY_DB/AGENT_MEMORY_ROOT is set explicitly.
#
# Usage:
#   ./install.sh                    # Claude Code, user-global (~/.claude)
#   ./install.sh --codex            # also wire Codex (~/.codex)
#   ./install.sh --project .        # wire into ./.claude (+ ./.codex) instead of home
#   ./install.sh --project . --codex
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
  PY=(python3)
elif command -v python >/dev/null 2>&1; then
  PY=(python)
elif command -v py >/dev/null 2>&1; then
  PY=(py -3)
else
  echo "python3/python/py not found on PATH"
  exit 1
fi

echo "==> installing deps"
"${PY[@]}" -m ensurepip --upgrade >/dev/null 2>&1 || true
"${PY[@]}" -m pip install -r "$ROOT/core/requirements.txt"

echo "==> wiring config"
exec "${PY[@]}" "$ROOT/core/install.py" "$@"
