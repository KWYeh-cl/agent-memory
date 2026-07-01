#!/usr/bin/env python3
"""Codex UserPromptSubmit hook wrapper.

Delegates to the shared Claude Code hook, which resolves AGENT_MEMORY_DB (or
falls back to a cwd-relative "agent_memory.db", giving each project its own
store). Its plain stdout (<related_prior_tasks>) is injected as developer
context by Codex, same as Claude Code (verified against
developers.openai.com/codex/hooks).
"""
import os, runpy

_h = os.path.dirname(os.path.abspath(__file__))
runpy.run_path(
    os.path.join(_h, "..", "..", "claude-code", "hooks", "on_prompt.py"),
    run_name="__main__",
)
