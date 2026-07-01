---
name: agent-memory
description: >
  Cross-session task memory protocol. Use at the START of any non-trivial task
  (to reuse prior work) and whenever handing off to another agent or ending a
  session (to seal what was done). Trigger words: continue, hand off, pick up
  where we left off, prior work, "have we done this before", checkpoint, resume.
---

# Task Memory Protocol

You share a persistent memory store with other agents and past/future sessions,
exposed as MCP tools (`memory_*`). The goal is to send LESS context, not more:
store summaries + pointers, load detail only on demand.

## Tools
- `memory_find_related_tasks(query, tags)` — search prior work; light records only.
- `memory_get_task_detail(task_id)` — a task's summary, checkpoints, artifact pointers.
- `memory_get_artifact(artifact_id)` — one heavy artifact body. Expensive; use sparingly.
- `memory_save_checkpoint(...)` — seal a stage of work. Nothing is created before this:
  the store is lazily initialized on the first call, per-project.
- `memory_link_tasks(from, to, relation)` — record a stable relationship.

Every tool takes an optional `db_path`. Default is a cwd-relative `agent_memory.db`
(one store per project); pass `db_path` explicitly if you need a different file.

## Starting a task
A prompt-submit hook injects a `<related_prior_tasks>` block, but only when the
current prompt itself shows memory intent (continue, resume, checkpoint, 之前,
記得, etc.) — plain task prompts don't trigger it. If the block is present and
anything looks relevant, call `memory_get_task_detail` on it and reuse its
decisions instead of redoing the work. If no block appears but the task
plausibly resembles past work anyway, call `memory_find_related_tasks`
yourself — don't assume "no block" means "no prior work exists."
Pull a large artifact with `memory_get_artifact` only when its description shows
it's needed for the current step — never bulk-load artifacts.

## Handing off or ending a session
Seal the work with `memory_save_checkpoint`:
- `summary`: rewrite the one-line current state of the whole task.
- `outcome`: what THIS stage achieved.
- `decisions`: choices made and WHY — these stop the next agent re-deciding.
- `open_items`: anything unresolved or passed onward.
- `artifacts`: large outputs (designs, generated docs, long results) go here as
  out-of-line content; never paste large bodies into `outcome`.
- DROP trial-and-error and superseded attempts. Aim for "enough for the next
  agent to take the correct next step", not a full replay.

A stop hook will remind you if you finish without sealing — but seal proactively.
The reminder only fires when this session's prompts showed memory intent
(continue/resume/checkpoint/記得/之前/etc.); it stays silent otherwise, so
don't rely on it for tasks that never mentioned wanting memory.

## Linking
If this task clearly depends_on / supersedes / derived_from a specific prior
task, call `memory_link_tasks` with a short note on why. Do NOT link mere topical
similarity — that's discovered automatically by find.

## If save_checkpoint reports `compressed: true`
The task has many checkpoints. Note it; an out-of-band compression step merges
old ones. Keep your summary tight so growth stays bounded.
