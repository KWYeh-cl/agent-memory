#!/usr/bin/env python3
"""Wire agent-memory into Claude Code and optionally Codex.

The installed memory store is a single SQLite file at ROOT/agent_memory.db.
Re-running the installer updates managed config in place and imports known
legacy stores so every app/CLI points at the same memory after install.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import memory
import migrate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

MD_START = "<!-- agent-memory:start -->"
MD_END = "<!-- agent-memory:end -->"
TOML_START = "# >>> agent-memory (managed by install.py) >>>"
TOML_END = "# <<< agent-memory <<<"


class McpRegistrationError(RuntimeError):
    """Raised when a user-scope Claude MCP migration could not be completed."""


def read_json(path):
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
    os.replace(tmp, path)


def upsert_block(path, body):
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
    settings.setdefault("env", {})["AGENT_MEMORY_ROOT"] = ROOT
    settings["env"].pop("AGENT_MEMORY_DB", None)
    return settings


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

    copy_skill(skills_dir)
    settings = ensure_claude_hooks(read_json(settings_path))
    write_json(settings_path, settings)
    print(f"  hooks   -> {settings_path}")

    register_claude_mcp(project)

    with open(os.path.join(ROOT, "claude-code/CLAUDE.md"), encoding="utf-8") as f:
        upsert_block(rules_path, f.read())
    print(f"  rules   -> {rules_path}")


def agent_memory_server():
    return {"command": PY, "args": [os.path.join(ROOT, "core/mcp_server.py")],
            "env": {"AGENT_MEMORY_ROOT": ROOT}}


def register_claude_mcp(project):
    server = os.path.join(ROOT, "core/mcp_server.py")
    if project:
        path = os.path.join(project, ".mcp.json")
        data = read_json(path)
        data.setdefault("mcpServers", {})["agent-memory"] = agent_memory_server()
        write_json(path, data)
        print(f"  mcp     -> {path}")
        return

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
             f"AGENT_MEMORY_ROOT={ROOT}", "--", PY, server],
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
    data.setdefault("mcpServers", {})["agent-memory"] = agent_memory_server()
    write_json(path, data)
    print(f"  mcp     -> {path} (claude CLI not found; edited config directly)")


def codex_toml_block():
    server = os.path.join(ROOT, "core/mcp_server.py")

    def hk(rel):
        return os.path.join(ROOT, rel)

    return "\n".join([
        TOML_START,
        "[mcp_servers.agent-memory]",
        f"command = {json.dumps(PY)}",
        f"args = [{json.dumps(server)}]",
        "",
        "[mcp_servers.agent-memory.env]",
        f"AGENT_MEMORY_ROOT = {json.dumps(ROOT)}",
        "",
        "[[hooks.SessionStart]]",
        "[[hooks.SessionStart.hooks]]",
        'type = "command"',
        f"command = {json.dumps(f'{PY} {hk('codex/hooks/on_session_start.py')}')}",
        "",
        "[[hooks.UserPromptSubmit]]",
        "[[hooks.UserPromptSubmit.hooks]]",
        'type = "command"',
        f"command = {json.dumps(f'{PY} {hk('codex/hooks/on_prompt.py')}')}",
        "",
        "[[hooks.Stop]]",
        "[[hooks.Stop.hooks]]",
        'type = "command"',
        f"command = {json.dumps(f'{PY} {hk('codex/hooks/on_stop.py')}')}",
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


def copy_skill(skills_dir):
    dest = os.path.join(skills_dir, "agent-memory")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(os.path.join(ROOT, "skill/agent-memory"), dest)
    print(f"  skill   -> {dest}")


def init_root_db():
    memory.init_db(memory.DB_PATH)
    print(f"  db      -> {memory.DB_PATH}")
    imported = [item for item in migrate.merge_databases() if not item.get("skipped")]
    if not imported:
        print("  import  -> no legacy DBs found")
        return
    for item in imported:
        print(
            "  import  -> {source} "
            "(tasks={tasks}, checkpoints={checkpoints}, artifacts={artifacts}, links={links})"
            .format(**item)
        )


def main():
    ap = argparse.ArgumentParser(prog="install.py", description="Wire agent-memory into your CLIs.")
    ap.add_argument("--codex", action="store_true", help="also wire Codex")
    ap.add_argument("--project", metavar="DIR",
                    help="install into DIR (project scope) instead of your home config")
    args = ap.parse_args()

    project = os.path.abspath(args.project) if args.project else None
    where = f"project {project}" if project else "user-global (home)"
    print(f"agent-memory: wiring from {ROOT}\n  target  -> {where}\n")

    print("Memory store:")
    init_root_db()
    print("")

    try:
        print("Claude Code:")
        wire_claude(project)
        if args.codex:
            print("\nCodex:")
            wire_codex(project)
    except McpRegistrationError as e:
        print(f"! agent-memory installation failed: {e}", file=sys.stderr)
        return 1

    print("\nDone. Restart your CLI, then verify with /mcp (lists agent-memory).")
    print(f"All default memory reads/writes now use {memory.DB_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
