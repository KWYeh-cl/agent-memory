#!/usr/bin/env python3
"""Claude Code Stop hook -> if no checkpoint was saved this session, block once
and tell the model to seal the work (exit 2 feeds stderr back to the model).

A hook can't author the summary, so it can't *do* the seal — but it guarantees
the model is told to seal before the turn is allowed to finish. Fires at most
once per session (tracked in the sentinel) so it never loops.
"""
import json, os, subprocess, sys

CORE = os.environ.get("AGENT_MEMORY_CORE") or os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "core"))

data = {}
try:
    data = json.load(sys.stdin)
except Exception:
    pass
sid = data.get("session_id", "default")

r = subprocess.run([sys.executable, os.path.join(CORE, "mem_cli.py"), "seal-reminder", sid],
                   capture_output=True, text=True)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)  # propagate exit 2 (block) when a seal is missing
