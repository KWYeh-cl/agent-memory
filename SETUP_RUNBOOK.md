# SETUP RUNBOOK — for the harness agent

You are an agent setting up the **agent-memory** system for the user. Follow this
runbook top to bottom. It installs a shared core, then wires it into Claude Code
and/or Codex. The user has handed you this whole `agent-memory/` folder.

Success = the MCP server is registered, the skill is discoverable, the hooks are
in place, and the verification in Phase D passes.

---

## Operating rules (do not violate)

1. **Confirm before editing any config or global file.** Before you modify
   `settings.json`, `config.toml`, `CLAUDE.md`, `AGENTS.md`, or register an MCP
   server, show the user the exact change and the exact file path, and wait for a
   clear yes. These are standing-configuration changes.
2. **Never overwrite — merge.** If a target file already exists, back it up
   (`<file>.bak`) and merge the new keys in. Never clobber an existing
   `settings.json`/`config.toml`/`CLAUDE.md`. Never overwrite an existing
   `agent_memory.db` or an existing `skill/agent-memory/`.
3. **One root memory DB.** All installed apps and CLIs must point at
   `ROOT/agent_memory.db`. Managed MCP config should set `AGENT_MEMORY_ROOT`
   to `ROOT` so the working directory and host app cannot create divergent
   stores. `AGENT_MEMORY_DB` and per-call `db_path` are only for explicit
   migration/admin overrides.
4. **No secrets in any file.** These configs hold paths only.
5. **Idempotent.** Re-running this runbook must not duplicate hooks, re-init the
   DB, or double-register the server. Check before you add.
6. **Don't fabricate Codex hook syntax.** The Codex hook event names are marked
   `verify` in the snippet; confirm them against the current Codex Hooks doc
   before enabling, or skip Phase C's hook step and tell the user it's advisory.
7. **Verify, don't assume.** After each phase, run the stated check and report the
   actual output. If a check fails, stop and report — don't push forward.

---

## Phase 0 — Gather inputs (ask the user)

Ask, in one message:
1. The **absolute path** where this `agent-memory/` folder lives
   (e.g. `/Users/alex/agent-memory`). Call its value `ROOT`. The replacement for
   `REPLACE_WITH_ABS_PATH` in the shipped configs is the **parent** of `ROOT`.
2. Which CLI(s) to wire: **Claude Code**, **Codex**, or **both**.
3. **Scope**: this project only, or all projects (user-global)?
   - Claude Code: project = `.claude/` in the repo; global = `~/.claude/`.
   - Codex: project = `<repo>/.codex/` + `.agents/skills/`; global = `~/.codex/`.
Resolve the Python interpreter: run `which python3`. If hooks may run in an
environment without `python3` on PATH, use the absolute interpreter path in all
hook commands.

---

## Phase A — Core setup (shared; do once)

```bash
cd ROOT/core
python3 -m pip install -r requirements.txt
```

The installer initializes `ROOT/agent_memory.db` and imports known legacy
stores (for example older Codex and VibeFlow locations). Read-only hooks and
tools must never create a cwd-relative DB; all default reads/writes resolve to
the root store. Every `memory_*` MCP tool also accepts an explicit `db_path`,
but that is reserved for migration/admin overrides.

**Check:** `python3 mem_cli.py find "setup smoke test"` runs without error. It
may print prior work from the unified store. From a throwaway project cwd,
`ls agent_memory.db` should still fail, while `ls ROOT/agent_memory.db` should
show the single root DB.

---

## Phase B — Claude Code (only if selected)

For each file, show the diff and confirm before writing.

1. **Register the MCP server** (preferred over hand-editing `.mcp.json`):
   ```bash
   claude mcp add agent-memory python3 ROOT/core/mcp_server.py
   ```
   Set its env to `AGENT_MEMORY_ROOT=ROOT`. If `claude mcp add` can't set env,
   instead merge `claude-code/.mcp.json` (paths fixed) into the project root
   `.mcp.json`. Check: `claude mcp list` shows `agent-memory`.

2. **Skill:** copy `skill/agent-memory/` to `~/.claude/skills/agent-memory/`
   (global) or `.claude/skills/agent-memory/` (project). Do not overwrite if it
   exists; diff first.

3. **Hooks:** merge the three entries from `claude-code/settings.json` into
   `~/.claude/settings.json` or `.claude/settings.json`. Replace
   `REPLACE_WITH_ABS_PATH` with `ROOT`'s parent so the three hook paths resolve to
   `ROOT/claude-code/hooks/*.py`. If a `hooks` block already exists, append these
   entries — do not replace the block. Back up first.

4. **Always-on rules:** append the contents of `claude-code/CLAUDE.md` to the
   project `CLAUDE.md` (create if absent). Don't duplicate if already present.

**Check (Phase B):** restart Claude Code, then:
- `/mcp` lists `agent-memory`.
- The three hook scripts are executable: `ls -l ROOT/claude-code/hooks/*.py`.

---

## Phase C — Codex (only if selected)

1. **MCP server:** merge the `[mcp_servers.agent-memory]` block from
   `codex/config.toml.snippet` (paths fixed) into `~/.codex/config.toml` or the
   project `.codex/config.toml`. Its env must set `AGENT_MEMORY_ROOT=ROOT`, not
   a worktree path. Codex loads project config only when the project is trusted ?
   tell the user if it isn't. If using the installer instead, run
   `./install.sh --codex`; it writes this root to Codex MCP.

2. **Skill:** copy `skill/agent-memory/` to `.agents/skills/agent-memory/`
   (project) or `~/.codex/skills/agent-memory/` (global). Diff before overwrite.

3. **Always-on rules:** append `codex/AGENTS.md` contents to the project
   `AGENTS.md`.

4. **Hooks (deterministic layer — verify first):** the event names in the snippet
   are placeholders. Before enabling, confirm the real event names/fields against
   the Codex Hooks doc. Each hook calls the same `mem_cli.py` commands
   (`find` / `session-start` / `seal-reminder`). If you cannot confirm the syntax,
   **do not enable the hooks** — install steps 1–3 only, and tell the user the
   opening query and seal are advisory (skill-driven) on Codex until hooks are
   verified.

**Check (Phase C):** restart Codex; `/mcp` lists the server; `/skills` (or `$`)
shows `agent-memory`.

---

## Phase D — End-to-end verification (report results)

1. **Tools reachable:** in the CLI, confirm `memory_find_related_tasks` and
   `memory_save_checkpoint` appear in the tool/`/mcp` listing.
2. **Opening query is gated on memory intent, and creates nothing (Claude
   Code):** the `UserPromptSubmit` hook only calls `find` when the CURRENT
   prompt itself shows memory intent (continue/resume/checkpoint/之前/記得/
   etc.) — a plain task prompt should never trigger it. Confirm both halves:
   ```bash
   cd <some project dir>
   echo '{"session_id":"t1","prompt":"fix this typo"}' \
     | python3 ROOT/claude-code/hooks/on_prompt.py    # prints nothing (no keyword)
   echo '{"session_id":"t2","prompt":"continue where we left off"}' \
     | python3 ROOT/claude-code/hooks/on_prompt.py    # runs find (prints nothing if no prior tasks)
   test -e "ROOT/agent_memory.db"                      # root store exists after install
   ```
3. **Seal reminder is gated on memory intent (Claude Code):** a prompt with no
   memory-intent keywords (e.g. "fix this typo"), ended without calling
   `memory_save_checkpoint`, must produce NO reminder. A prompt that does
   mention intent (e.g. "continue where we left off"), ended the same way,
   must produce the reminder exactly once. (Fires at most once per session by
   design, and must not create a db file if none exists yet.)
4. **Round-trip:** ask the model to save a checkpoint for a dummy task (this
   writes `ROOT/agent_memory.db`), then in a fresh session in any project
   directory ask about the same topic **using a prompt that itself shows memory
   intent** (e.g. "continue the <topic> work from before") — a plain restatement
   of the topic won't trigger the hook. Confirm the prior task surfaces and its
   detail loads via `memory_get_task_detail`. Confirm a different project
   directory sees the same memory store.

Report which checks passed. If 2 or 3 didn't fire, the hooks aren't wired —
re-check the paths in `settings.json` and that `python3` resolves.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/mcp` doesn't list the server | wrong path / not restarted | fix abs path in `.mcp.json` or re-run `claude mcp add`; restart |
| Tools listed but every call errors | missing deps, or a wrapper forced the wrong DB | `pip install -r core/requirements.txt`; confirm `AGENT_MEMORY_ROOT=ROOT` |
| A db file shows up somewhere unexpected | a tool fell back to cwd or a wrapper forced the wrong DB | set `AGENT_MEMORY_ROOT=ROOT` in that MCP config, or remove unintended `AGENT_MEMORY_DB` overrides |
| Opening query never injects | prompt hook not firing | check `UserPromptSubmit` entry + that the hook is executable + `python3` on PATH |
| Seal reminder never fires | Stop hook path wrong, or already fired this session | check `Stop` entry; reminder is one-shot per session by design |
| Skill never triggers | description didn't match | it's advisory; the hooks/MCP still work — invoke `/agent-memory` explicitly if needed |

## Do NOT
- Do not enable Codex hooks with unverified event names.
- Do not let any default install fall back to a cwd-relative or app-private DB.
- Do not overwrite existing `settings.json` / `config.toml` / `CLAUDE.md` / the root DB.
- Do not add any credentials or tokens to these files.
