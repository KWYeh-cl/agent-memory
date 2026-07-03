#!/usr/bin/env bash
# install.sh — one command to set up agent-memory after cloning.
# Installs deps, then wires the MCP server + hooks + skill + always-on rules
# into your CLI, resolving all paths from this repo. Idempotent; safe to re-run.
#
# No DB is created here: the store is per-project and lazy (created on the first
# memory_save_checkpoint, at a cwd-relative agent_memory.db). Nothing sets
# AGENT_MEMORY_DB.
#
# Usage:
#   ./install.sh                    # Claude Code, user-global (~/.claude)
#   ./install.sh --codex            # also wire Codex (~/.codex)
#   ./install.sh --project .        # wire into ./.claude (+ ./.codex) instead of home
#   ./install.sh --project . --codex
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "python3 not found on PATH"; exit 1; }

echo "==> installing deps"
"$PY" -m pip install -r "$ROOT/core/requirements.txt"

echo "==> wiring config"
exec "$PY" "$ROOT/core/install.py" "$@"
