#!/usr/bin/env python3
"""install.py — wire agent-memory into Claude Code (and optionally Codex),
resolving every path from this repo's own location. No placeholders to fill.

This replaces the old "generate configs into dist/ then hand-merge them
yourself" flow: clone the repo, run this once, and the MCP server + hooks +
skill + always-on rules are all registered. Idempotent — re-running updates in
place (guarded by markers / dedup checks) instead of duplicating anything.

  python3 core/install.py                 # Claude Code, user-global (~/.claude)
  python3 core/install.py --codex         # also wire Codex (~/.codex)
  python3 core/install.py --project DIR    # wire into DIR/.claude (+ DIR/.codex) instead of home
  python3 core/install.py --project . --codex

There is still no DB here: the store stays per-project and lazy, created on the
first memory_save_checkpoint. Nothing below sets AGENT_MEMORY_DB.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
PY = sys.executable  # absolute interpreter, so hooks work even if python3 isn't on PATH

MD_START = "<!-- agent-memory:start -->"
MD_END = "<!-- agent-memory:end -->"
TOML_START = "# >>> agent-memory (managed by install.py) >>>"
TOML_END = "# <<< agent-memory <<<"


# ---- small IO helpers ------------------------------------------------------
def read_json(path):
    """Return parsed JSON, or {} if the file is absent. Abort (never overwrite)
    if the file exists but is invalid — clobbering a user's settings on a parse
    error would be silent data loss."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.exit(f"! {path} exists but is not valid JSON ({e}); fix or remove it, then re-run.")


def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)  # atomic; a crash mid-write can't corrupt the original


def upsert_block(path, body):
    """Insert/replace `body` between MD markers in a markdown file. Idempotent:
    a second run swaps the old block for the new one instead of appending."""
    block = f"{MD_START}\n{body.rstrip()}\n{MD_END}\n"
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if MD_START in old and MD_END in old:
        pre = old[: old.index(MD_START)]
        post = old[old.index(MD_END) + len(MD_END):].lstrip("\n")
        new = pre.rstrip() + ("\n\n" if pre.strip() else "") + block + (post if post else "")
    else:
        new = (old.rstrip() + "\n\n" if old.strip() else "") + block
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)


# ---- hook wiring -----------------------------------------------------------
CLAUDE_EVENTS = {
    "SessionStart": "claude-code/hooks/on_session_start.py",
    "UserPromptSubmit": "claude-code/hooks/on_prompt.py",
    "Stop": "claude-code/hooks/on_stop.py",
}


def hook_cmd(rel):
    return f"{PY} {os.path.join(ROOT, rel)}"


def ensure_claude_hooks(settings):
    hooks = settings.setdefault("hooks", {})
    for event, rel in CLAUDE_EVENTS.items():
        cmd = hook_cmd(rel)
        entries = hooks.setdefault(event, [])
        # dedup by the hook script path, ignoring which interpreter prefixes it,
        # so an interpreter change updates in place rather than adding a twin.
        script = os.path.join(ROOT, rel)
        already = any(
            script in h.get("command", "")
            for entry in entries
            for h in entry.get("hooks", [])
        )
        if already:
            for entry in entries:
                for h in entry.get("hooks", []):
                    if script in h.get("command", ""):
                        h["command"] = cmd
        else:
            entries.append({"hooks": [{"type": "command", "command": cmd}]})
    return settings


# ---- Claude Code -----------------------------------------------------------
def wire_claude(project):
    if project:
        base = os.path.join(project, ".claude")
        settings_path = os.path.join(base, "settings.json")
        skills_dir = os.path.join(base, "skills")
        rules_path = os.path.join(project, "CLAUDE.md")
    else:
        base = os.path.expanduser("~/.claude")
        settings_path = os.path.join(base, "settings.json")
        skills_dir = os.path.join(base, "skills")
        rules_path = os.path.join(base, "CLAUDE.md")

    # 1. skill
    copy_skill(skills_dir)

    # 2. hooks
    settings = ensure_claude_hooks(read_json(settings_path))
    write_json(settings_path, settings)
    print(f"  hooks   -> {settings_path}")

    # 3. MCP server
    register_claude_mcp(project)

    # 4. always-on rules
    with open(os.path.join(ROOT, "claude-code/CLAUDE.md"), encoding="utf-8") as f:
        upsert_block(rules_path, f.read())
    print(f"  rules   -> {rules_path}")


def register_claude_mcp(project):
    server = os.path.join(ROOT, "core/mcp_server.py")
    if project:
        # project scope: we own .mcp.json — merge it directly, no CLI dependency.
        path = os.path.join(project, ".mcp.json")
        data = read_json(path)
        data.setdefault("mcpServers", {})["agent-memory"] = {
            "command": PY, "args": [server]
        }
        write_json(path, data)
        print(f"  mcp     -> {path}")
        return
    # user scope: prefer the blessed CLI; fall back to editing ~/.claude.json.
    if shutil.which("claude"):
        r = subprocess.run(
            ["claude", "mcp", "add", "-s", "user", "agent-memory", "--", PY, server],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            print("  mcp     -> registered via `claude mcp add -s user`")
            return
        # non-zero usually means "already exists" — treat as fine, but keep it visible.
        print("  mcp     -> `claude mcp add` skipped "
              f"(already registered? {r.stderr.strip() or r.stdout.strip()})")
        return
    path = os.path.expanduser("~/.claude.json")
    data = read_json(path)
    data.setdefault("mcpServers", {})["agent-memory"] = {"command": PY, "args": [server]}
    write_json(path, data)
    print(f"  mcp     -> {path} (claude CLI not found; edited config directly)")


# ---- Codex -----------------------------------------------------------------
def codex_toml_block():
    server = os.path.join(ROOT, "core/mcp_server.py")

    def hk(rel):
        return os.path.join(ROOT, rel)

    return "\n".join([
        TOML_START,
        "[mcp_servers.agent-memory]",
        f'command = "{PY}"',
        f'args = ["{server}"]',
        "",
        "[[hooks.SessionStart]]",
        "[[hooks.SessionStart.hooks]]",
        'type = "command"',
        f'command = "{PY} {hk("codex/hooks/on_session_start.py")}"',
        "",
        "[[hooks.UserPromptSubmit]]",
        "[[hooks.UserPromptSubmit.hooks]]",
        'type = "command"',
        f'command = "{PY} {hk("codex/hooks/on_prompt.py")}"',
        "",
        "[[hooks.Stop]]",
        "[[hooks.Stop.hooks]]",
        'type = "command"',
        f'command = "{PY} {hk("codex/hooks/on_stop.py")}"',
        TOML_END,
        "",
    ])


def upsert_toml_block(path, block):
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if TOML_START in old and TOML_END in old:
        pre = old[: old.index(TOML_START)]
        post = old[old.index(TOML_END) + len(TOML_END):].lstrip("\n")
        new = pre.rstrip() + "\n\n" + block + post
    else:
        new = (old.rstrip() + "\n\n" if old.strip() else "") + block
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)


def wire_codex(project):
    if project:
        skills_dir = os.path.join(project, ".agents/skills")
        config_path = os.path.join(project, ".codex/config.toml")
        rules_path = os.path.join(project, "AGENTS.md")
    else:
        base = os.path.expanduser("~/.codex")
        skills_dir = os.path.join(base, "skills")
        config_path = os.path.join(base, "config.toml")
        rules_path = os.path.join(base, "AGENTS.md")

    copy_skill(skills_dir)
    upsert_toml_block(config_path, codex_toml_block())
    print(f"  config  -> {config_path}")
    with open(os.path.join(ROOT, "codex/AGENTS.md"), encoding="utf-8") as f:
        upsert_block(rules_path, f.read())
    print(f"  rules   -> {rules_path}")


# ---- shared ----------------------------------------------------------------
def copy_skill(skills_dir):
    dest = os.path.join(skills_dir, "agent-memory")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(os.path.join(ROOT, "skill/agent-memory"), dest)
    print(f"  skill   -> {dest}")


def main():
    ap = argparse.ArgumentParser(prog="install.py", description="Wire agent-memory into your CLIs.")
    ap.add_argument("--codex", action="store_true", help="also wire Codex")
    ap.add_argument("--project", metavar="DIR",
                    help="install into DIR (project scope) instead of your home config")
    args = ap.parse_args()

    project = os.path.abspath(args.project) if args.project else None
    where = f"project {project}" if project else "user-global (home)"
    print(f"agent-memory: wiring from {ROOT}\n  target  -> {where}\n")

    print("Claude Code:")
    wire_claude(project)
    if args.codex:
        print("\nCodex:")
        wire_codex(project)

    print("\nDone. Restart your CLI, then verify with /mcp (lists agent-memory).")
    print("No db was created — that happens per project on the first checkpoint.")


if __name__ == "__main__":
    main()
