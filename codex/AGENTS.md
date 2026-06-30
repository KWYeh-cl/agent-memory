# Memory protocol (always on)

This project uses a persistent task-memory store via the `agent-memory` MCP
server (`memory_*` tools) and the `agent-memory` skill.

- Before non-trivial work: reuse prior tasks. If a `<related_prior_tasks>` block
  is present, load relevant ones with `memory_get_task_detail`; otherwise call
  `memory_find_related_tasks` yourself when the task resembles past work.
- When handing off or finishing: seal the work with `memory_save_checkpoint`
  (rolling summary, outcome, decisions + reasons, open items, large outputs as
  artifacts). Drop trial-and-error.
- Prefer summaries and pointers over full content; load artifacts only on demand.

See the `agent-memory` skill for the full protocol.
