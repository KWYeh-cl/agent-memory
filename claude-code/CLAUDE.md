# Memory protocol (always on)

This project uses a persistent task-memory store via the `agent-memory` MCP
server (`memory_*` tools) and the `agent-memory` skill. The store is shared by
VibeFlow across all tasks, projects, and worktrees. VibeFlow
launches Claude with an inline `--mcp-config` for its built-in server and passes
`--db <VibeFlow User Data>/agent_memory.db` (for example,
`/Users/you/Library/Application Support/vibeflow/agent_memory.db`). Nothing is
written until the first `memory_save_checkpoint`; read-only tools return empty
results (no `<related_prior_tasks>` block) until then and never create a file.
Every `memory_*` tool accepts optional `db_path` only for an explicit override.

- Before non-trivial work: reuse prior tasks. A `<related_prior_tasks>` block is
  injected automatically only when the current prompt itself shows memory
  intent (continue/resume/checkpoint/記得/之前/etc.) — not on every prompt. If
  it appears and looks relevant, load detail with `memory_get_task_detail`. If
  the task plausibly resembles past work but the prompt didn't trigger the
  hook, call `memory_find_related_tasks` yourself.
- When handing off or finishing: seal the work with `memory_save_checkpoint`
  (rolling summary, outcome, decisions + reasons, open items, large outputs as
  artifacts). Drop trial-and-error.
- The Stop hook auto-enforces sealing: if nothing was saved this session, it blocks once and instructs the model to call `memory_save_checkpoint` before finishing. Comply unless no substantive task work happened (pure Q&A, trivial one-liners) — then finish without saving.
- Prefer summaries and pointers over full content; load artifacts only on demand.

See the `agent-memory` skill for the full protocol.
