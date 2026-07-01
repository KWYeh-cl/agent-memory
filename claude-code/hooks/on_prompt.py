#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook -> inject <related_prior_tasks> for the prompt.

stdout from this hook is added to the model's context before it answers, so the
opening query happens deterministically without the model having to remember.
"""
import json, os, subprocess, sys

CORE = os.environ.get("AGENT_MEMORY_CORE") or os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "core"))

data = {}
try:
    data = json.load(sys.stdin)
except Exception:
    pass
prompt = data.get("prompt", "")
sid = data.get("session_id", "default")

# ensure the session sentinel exists even if SessionStart hook isn't configured;
# --prompt lets it arm the (opt-in) seal reminder if this prompt mentions memory
subprocess.run([sys.executable, os.path.join(CORE, "mem_cli.py"), "session-start", sid, "--prompt", prompt])

r = subprocess.run(
    [sys.executable, os.path.join(CORE, "mem_cli.py"), "find", prompt, "--limit", "5"],
    capture_output=True, text=True,
)
sys.stdout.write(r.stdout)  # injected into context (empty when no prior work)
