# Install

Same core for both tools. You install three things: the **MCP server** (in-session
tools), the **skill** (the protocol), and the **hooks** (the deterministic
opening-query + seal). Only the wiring differs per tool.

## 0. One-time core setup

```bash
cd agent-memory/core
python3 -m pip install -r requirements.txt        # mcp, pydantic
```

That's it — there's no DB to initialize. The memory store is **per-project and
lazy**: it's created only the first time a session actually calls
`memory_save_checkpoint`, at a cwd-relative `agent_memory.db` in that project.
Read-only tools and hooks never create it. Do not set `AGENT_MEMORY_DB`
anywhere below — that would force every project onto one shared file, which is
exactly what this design avoids. If a session needs a specific location, pass
`db_path` on the individual `memory_*` tool calls instead.

Pick an absolute path for the package, e.g. `/Users/you/agent-memory`. Everywhere
below, replace `REPLACE_WITH_ABS_PATH` with the parent of that `agent-memory`
folder. `python3` must be on PATH for the hooks; use a full interpreter path if not.

---

## Claude Code

1. **MCP server** — copy `claude-code/.mcp.json` to your project root (or merge
   into an existing one), and fix the one path. Or instead run:
   ```bash
   claude mcp add agent-memory python3 REPLACE_WITH_ABS_PATH/agent-memory/core/mcp_server.py
   ```
2. **Skill** — copy the folder `skill/agent-memory/` to
   `.claude/skills/agent-memory/` (project) or `~/.claude/skills/agent-memory/`
   (all projects).
3. **Hooks** — merge `claude-code/settings.json` into `.claude/settings.json`
   (project) or `~/.claude/settings.json`, fixing the three paths. These wire:
   - `SessionStart` → records the session sentinel
   - `UserPromptSubmit` → injects `<related_prior_tasks>` (forced opening query,
     always runs; no-op and creates nothing if this project has no memory yet)
   - `Stop` → reminds to seal, but only if some prompt this session showed
     memory intent (continue/resume/checkpoint/之前/記得/etc.) **and** nothing
     was checkpointed yet (fires once)
4. **Always-on rules** — copy `claude-code/CLAUDE.md` into your project `CLAUDE.md`
   (or append its contents).
5. Restart Claude Code. Verify: `/mcp` lists `agent-memory`; type a task and the
   model should see prior tasks (once any exist in this project); say something
   like "continue this later" and finish without sealing — the Stop hook nudges.

---

## Codex CLI

1. **MCP server + hooks** — open `codex/config.toml.snippet`, fix the paths,
   and merge the `[mcp_servers.agent-memory]` and `[[hooks...]]` blocks into
   `~/.codex/config.toml` (or `<project>/.codex/config.toml`, which loads only
   when the project is trusted).
2. **Skill** — copy the folder `skill/agent-memory/` to
   `<project>/.agents/skills/agent-memory/` or `~/.codex/skills/agent-memory/`.
3. **Always-on rules** — copy `codex/AGENTS.md` into your project `AGENTS.md`
   (or append its contents).
4. **Hooks (deterministic layer)** — the snippet's event names/nested-table
   syntax were verified against the Codex *Hooks* doc
   (developers.openai.com/codex/hooks); re-verify if Codex has since changed
   them. Each hook wraps the same `mem_cli.py` commands (`find`,
   `session-start`, `seal-reminder`) via `codex/hooks/*.py`. If Codex hooks
   ever can't inject context / block a turn the way you need, the MCP tools +
   skill + AGENTS.md still give the full workflow — you just lose the
   *guarantee*, and the opening query + seal become advisory.
5. Restart Codex. Verify: `/mcp` lists the server; `/skills` (or `$`) shows
   `agent-memory`.

---

## What's deterministic vs advisory

| Step | Claude Code | Codex |
|------|-------------|-------|
| In-session tools (find / detail / artifact / save / link) | MCP — works | MCP — works |
| Protocol (when/how to use them) | skill + CLAUDE.md — advisory | skill + AGENTS.md — advisory |
| Opening query injection (always runs, every prompt) | UserPromptSubmit hook — **deterministic** | hook (verify) or advisory |
| Seal-on-handoff reminder (only if session showed memory intent) | Stop hook — **deterministic** (once/session) | hook (verify) or advisory |

The MCP server and skill are fully portable and identical across both. The hooks
are the only tool-specific part, and the only place the determinism guarantee lives.

## Notes
- **No global DB, no `AGENT_MEMORY_DB`.** Each project gets its own
  `agent_memory.db`, created lazily on first save. Don't pin a shared path in
  any config — that reintroduces cross-project bleed and stray files wherever
  a CLI happens to launch from. Need a one-off different location? Pass
  `db_path` on the specific `memory_*` tool call, not a global env var.
- `AGENT_MEMORY_COMPRESS_AT` (default 12) sets when `save_checkpoint` reports
  `compressed: true`. The actual merge needs a model call — see `mem_cli compress`
  to list candidates, then call `memory.apply_compression(...)` from your own script.
- Sub-agents: each gets its own task_id and seals its own checkpoint; the next
  agent's opening query surfaces it (within the same project). No extra wiring needed.
