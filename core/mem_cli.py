#!/usr/bin/env python3
"""
mem_cli.py — thin command-line surface over memory.py, used by HOOKS.

Hooks can't call MCP tools directly, so the deterministic steps go through this
CLI instead. The agent uses the MCP server for judgment-driven actions; the
hooks use this CLI for the two steps that must happen no matter what:

  find            -> opening query, printed as an injectable context block
                     (wire to a prompt-submit hook)
  session-start   -> record a per-session timestamp sentinel
  seal-reminder   -> if no checkpoint was written since session start, emit a
                     reminder and exit 2 so the harness feeds it back to the model
                     (wire to a stop / session-end hook)

Everything here is local and cheap; no model calls.
"""

import argparse
import json
import os
import sys
import tempfile

import memory

STATE_DIR = os.path.join(tempfile.gettempdir(), "agent_memory_sessions")


def _sentinel(session_id: str) -> str:
    os.makedirs(STATE_DIR, exist_ok=True)
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "default"
    return os.path.join(STATE_DIR, safe)


def cmd_init(args):
    memory.init_db()
    print("memory db ready")


def cmd_find(args):
    tags = [t for t in (args.tags or "").split(",") if t.strip()]
    results = memory.find_related_tasks(args.query, tags, args.limit)
    if not results:
        # Print nothing to inject when there's no prior work; keeps context clean.
        return
    block = ["<related_prior_tasks note=\"auto-retrieved from memory; reuse instead of redoing\">"]
    for r in results:
        block.append(
            f"- id={r['id']} | {r['title']} | {r.get('summary','')} "
            f"| tags={','.join(r.get('tags', []))} "
            f"(call memory_get_task_detail to load decisions/checkpoints)"
        )
    block.append("</related_prior_tasks>")
    print("\n".join(block))


def cmd_session_start(args):
    # Create-if-absent: safe to call on every prompt without resetting the
    # session window or the one-shot reminder flag.
    path = _sentinel(args.session_id)
    if os.path.exists(path):
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"start": memory._now(), "reminded": False}, f)


def cmd_seal_reminder(args):
    path = _sentinel(args.session_id)
    state = {"start": "", "reminded": False}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            pass
    if state.get("reminded"):
        return  # fire at most once per session, never loop

    since = state.get("start") or ""
    conn = memory.connect()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM checkpoints WHERE created_at >= ?", (since,)
    ).fetchone()
    conn.close()
    if row["c"] == 0:
        state["reminded"] = True
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except Exception:
            pass
        sys.stderr.write(
            "No checkpoint was saved this session. Before finishing, seal the work: "
            "call memory_save_checkpoint with the rolling summary, this stage's "
            "outcome, key decisions + reasons, open items, and any large outputs as "
            "artifacts. Skip only if no substantive task work happened.\n"
        )
        sys.exit(2)  # exit 2 => the CLI feeds stderr back to the model


def cmd_compress(args):
    """Report which old checkpoints would be merged. Actual merge needs a model
    call to write the merged summary — run that from your own script, then call
    memory.apply_compression(). This command just surfaces the candidates."""
    old = memory.get_checkpoints_for_compression(args.task_id, args.keep_recent)
    print(json.dumps({"task_id": args.task_id, "candidates": old}, ensure_ascii=False, default=str))


def main():
    p = argparse.ArgumentParser(prog="mem_cli")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("init"); s.set_defaults(fn=cmd_init)

    s = sub.add_parser("find"); s.add_argument("query"); s.add_argument("--tags", default="")
    s.add_argument("--limit", type=int, default=5); s.set_defaults(fn=cmd_find)

    s = sub.add_parser("session-start"); s.add_argument("session_id"); s.set_defaults(fn=cmd_session_start)

    s = sub.add_parser("seal-reminder"); s.add_argument("session_id"); s.set_defaults(fn=cmd_seal_reminder)

    s = sub.add_parser("compress"); s.add_argument("task_id")
    s.add_argument("--keep-recent", type=int, default=3); s.set_defaults(fn=cmd_compress)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
