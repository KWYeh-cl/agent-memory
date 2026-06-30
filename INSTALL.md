# Install

Same core for both tools. You install three things: the **MCP server** (in-session
tools), the **skill** (the protocol), and the **hooks** (the deterministic
opening-query + seal). Only the wiring differs per tool.

## 0. One-time core setup

```bash
cd agent-memory/core
python3 -m pip install -r requirements.txt        # mcp, pydantic
python3 mem_cli.py init                            # creates agent_memory.db
```

Pick an absolute path for the package, e.g. `/Users/you/agent-memory`. Everywhere
below, replace `REPLACE_WITH_ABS_PATH` with the parent of that `agent-memory`
folder. `python3` must be on PATH for the hooks; use a full interpreter path if not.

---

## Claude Code

1. **MCP server** — copy `claude-code/.mcp.json` to your project root (or merge
   into an existing one), and fix the two paths. Or instead run:
   ```bash
   claude mcp add agent-memory python3 REPLACE_WITH_ABS_PATH/agent-memory/core/mcp_server.py
   ```
2. **Skill** — copy the folder `skill/agent-memory/` to
   `.claude/skills/agent-memory/` (project) or `~/.claude/skills/agent-memory/`
   (all projects).
3. **Hooks** — merge `claude-code/settings.json` into `.claude/settings.json`
   (project) or `~/.claude/settings.json`, fixing the three paths. These wire:
   - `SessionStart` → records the session sentinel
   - `UserPromptSubmit` → injects `<related_prior_tasks>` (forced opening query)
   - `Stop` → reminds to seal if nothing was checkpointed (fires once)
4. **Always-on rules** — copy `claude-code/CLAUDE.md` into your project `CLAUDE.md`
   (or append its contents).
5. Restart Claude Code. Verify: `/mcp` lists `agent-memory`; type a task and the
   model should see prior tasks; finish without sealing and the Stop hook nudges.

---

## Codex CLI

1. **MCP server + (optional) hooks** — open `codex/config.toml.snippet`, fix the
   paths, and paste the `[mcp_servers.agent-memory]` block into
   `~/.codex/config.toml` (or `<project>/.codex/config.toml`, which loads only
   when the project is trusted).
2. **Skill** — copy the folder `skill/agent-memory/` to
   `<project>/.agents/skills/agent-memory/` or `~/.codex/skills/agent-memory/`.
3. **Always-on rules** — copy `codex/AGENTS.md` into your project `AGENTS.md`
   (or append its contents).
4. **Hooks (deterministic layer)** — the snippet includes a hooks template, but
   Codex's hook event names/schema differ from Claude Code's and change between
   releases. Verify them against the Codex *Hooks* doc before relying on it. Each
   hook calls the same `mem_cli.py` commands (`find`, `session-start`,
   `seal-reminder`). If Codex hooks can't inject context / block a turn the way
   you need, the MCP tools + skill + AGENTS.md still give the full workflow — you
   just lose the *guarantee*, and the opening query + seal become advisory.
5. Restart Codex. Verify: `/mcp` lists the server; `/skills` (or `$`) shows
   `agent-memory`.

---

## What's deterministic vs advisory

| Step | Claude Code | Codex |
|------|-------------|-------|
| In-session tools (find / detail / artifact / save / link) | MCP — works | MCP — works |
| Protocol (when/how to use them) | skill + CLAUDE.md — advisory | skill + AGENTS.md — advisory |
| Opening query injection | UserPromptSubmit hook — **deterministic** | hook (verify) or advisory |
| Seal-on-handoff reminder | Stop hook — **deterministic** (once/session) | hook (verify) or advisory |

The MCP server and skill are fully portable and identical across both. The hooks
are the only tool-specific part, and the only place the determinism guarantee lives.

## Notes
- The DB is one SQLite file (`AGENT_MEMORY_DB`). Point every entry point at the
  same path so tools and hooks share state.
- `AGENT_MEMORY_COMPRESS_AT` (default 12) sets when `save_checkpoint` reports
  `compressed: true`. The actual merge needs a model call — see `mem_cli compress`
  to list candidates, then call `memory.apply_compression(...)` from your own script.
- Sub-agents: each gets its own task_id and seals its own checkpoint; the next
  agent's opening query surfaces it. No extra wiring needed.
