#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook -> inject <related_prior_tasks> for the
prompt, but only when THIS prompt itself signals wanting memory (continue,
resume, checkpoint, 之前, 記得, etc.) — not on every turn. A plain "add a
health check endpoint" prompt does not trigger a search; "continue where we
left off" does. Uses the same keyword check as the seal reminder, so the two
deterministic layers agree on what "shows memory intent" means.
"""
import json, os, subprocess, sys

CORE = os.environ.get("AGENT_MEMORY_CORE") or os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "core"))
sys.path.insert(0, CORE)
import mem_cli  # noqa: E402  (path must be set up first)

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

if mem_cli._mentions_memory(prompt):
    r = subprocess.run(
        [sys.executable, os.path.join(CORE, "mem_cli.py"), "find", prompt, "--limit", "5"],
        capture_output=True, text=True,
    )
    sys.stdout.write(r.stdout)  # injected into context (empty when no prior work)
