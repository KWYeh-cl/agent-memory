"""
mcp_server.py — the in-session tool surface.

Exposes the memory store as MCP tools over stdio. Both Claude Code and Codex
speak MCP, so this single server works in either CLI unchanged; only the
registration syntax differs (see ../claude-code and ../codex).

These tools are what the agent calls *during* a task, by its own judgment
(find prior work, load detail/artifact, seal a checkpoint, link tasks). The
two non-negotiable steps (opening query, handoff seal) are additionally driven
by hooks via mem_cli.py, so they don't depend on the model remembering.

Run:  python mcp_server.py     (stdio transport)
Requires:  pip install mcp     (and this file next to memory.py)
"""

from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

import memory

mcp = FastMCP("agent_memory_mcp")
memory.init_db()  # idempotent; creates the db/tables on first run


# ---- input models ----------------------------------------------------------
class FindInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field("", description="Free-text describing the task to match against prior work.")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tag filters, e.g. ['auth','migration'].")
    limit: int = Field(5, ge=1, le=20)


class TaskIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    task_id: str = Field(..., min_length=1)


class ArtifactInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    artifact_id: str = Field(..., min_length=1)


class Decision(BaseModel):
    choice: str
    reason: str = ""


class Artifact(BaseModel):
    description: str = ""
    content: str = ""


class SaveInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    task_id: str = Field(..., description="Stable id for this task across sessions/agents.")
    title: str
    summary: str = Field(..., description="One-line current state of the WHOLE task (rewritten each time).")
    outcome: str = Field(..., description="What THIS stage achieved.")
    decisions: Optional[List[Decision]] = Field(default_factory=list, description="Choices + why. Keep these; drop trial-and-error.")
    open_items: Optional[List[str]] = Field(default_factory=list)
    artifacts: Optional[List[Artifact]] = Field(default_factory=list, description="Large outputs stored out of line, not inline in outcome.")
    tags: Optional[List[str]] = Field(default_factory=list)
    status: str = Field("in_progress", description="in_progress | done | archived")


class LinkInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    from_task: str
    to_task: str
    relation: str = Field(..., description="depends_on | supersedes | derived_from | blocks | relates_to")
    note: str = ""


# ---- tools -----------------------------------------------------------------
@mcp.tool(
    name="memory_find_related_tasks",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
def memory_find_related_tasks(params: FindInput) -> dict:
    """Search prior tasks for relevant past work BEFORE starting. Returns light
    records (title, one-line summary, tags) only — never checkpoint or document
    bodies. Call at the start of a task to check for similar prior work."""
    return {"results": memory.find_related_tasks(params.query, params.tags, params.limit)}


@mcp.tool(
    name="memory_get_task_detail",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
def memory_get_task_detail(params: TaskIdInput) -> dict:
    """Load a prior task's rolling summary, all checkpoints (outcomes, decisions,
    open items) and artifact POINTERS (id + description only). Call only after
    find_related_tasks surfaces a task that looks relevant."""
    detail = memory.get_task_detail(params.task_id)
    return detail or {"error": f"no task {params.task_id}"}


@mcp.tool(
    name="memory_get_artifact",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
def memory_get_artifact(params: ArtifactInput) -> dict:
    """Load the FULL body of one large artifact by id. This is the only path that
    pulls heavy content into context, so call it only when a specific artifact
    (seen as a pointer in get_task_detail) is actually needed for this step."""
    art = memory.get_artifact(params.artifact_id)
    return art or {"error": f"no artifact {params.artifact_id}"}


@mcp.tool(
    name="memory_save_checkpoint",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
)
def memory_save_checkpoint(params: SaveInput) -> dict:
    """Seal a stage of work when handing off to another agent or ending a session.
    Keep decisions + reasons; DROP trial-and-error and superseded attempts. Put
    large outputs in `artifacts` (stored out of line), not inline in `outcome`.
    Returns {task_id, checkpoint_id, seq, compressed}; if compressed is true the
    task has grown long and old checkpoints should be merged (see mem_cli compress)."""
    return memory.save_checkpoint(
        task_id=params.task_id, title=params.title, summary=params.summary,
        outcome=params.outcome,
        decisions=[d.model_dump() for d in (params.decisions or [])],
        open_items=params.open_items or [],
        artifacts=[a.model_dump() for a in (params.artifacts or [])],
        tags=params.tags or [], status=params.status,
    )


@mcp.tool(
    name="memory_link_tasks",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
)
def memory_link_tasks(params: LinkInput) -> dict:
    """Record a STABLE relationship between two tasks (depends_on / supersedes /
    derived_from / blocks). Do NOT use for mere topical similarity — that is found
    automatically by find_related_tasks."""
    return memory.link_tasks(params.from_task, params.to_task, params.relation, params.note)


if __name__ == "__main__":
    mcp.run()  # stdio
