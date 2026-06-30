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
3. **One DB, one path.** Every entry point (MCP server `env`, all hooks) must
   point `AGENT_MEMORY_DB` at the *same* absolute file. If they diverge, tools and
   hooks record to different stores and nothing lines up.
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
test -f ROOT/agent_memory.db || python3 mem_cli.py init
```

The DB defaults to the current directory. To keep it at `ROOT/agent_memory.db`,
set `AGENT_MEMORY_DB=ROOT/agent_memory.db` when running, and use that same path
in every config below.

**Check:** `python3 mem_cli.py find "setup smoke test"` runs without error
(prints nothing on an empty DB — that's correct).

---

## Phase B — Claude Code (only if selected)

For each file, show the diff and confirm before writing.

1. **Register the MCP server** (preferred over hand-editing `.mcp.json`):
   ```bash
   claude mcp add agent-memory python3 ROOT/core/mcp_server.py
   ```
   Then set its DB env so it matches Phase A. If `claude mcp add` can't set env,
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
   project `.codex/config.toml`. Codex loads project config only when the project
   is trusted — tell the user if it isn't.

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
2. **Opening query injects (Claude Code):** start a task; confirm a
   `<related_prior_tasks>` block appears (empty DB → no block, which is fine).
   Also confirm by hand:
   ```bash
   AGENT_MEMORY_DB=ROOT/agent_memory.db python3 ROOT/core/mem_cli.py find "test"
   ```
3. **Seal reminder fires (Claude Code):** run a trivial task and end the turn
   without calling `memory_save_checkpoint`; the Stop hook should surface a
   reminder once. (It fires at most once per session by design.)
4. **Round-trip:** ask the model to save a checkpoint for a dummy task, then in a
   fresh session ask about the same topic; confirm the prior task surfaces and its
   detail loads via `memory_get_task_detail`.

Report which checks passed. If 2 or 3 didn't fire, the hooks aren't wired —
re-check the paths in `settings.json` and that `python3` resolves.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/mcp` doesn't list the server | wrong path / not restarted | fix abs path in `.mcp.json` or re-run `claude mcp add`; restart |
| Tools listed but every call errors | DB path mismatch / missing deps | ensure one `AGENT_MEMORY_DB`; `pip install -r core/requirements.txt` |
| Opening query never injects | prompt hook not firing | check `UserPromptSubmit` entry + that the hook is executable + `python3` on PATH |
| Seal reminder never fires | Stop hook path wrong, or already fired this session | check `Stop` entry; reminder is one-shot per session by design |
| Skill never triggers | description didn't match | it's advisory; the hooks/MCP still work — invoke `/agent-memory` explicitly if needed |

## Do NOT
- Do not enable Codex hooks with unverified event names.
- Do not point hooks and the MCP server at different DB files.
- Do not overwrite existing `settings.json` / `config.toml` / `CLAUDE.md` / the DB.
- Do not add any credentials or tokens to these files.
