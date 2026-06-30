#!/usr/bin/env bash
# install.sh — set up agent-memory with paths resolved automatically.
# Safe by default: it installs deps, inits the DB, and GENERATES ready-to-use
# config files with real absolute paths into ./dist/. It does NOT edit your
# global ~/.claude or ~/.codex config unless you pass --copy-skill (skill only).
#
# Usage:
#   ./install.sh                 # core + generate configs for both tools
#   ./install.sh --claude        # only generate Claude Code configs
#   ./install.sh --codex         # only generate Codex config
#   ./install.sh --copy-skill    # also copy the skill into your user skills dir
#   ./install.sh --db /path.db   # use a specific DB path (default: repo/agent_memory.db)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "python3 not found on PATH"; exit 1; }

DB="$ROOT/agent_memory.db"
DO_CLAUDE=0; DO_CODEX=0; COPY_SKILL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --claude) DO_CLAUDE=1 ;;
    --codex)  DO_CODEX=1 ;;
    --copy-skill) COPY_SKILL=1 ;;
    --db) shift; DB="$1" ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
[ $DO_CLAUDE -eq 0 ] && [ $DO_CODEX -eq 0 ] && { DO_CLAUDE=1; DO_CODEX=1; }

echo "==> repo root: $ROOT"
echo "==> python:    $PY"
echo "==> db path:   $DB"

echo "==> installing deps"
"$PY" -m pip install -r "$ROOT/core/requirements.txt"

echo "==> initializing db (if absent)"
if [ ! -f "$DB" ]; then ( cd "$ROOT/core" && AGENT_MEMORY_DB="$DB" "$PY" mem_cli.py init ); else echo "    exists, skipping"; fi

mkdir -p "$ROOT/dist/claude-code" "$ROOT/dist/codex"
# Replace the shipped placeholder prefix with this repo's real path (folder-name agnostic).
fill() { sed -e "s|REPLACE_WITH_ABS_PATH/agent-memory|$ROOT|g" \
             -e "s|REPLACE_WITH_ABS_PATH/agent_memory.db|$DB|g" "$1"; }

if [ $DO_CLAUDE -eq 1 ]; then
  echo "==> generating Claude Code configs -> dist/claude-code/"
  fill "$ROOT/claude-code/.mcp.json"   | sed "s|$ROOT/agent_memory.db|$DB|g" > "$ROOT/dist/claude-code/.mcp.json"
  fill "$ROOT/claude-code/settings.json" > "$ROOT/dist/claude-code/settings.json"
  cp "$ROOT/claude-code/CLAUDE.md" "$ROOT/dist/claude-code/CLAUDE.md"
fi
if [ $DO_CODEX -eq 1 ]; then
  echo "==> generating Codex config -> dist/codex/"
  fill "$ROOT/codex/config.toml.snippet" > "$ROOT/dist/codex/config.toml.snippet"
  cp "$ROOT/codex/AGENTS.md" "$ROOT/dist/codex/AGENTS.md"
fi

if [ $COPY_SKILL -eq 1 ]; then
  if [ $DO_CLAUDE -eq 1 ]; then
    mkdir -p "$HOME/.claude/skills"; cp -R "$ROOT/skill/agent-memory" "$HOME/.claude/skills/" && echo "==> skill -> ~/.claude/skills/agent-memory"
  fi
  if [ $DO_CODEX -eq 1 ]; then
    mkdir -p "$HOME/.codex/skills"; cp -R "$ROOT/skill/agent-memory" "$HOME/.codex/skills/" && echo "==> skill -> ~/.codex/skills/agent-memory"
  fi
fi

cat <<EOF

Done. Generated configs (with real paths) are in: $ROOT/dist/
Next steps (these touch your CLI config, so review them yourself):

Claude Code:
  - Register MCP:  claude mcp add agent-memory "$PY" "$ROOT/core/mcp_server.py"
                   (then ensure its AGENT_MEMORY_DB=$DB)
  - Merge dist/claude-code/settings.json into ~/.claude/settings.json (hooks)
  - Skill: re-run with --copy-skill, or copy skill/agent-memory into ~/.claude/skills/
  - Append dist/claude-code/CLAUDE.md to your project CLAUDE.md

Codex:
  - Merge the [mcp_servers.agent-memory] block from dist/codex/config.toml.snippet
    into ~/.codex/config.toml
  - Skill: copy skill/agent-memory into .agents/skills/ (or ~/.codex/skills/)
  - Append dist/codex/AGENTS.md to your project AGENTS.md
  - Hooks: verify event names against the Codex Hooks doc before enabling

Or skip all of the above: open this folder in your CLI and say
"set up agent-memory by following SETUP_RUNBOOK.md".
EOF
