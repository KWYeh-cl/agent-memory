# Install

## Quick start (one command)

Clone the repo, then:

```bash
./install.sh            # Claude Code, user-global (~/.claude)
./install.sh --codex    # also wire Codex (~/.codex)
./install.sh --project .   # project scope: ./.claude (+ ./.codex) instead of home
```

It installs deps and wires the **MCP server + hooks + skill + always-on rules**
in one shot, resolving every path from this repo — no placeholders to fill.
Idempotent (re-run to update in place; existing `settings.json`/`CLAUDE.md`
content is preserved and backed up to `.bak`). It initializes the single root
store at `agent-memory/agent_memory.db` and imports known legacy stores. Under
the hood it's `python3 core/install.py`; run that directly to skip the pip step.
Restart your CLI and verify with `/mcp`.

The manual, per-tool steps below are a fallback if you want to wire things by
hand or understand exactly what the installer touches.

---

Same core for both tools. You install three things: the **MCP server** (in-session
tools), the **skill** (the protocol), and the **hooks** (the deterministic
opening-query + seal). Only the wiring differs per tool.

## 0. One-time core setup

```bash
cd agent-memory/core
python3 -m pip install -r requirements.txt        # mcp, pydantic
```

That's it. The memory store is **single-root**: normal reads and writes use
`ROOT/agent_memory.db`, where `ROOT` is the installed `agent-memory` folder.
`AGENT_MEMORY_ROOT` points wrappers at that same root. `AGENT_MEMORY_DB` and
per-tool `db_path` are explicit migration/admin overrides, not normal task
routing.

Pick an absolute path for the package, e.g. `/Users/you/agent-memory`. Everywhere
below, replace `REPLACE_WITH_ABS_PATH` with the parent of that `agent-memory`
folder. `python3` must be on PATH for the hooks; use a full interpreter path if not.

---

## Claude Code

1. **MCP server** — copy `claude-code/.mcp.json` to your project root (or merge
   into an existing one), fix the paths, and set `AGENT_MEMORY_ROOT` to the
   installed `agent-memory` folder. Or instead run:
   ```bash
   ./install.sh
   ```
2. **Skill** — copy the folder `skill/agent-memory/` to
   `.claude/skills/agent-memory/` (project) or `~/.claude/skills/agent-memory/`
   (all projects).
3. **Hooks** — merge `claude-code/settings.json` into `.claude/settings.json`
   (project) or `~/.claude/settings.json`, fixing the three paths. These wire:
   - `SessionStart` → records the session sentinel
   - `UserPromptSubmit` → injects `<related_prior_tasks>`, but only when the
     current prompt itself shows memory intent (continue/resume/checkpoint/
     之前/記得/etc.) — a plain task prompt never triggers the search, and it
     creates nothing if the root database has no memory yet
   - `Stop` → reminds to seal, but only if some prompt this session showed
     memory intent **and** nothing was checkpointed yet (fires once)
4. **Always-on rules** — copy `claude-code/CLAUDE.md` into your project `CLAUDE.md`
   (or append its contents).
5. Restart Claude Code. Verify: `/mcp` lists `agent-memory`; say something like
   "continue where we left off" and the model should see prior tasks (once any
   exist in the root database — a plain task prompt won't trigger the search); say
   it again and finish without sealing — the Stop hook nudges.

---

## Codex CLI

1. **MCP server + hooks** — open `codex/config.toml.snippet`, fix the paths,
   and merge the `[mcp_servers.agent-memory]` block (including its
   `AGENT_MEMORY_ROOT` env) and `[[hooks...]]` blocks into
   `~/.codex/config.toml` (or `<project>/.codex/config.toml`, which loads only
   when the project is trusted). Do not point Codex at a worktree path. The
   installer writes the same root automatically with `./install.sh --codex`.
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
| Opening query injection (only when the prompt shows memory intent) | UserPromptSubmit hook — **deterministic** | hook (verify) or advisory |
| Seal-on-handoff reminder (only if session showed memory intent) | Stop hook — **deterministic** (once/session) | hook (verify) or advisory |

The MCP server and skill are fully portable and identical across both. The hooks
are the only tool-specific part, and the only place the determinism guarantee lives.

## Notes
- **One root DB.** All installed apps and CLIs should use
  `ROOT/agent_memory.db`. The installer sets `AGENT_MEMORY_ROOT` in managed MCP
  config so working directory and host app do not change where memory lands.
  Use `AGENT_MEMORY_DB` or a per-call `db_path` only for migration/admin work.
- `AGENT_MEMORY_COMPRESS_AT` (default 12) sets when `save_checkpoint` reports
  `compressed: true`. The actual merge needs a model call — see `mem_cli compress`
  to list candidates, then call `memory.apply_compression(...)` from your own script.
- Sub-agents: each gets its own task_id and seals its own checkpoint; the next
  agent's opening query can surface it from the shared root store. No extra
  wiring is needed.
