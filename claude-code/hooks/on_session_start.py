#!/usr/bin/env python3
"""Claude Code SessionStart hook -> record session sentinel (for seal reminder)."""
import json, os, subprocess, sys

CORE = os.environ.get("AGENT_MEMORY_CORE") or os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "core"))

data = {}
try:
    data = json.load(sys.stdin)
except Exception:
    pass
sid = data.get("session_id", "default")
subprocess.run([sys.executable, os.path.join(CORE, "mem_cli.py"), "session-start", sid])
