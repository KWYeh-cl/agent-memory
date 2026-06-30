#!/usr/bin/env python3
"""Codex SessionStart hook wrapper.

Codex has no settings-level env block (unlike Claude Code), so we pin
AGENT_MEMORY_DB here, then delegate to the shared Claude Code hook so the hook
logic lives in exactly one place. Event name / stdin-JSON / output contract are
identical between the two CLIs (verified against developers.openai.com/codex/hooks).

The DB path is derived relative to this file (ROOT/codex/hooks -> ROOT), so the
repo stays free of machine-specific absolute paths. Override with AGENT_MEMORY_DB.
"""
import os, runpy

_h = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault(
    "AGENT_MEMORY_DB",
    os.path.normpath(os.path.join(_h, "..", "..", "agent_memory.db")),
)
runpy.run_path(
    os.path.join(_h, "..", "..", "claude-code", "hooks", "on_session_start.py"),
    run_name="__main__",
)
