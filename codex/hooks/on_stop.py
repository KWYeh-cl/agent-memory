#!/usr/bin/env python3
"""Codex Stop hook wrapper.

Delegates to the shared Claude Code Stop hook, which emits the seal reminder on
stderr and exits 2. Codex treats "exit code 2 with stderr" as the continuation
reason for a Stop hook, so the same script drives the deterministic seal on
both CLIs (verified against developers.openai.com/codex/hooks). The reminder is
one-shot per session, so it never loops. DB path resolution (AGENT_MEMORY_DB,
or a cwd-relative "agent_memory.db" per project) happens in the shared hook.
"""
import os, runpy

_h = os.path.dirname(os.path.abspath(__file__))
runpy.run_path(
    os.path.join(_h, "..", "..", "claude-code", "hooks", "on_stop.py"),
    run_name="__main__",
)
