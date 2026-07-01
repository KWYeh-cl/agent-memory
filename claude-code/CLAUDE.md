# Memory protocol (always on)

This project uses a persistent task-memory store via the `agent-memory` MCP
server (`memory_*` tools) and the `agent-memory` skill. The store is per-project
and created lazily — nothing is written anywhere until the first
`memory_save_checkpoint` call; read-only tools return empty results (no
`<related_prior_tasks>` block) until then, and never create a file. Defaults to
a cwd-relative `agent_memory.db`; every `memory_*` tool also accepts an optional
`db_path` to target a specific file explicitly instead.

- Before non-trivial work: reuse prior tasks. A `<related_prior_tasks>` block is
  injected automatically; if relevant, load it with `memory_get_task_detail`.
- When handing off or finishing: seal the work with `memory_save_checkpoint`
  (rolling summary, outcome, decisions + reasons, open items, large outputs as
  artifacts). Drop trial-and-error.
- The Stop-hook seal reminder only fires if some prompt in this session showed memory intent (continue/resume/checkpoint/記得/之前/etc.) AND nothing was saved yet; most sessions are never nagged.
- Prefer summaries and pointers over full content; load artifacts only on demand.

See the `agent-memory` skill for the full protocol.
