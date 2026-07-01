# agent-memory

## About

`agent-memory` gives coding agents (Claude Code, Codex CLI) a persistent,
per-project **task memory**: a local SQLite store plus MCP tools, hooks, and a
skill that let an agent check "have I done this before?" at the start of a
task and leave a clean handoff note when it finishes — without the model
having to remember to do either.

## The problem

Coding agents are stateless between sessions and between handoffs to other
agents:

- **Lost context across sessions.** Close the chat, come back tomorrow, and
  the agent has no idea it already tried an approach, hit a specific bug, or
  made a deliberate tradeoff — it re-derives everything from scratch.
- **Expensive re-explaining.** The alternative — pasting the whole prior
  conversation back in — burns tokens on trial-and-error and superseded
  attempts, not just the parts worth keeping.
- **Lossy agent-to-agent handoff.** When one agent (or one session) hands work
  to another, decisions and their *reasons*, and open items, don't reliably
  survive the handoff unless someone manually writes them down.
- **"Remembering to remember" isn't reliable.** If saving progress depends on
  the model happening to think of it, it won't happen consistently.

`agent-memory` addresses this with a store that's queried automatically at the
start of every task and a lightweight nudge to save at the end — so continuity
doesn't depend on the model's memory of its own instructions.

## Core concepts

**Three layers**, each doing one job:

- **Judgment** (advisory) — `skill/agent-memory/SKILL.md` +
  `CLAUDE.md`/`AGENTS.md`. Tells the model *when* to reuse prior detail, what
  belongs in a checkpoint summary, and when to link tasks. The model can
  ignore this; nothing breaks if it does.
- **Correctness** (schema-enforced) — `core/memory.py` + `core/schema.sql`,
  exposed as MCP tools by `core/mcp_server.py`. The *only* way memory is
  written. The model chooses *when* to call these tools; it can never write a
  malformed record, because the shape is enforced in code, not by the model's
  discipline.
- **Guarantee** (deterministic) — hooks calling `core/mem_cli.py`. The opening
  query runs from a hook on every prompt, not from the model remembering to
  ask. A prompt is a suggestion; a hook always runs.

**Per-project, lazily created.** There is no global, shared database. The
store lives at a cwd-relative `agent_memory.db` (one per project) and is only
ever created the first time a session actually calls `memory_save_checkpoint`
— read-only lookups never create a file, and nothing is written anywhere until
a session decides there's something worth keeping. Every MCP tool also
accepts an optional `db_path` if a session needs to target a specific file
explicitly.

**Token-lean by construction.** `memory_find_related_tasks` returns only
light fields (title, one-line summary, tags) — never checkpoint or artifact
bodies. `memory_get_task_detail` adds checkpoints and artifact *pointers*
(id + description), still not bodies. Only `memory_get_artifact`, called by id
for one specific artifact, ever pulls a heavy content blob into context.

**Rows, not tables-per-task.** Tasks, checkpoints, and links are rows in fixed
tables — the schema doesn't grow with the number of tasks. `task_links` is a
plain edge table for *stable* relationships (depends_on / supersedes /
derived_from / blocks); mere topical similarity is computed at query time via
FTS, not stored as an edge.

## Trigger flow

What actually fires, and when — this is deterministic infrastructure, not the
model's own initiative, except where noted:

1. **Every prompt → automatic search, always.** A `UserPromptSubmit` hook
   calls `memory_find_related_tasks` with the prompt text on *every* turn, no
   keyword needed. If the project has no memory yet, or nothing overlaps, this
   is silent and creates nothing. If something does overlap, a
   `<related_prior_tasks>` block is injected into context automatically.
   Matching ORs the prompt's tokens against title/summary, so a full sentence
   still matches on partial overlap — it doesn't require every word in the
   prompt to appear in a stored task.
2. **During the task → the model's own judgment.** If a surfaced task looks
   relevant, the model calls `memory_get_task_detail` (and `memory_get_artifact`
   only if a specific pointer is actually needed) to pull in more detail —
   this step is advisory, driven by the judgment layer.
3. **Finishing / handing off → the model decides whether to save.** Per the
   always-on protocol, the model calls `memory_save_checkpoint` when it judges
   the work non-trivial enough to be worth remembering. This is the *only*
   action that ever creates or writes to the store (lazily, at first use).
4. **Safety net → a keyword-gated reminder, not a query.** A `Stop` hook checks:
   did *any* prompt this session mention wanting memory (continue, resume,
   checkpoint, hand off, 之前, 記得, 接續, etc.) **and** nothing got saved?
   If so, it reminds the model to seal the work — once per session, and only
   for sessions that showed that intent. A one-off "fix this typo" session is
   never nagged.

```mermaid
sequenceDiagram
    participant U as You
    participant Hk as Hooks (guarantee)
    participant Ag as Agent (judgment)
    participant Mc as MCP tools (correctness)
    participant DB as SQLite store (per project, lazy)

    U->>Ag: start a task (any prompt)
    Hk->>DB: find_related_tasks (always runs; no-op if db absent)
    Hk-->>Ag: inject <related_prior_tasks> if anything overlaps
    Ag->>Mc: get_task_detail / get_artifact (only if relevant)
    Mc->>DB: read summary + pointers; bodies on demand
    Note over Ag: do the work, reuse prior decisions
    Ag->>Mc: save_checkpoint (model's own judgment, on handoff/finish)
    Mc->>DB: lazily init schema if first write, then append checkpoint
    Hk->>Hk: did any prompt this session mention memory intent?
    Hk-->>Ag: only if yes AND nothing was saved: remind to seal (once)
```

## How to use it

Day to day, you don't call anything — you just work, and the trigger flow
above runs underneath:

- Start a task normally. If related prior work exists in *this* project,
  it's already in context before you ask.
- Finish or hand off normally. If the work was substantive, the agent should
  seal it on its own judgment; if it forgot and the conversation showed intent
  to continue later, it gets one reminder.
- You can also invoke the protocol explicitly — trigger words like
  *continue*, *hand off*, *pick up where we left off*, *checkpoint*, *resume*
  route to the `agent-memory` skill, which explains the tools in more detail.

### Setup

**Recommended — let an agent do it:** open this folder in Claude Code or
Codex and say

> "set up agent-memory by following SETUP_RUNBOOK.md"

The runbook makes the agent gather your paths, install the shared `core/`
scripts and skill globally (not the database — that stays per-project and
lazy), wire the MCP server + hooks, and verify each step — pausing for your
confirmation before touching any config file.

**Manual:** see `INSTALL.md` for the per-tool steps. `install.sh` also exists
for a quick core-only setup — installs deps and generates ready-to-use config
templates into `dist/` (no `AGENT_MEMORY_DB` pinned; the per-project, lazy
design above is what you get).

## Data model

```
tasks          id, title, summary (rolling one-liner), status, timestamps
checkpoints    task_id, seq, outcome, decisions (json), open_items (json)
artifacts      checkpoint_id, description, content (heavy, loaded on demand)
task_links     from_task, to_task, relation, note      (stable edges only)
tasks_fts      FTS5 index over title + summary
```

## Layout

```
core/        schema.sql, memory.py, mcp_server.py, mem_cli.py, requirements.txt
skill/       agent-memory/SKILL.md          (portable to both tools)
claude-code/ .mcp.json, settings.json, CLAUDE.md, hooks/
codex/       config.toml.snippet, AGENTS.md, hooks/
install.sh           one-shot, auto-pathing installer (deps + generated configs)
SETUP_RUNBOOK.md     agent-executable setup guide (recommended)
INSTALL.md           manual, per-tool install steps
```

## Requirements

Python 3.10+, `pip install -r core/requirements.txt` (mcp, pydantic), and Claude
Code and/or Codex CLI.

## License

MIT — see `LICENSE` (fill in your name/year).
