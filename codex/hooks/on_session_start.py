#!/usr/bin/env python3
"""Codex SessionStart hook wrapper.

Delegates to the shared Claude Code hook so the hook logic lives in exactly one
place. Event name / stdin-JSON / output contract are identical between the two
CLIs (verified against developers.openai.com/codex/hooks). The command wrapper
sets AGENT_MEMORY_DB to VibeFlow's shared User Data DB before delegating.
"""
import os, runpy

_h = os.path.dirname(os.path.abspath(__file__))
runpy.run_path(
    os.path.join(_h, "..", "..", "claude-code", "hooks", "on_session_start.py"),
    run_name="__main__",
)
