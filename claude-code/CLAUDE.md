# Memory protocol (always on)

This project uses a persistent task-memory store via the `agent-memory` MCP
server (`memory_*` tools) and the `agent-memory` skill. All installed apps and
CLIs use the same single store at the agent-memory install root
(`agent_memory.db`). Every `memory_*` tool accepts an optional `db_path` for
migration/admin overrides, but normal task work should omit it.

- Before non-trivial work: reuse prior tasks. A `<related_prior_tasks>` block is
  injected automatically only when the current prompt itself shows memory
  intent (continue/resume/checkpoint/記得/之前/etc.) — not on every prompt. If
  it appears and looks relevant, load detail with `memory_get_task_detail`. If
  the task plausibly resembles past work but the prompt didn't trigger the
  hook, call `memory_find_related_tasks` yourself.
- When handing off or finishing: seal the work with `memory_save_checkpoint`
  (rolling summary, outcome, decisions + reasons, open items, large outputs as
  artifacts). Drop trial-and-error.
- The Stop-hook seal reminder only fires if some prompt in this session showed memory intent (continue/resume/checkpoint/記得/之前/etc.) AND nothing was saved yet; most sessions are never nagged.
- Prefer summaries and pointers over full content; load artifacts only on demand.

See the `agent-memory` skill for the full protocol.
