#!/usr/bin/env python3
"""Codex UserPromptSubmit hook wrapper.

Pins AGENT_MEMORY_DB (derived relative to this file), then delegates to the
shared Claude Code hook. Its plain stdout (<related_prior_tasks>) is injected as
developer context by Codex, same as Claude Code (verified against
developers.openai.com/codex/hooks). Override the DB path with AGENT_MEMORY_DB.
"""
import os, runpy

_h = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault(
    "AGENT_MEMORY_DB",
    os.path.normpath(os.path.join(_h, "..", "..", "agent_memory.db")),
)
runpy.run_path(
    os.path.join(_h, "..", "..", "claude-code", "hooks", "on_prompt.py"),
    run_name="__main__",
)
