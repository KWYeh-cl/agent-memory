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
  python3 core/install.py --codex --db-path "~/Library/Application Support/vibeflow/agent_memory.db"

There is still no DB here: VibeFlow owns the shared User Data database. The
installer passes its path to both CLI MCP servers and hooks; without it, the
Python tooling falls back to its cwd.
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
PY = sys.executable  # absolute interpreter, so hooks work even if python3 isn't on PATH

MD_START = "<!-- agent-memory:start -->"
MD_END = "<!-- agent-memory:end -->"
TOML_START = "# >>> agent-memory (managed by install.py) >>>"
TOML_END = "# <<< agent-memory <<<"


class McpRegistrationError(RuntimeError):
    """Raised when a user-scope Claude MCP migration could not be completed."""


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


def hook_cmd(rel, db_path):
    return " ".join([
        f"AGENT_MEMORY_DB={shlex.quote(db_path)}",
        shlex.quote(PY),
        shlex.quote(os.path.join(ROOT, rel)),
    ])


def ensure_claude_hooks(settings, db_path):
    hooks = settings.setdefault("hooks", {})
    for event, rel in CLAUDE_EVENTS.items():
        cmd = hook_cmd(rel, db_path)
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
def wire_claude(project, db_path):
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
    settings = ensure_claude_hooks(read_json(settings_path), db_path)
    write_json(settings_path, settings)
    print(f"  hooks   -> {settings_path}")

    # 3. MCP server
    register_claude_mcp(project, db_path)

    # 4. always-on rules
    with open(os.path.join(ROOT, "claude-code/CLAUDE.md"), encoding="utf-8") as f:
        upsert_block(rules_path, f.read())
    print(f"  rules   -> {rules_path}")


def register_claude_mcp(project, db_path):
    server = os.path.join(ROOT, "core/mcp_server.py")
    if project:
        # project scope: we own .mcp.json — merge it directly, no CLI dependency.
        path = os.path.join(project, ".mcp.json")
        data = read_json(path)
        data.setdefault("mcpServers", {})["agent-memory"] = {
            "command": PY, "args": [server], "env": {"AGENT_MEMORY_DB": db_path}
        }
        write_json(path, data)
        print(f"  mcp     -> {path}")
        return
    # User scope: back up the actual Claude config before replacing an existing
    # agent-memory server. Never remove without a recoverable backup.
    if shutil.which("claude"):
        path = os.path.expanduser("~/.claude.json")
        data = read_json(path)
        has_existing = "agent-memory" in data.get("mcpServers", {})
        backup_path = None
        if os.path.exists(path):
            backup_path = path + ".bak"
            shutil.copy2(path, backup_path)

        if has_existing:
            if not backup_path or not os.path.exists(backup_path):
                raise McpRegistrationError(
                    "cannot safely update user-scope agent-memory: no recoverable ~/.claude.json backup"
                )
            removed = subprocess.run(
                ["claude", "mcp", "remove", "-s", "user", "agent-memory"],
                capture_output=True, text=True,
            )
            if removed.returncode != 0:
                raise McpRegistrationError(
                    "failed to remove existing user-scope agent-memory: "
                    f"{removed.stderr.strip() or removed.stdout.strip()}"
                )

        r = subprocess.run(
            ["claude", "mcp", "add", "-s", "user", "agent-memory", "-e",
             f"AGENT_MEMORY_DB={db_path}", "--", PY, server],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            action = "updated" if has_existing else "registered"
            print(f"  mcp     -> {action} agent-memory via `claude mcp add -s user`")
            return
        if backup_path:
            shutil.copy2(backup_path, path)
        raise McpRegistrationError(
            "failed to add user-scope agent-memory; restored ~/.claude.json backup: "
            f"{r.stderr.strip() or r.stdout.strip()}"
        )
    path = os.path.expanduser("~/.claude.json")
    data = read_json(path)
    data.setdefault("mcpServers", {})["agent-memory"] = {
        "command": PY, "args": [server], "env": {"AGENT_MEMORY_DB": db_path}
    }
    write_json(path, data)
    print(f"  mcp     -> {path} (claude CLI not found; edited config directly)")


# ---- Codex -----------------------------------------------------------------
def codex_toml_block(db_path):
    server = os.path.join(ROOT, "core/mcp_server.py")

    def command(rel):
        return hook_cmd(rel, db_path)

    return "\n".join([
        TOML_START,
        "[mcp_servers.agent-memory]",
        f"command = {json.dumps(PY)}",
        f"args = [{json.dumps(server)}]",
        "[mcp_servers.agent-memory.env]",
        f"AGENT_MEMORY_DB = {json.dumps(db_path)}",
        "",
        "[[hooks.SessionStart]]",
        "[[hooks.SessionStart.hooks]]",
        'type = "command"',
        f"command = {json.dumps(command('codex/hooks/on_session_start.py'))}",
        "",
        "[[hooks.UserPromptSubmit]]",
        "[[hooks.UserPromptSubmit.hooks]]",
        'type = "command"',
        f"command = {json.dumps(command('codex/hooks/on_prompt.py'))}",
        "",
        "[[hooks.Stop]]",
        "[[hooks.Stop.hooks]]",
        'type = "command"',
        f"command = {json.dumps(command('codex/hooks/on_stop.py'))}",
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


def wire_codex(project, db_path):
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
    upsert_toml_block(config_path, codex_toml_block(db_path))
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
    ap.add_argument(
        "--db-path",
        default=os.path.expanduser("~/Library/Application Support/vibeflow/agent_memory.db"),
        help="VibeFlow shared Agent Memory DB path for CLI wiring (default: %(default)s)",
    )
    args = ap.parse_args()

    project = os.path.abspath(args.project) if args.project else None
    db_path = os.path.abspath(os.path.expanduser(args.db_path))
    where = f"project {project}" if project else "user-global (home)"
    print(f"agent-memory: wiring from {ROOT}\n  target  -> {where}\n")

    try:
        print("Claude Code:")
        wire_claude(project, db_path)
        if args.codex:
            print("\nCodex:")
            wire_codex(project, db_path)
    except McpRegistrationError as e:
        print(f"! agent-memory installation failed: {e}", file=sys.stderr)
        return 1

    print("\nDone. Restart your CLI, then verify with /mcp (lists agent-memory).")
    print("No db was created — VibeFlow creates its shared User Data db on the first checkpoint.")
    if args.codex:
        print(f"Codex AGENT_MEMORY_DB -> {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
