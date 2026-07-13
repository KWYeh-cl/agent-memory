# Install

## Quick start (one command)

Clone the repo, then:

```bash
./install.sh            # Claude Code, user-global (~/.claude)
./install.sh --codex    # also wire Codex (~/.codex)
./install.sh --project .   # project scope: ./.claude (+ ./.codex) instead of home
./install.sh --codex --db-path "$HOME/Library/Application Support/vibeflow/agent_memory.db"
```

It installs deps and wires the **MCP server + hooks + skill + always-on rules**
in one shot, resolving every path from this repo — no placeholders to fill.
Idempotent (re-run to update in place; existing `settings.json`/`CLAUDE.md`
content is preserved and backed up to `.bak`). It creates **no** DB — VibeFlow's
single User Data store is lazy and is created on its first checkpoint. Under the
hood it's `python3 core/install.py`; run that directly to skip the pip step.
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

That's it — there's no DB to initialize. VibeFlow uses one **shared, lazy**
database for every task, project, and worktree:
`<VibeFlow User Data>/agent_memory.db` (for example,
`/Users/you/Library/Application Support/vibeflow/agent_memory.db`). It is
created only when a session first calls `memory_save_checkpoint`; read-only
tools and hooks never create it. Keep `db_path` for an explicit per-call
override, not routine configuration.

`--db-path` defaults to the packaged macOS VibeFlow User Data location,
`~/Library/Application Support/vibeflow/agent_memory.db`. Development builds
use `~/Library/Application Support/vibeflow (development)/agent_memory.db`;
pass that exact path with `--db-path` when wiring either CLI to a development
VibeFlow session.

Pick an absolute path for the package, e.g. `/Users/you/agent-memory`. Everywhere
below, replace `REPLACE_WITH_ABS_PATH` with the parent of that `agent-memory`
folder. `python3` must be on PATH for the hooks; use a full interpreter path if not.

---

## Claude Code

1. **MCP server** — inside VibeFlow, do not add a persistent Claude MCP setting:
   VibeFlow injects its built-in server and `--db <VibeFlow User Data>/agent_memory.db`
   every time it launches Claude. For standalone Claude Code, copy
   `claude-code/.mcp.json` to your project root (or merge into an existing one),
   fix the paths (including the User Data placeholder), and configure the same
   database path for both MCP and hooks. Or instead run:
   ```bash
   ./install.sh --db-path "<VibeFlow User Data>/agent_memory.db"
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
     creates nothing if the shared database has no memory yet
   - `Stop` → reminds to seal, but only if some prompt this session showed
     memory intent **and** nothing was checkpointed yet (fires once)
4. **Always-on rules** — copy `claude-code/CLAUDE.md` into your project `CLAUDE.md`
   (or append its contents).
5. Restart Claude Code. Verify: `/mcp` lists `agent-memory`; say something like
   "continue where we left off" and the model should see prior tasks (once any
   exist in the shared database — a plain task prompt won't trigger the search); say
   it again and finish without sealing — the Stop hook nudges.

---

## Codex CLI

1. **MCP server + hooks** — open `codex/config.toml.snippet`, fix the paths,
   replace `REPLACE_WITH_VIBEFLOW_USER_DATA_PATH` with the current user's
   VibeFlow User Data directory, and merge the `[mcp_servers.agent-memory]`
   (including its `env`) and `[[hooks...]]` blocks into `~/.codex/config.toml`
   (or `<project>/.codex/config.toml`, which loads only when the project is
   trusted). Do not set it to a worktree path: Codex lacks VibeFlow's
   launch-time injection and the Python MCP otherwise falls back to cwd.
   The installer writes the same value automatically: `./install.sh --codex`
   defaults to `~/Library/Application Support/vibeflow/agent_memory.db`; pass
   `--db-path <VibeFlow User Data>/agent_memory.db` when this user's User Data
   directory differs, including VibeFlow development's `vibeflow (development)`
   directory. The installer applies the same path to Codex MCP and hooks.
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
- **One VibeFlow DB.** Set Codex's MCP `AGENT_MEMORY_DB` to
  `<VibeFlow User Data>/agent_memory.db`, never a worktree path. VibeFlow's
  Claude launch already supplies the same path through `--mcp-config`; this is
  an execution-time injection, not a claimed Claude CLI global setting. Need a
  one-off different location? Pass `db_path` on the specific `memory_*` call.
- **User-scope Claude migration.** When a user-scope `agent-memory` server
  exists, the installer backs up `~/.claude.json` to `.bak`, removes only that
  server, then adds it again with the current `--db-path`. It never removes an
  existing server without a recoverable backup; if the add fails, it restores
  the backup and exits non-zero. A missing prior registration is added normally.
- `AGENT_MEMORY_COMPRESS_AT` (default 12) sets when `save_checkpoint` reports
  `compressed: true`. The actual merge needs a model call — see `mem_cli compress`
  to list candidates, then call `memory.apply_compression(...)` from your own script.
- Sub-agents: each gets its own task_id and seals its own checkpoint; the next
  agent's opening query can surface it from the shared VibeFlow store. No extra
  wiring is needed.
