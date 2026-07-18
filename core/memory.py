"""
memory.py — SQLite-backed memory store.

This is LAYER 2 (the part that guarantees correctness). Every operation the
agent can take on memory goes through one of these functions. The schema and
JSON shapes are enforced here, in code, so the model can never write a
malformed memory — it only chooses *when* to call, never *how* it's stored.

Read-cost discipline (this is what actually saves tokens):
  - find_related_tasks() selects only light columns. It never touches
    artifacts.content.
  - get_task_detail() returns checkpoints + artifact *descriptions* (pointers),
    not artifact bodies.
  - get_artifact() is the only path that pulls a heavy content body, and only
    for one explicitly named artifact.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

COMPRESS_THRESHOLD = int(os.environ.get("AGENT_MEMORY_COMPRESS_AT", "12"))

# Resolve bundled files relative to this module so callers work from any cwd
# (the MCP server is launched from the CLI's working dir, not this directory).
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
SCHEMA_PATH = os.path.join(_HERE, "schema.sql")
DB_FILE = "agent_memory.db"


def default_db_path() -> str:
    """Return the single install-root memory store path.

    Normal installs should let every CLI/app use this default. AGENT_MEMORY_DB
    remains an explicit escape hatch for migration/admin work, while
    AGENT_MEMORY_ROOT lets wrapper apps point at the same installed root.
    """
    explicit = os.environ.get("AGENT_MEMORY_DB")
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    root = os.environ.get("AGENT_MEMORY_ROOT") or ROOT
    return os.path.join(os.path.abspath(os.path.expanduser(root)), DB_FILE)


DB_PATH = default_db_path()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str = DB_PATH, schema_path: str = SCHEMA_PATH) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = f.read()
    conn = connect(db_path)
    with conn:
        conn.executescript(schema)
    conn.close()


def _ensure_tags(conn, task_id, tags):
    for name in tags or []:
        name = name.strip().lower()
        if not name:
            continue
        conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
        tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"]
        conn.execute(
            "INSERT OR IGNORE INTO task_tags(task_id, tag_id) VALUES (?, ?)",
            (task_id, tag_id),
        )


# ----------------------------------------------------------------------------
# OPENING QUERY  — called before any task starts (cheap, light columns only)
# ----------------------------------------------------------------------------
def find_related_tasks(query: str = "", tags=None, limit: int = 5, db_path: str = DB_PATH):
    """Return light task records that may be relevant prior work.

    Matches by FTS over title/summary AND/OR by tag overlap. Returns only
    id/title/summary/status/tags — never any checkpoint or artifact body.

    Never creates the db file: nothing has been saved here yet if it's absent.
    """
    if not os.path.exists(db_path):
        return []
    conn = connect(db_path)
    hits = {}

    if query:
        # FTS5 MATCH; OR the tokens so a long natural-language prompt still
        # matches on partial overlap (bare "a b c" would require ALL of
        # a/b/c present, which real prompts almost never satisfy).
        # Falls back to LIKE if the query has no usable tokens.
        tokens = [t.replace('"', '""') for t in query.split() if t.strip()]
        fts_query = " OR ".join(f'"{t}"' for t in tokens) if tokens else query
        try:
            rows = conn.execute(
                """SELECT t.id, t.title, t.summary, t.status
                   FROM tasks_fts f JOIN tasks t ON t.id = f.id
                   WHERE tasks_fts MATCH ? LIMIT ?""",
                (fts_query, limit * 2),
            ).fetchall()
        except sqlite3.OperationalError:
            like = f"%{query}%"
            rows = conn.execute(
                """SELECT id, title, summary, status FROM tasks
                   WHERE title LIKE ? OR summary LIKE ? LIMIT ?""",
                (like, like, limit * 2),
            ).fetchall()
        for r in rows:
            hits[r["id"]] = dict(r)

    if tags:
        placeholders = ",".join("?" * len(tags))
        rows = conn.execute(
            f"""SELECT DISTINCT t.id, t.title, t.summary, t.status
                FROM tasks t
                JOIN task_tags tt ON tt.task_id = t.id
                JOIN tags g ON g.id = tt.tag_id
                WHERE g.name IN ({placeholders})
                LIMIT ?""",
            (*[s.lower() for s in tags], limit * 2),
        ).fetchall()
        for r in rows:
            hits[r["id"]] = dict(r)

    results = list(hits.values())[:limit]
    for r in results:
        tag_rows = conn.execute(
            """SELECT g.name FROM tags g
               JOIN task_tags tt ON tt.tag_id = g.id WHERE tt.task_id = ?""",
            (r["id"],),
        ).fetchall()
        r["tags"] = [t["name"] for t in tag_rows]
    conn.close()
    return results


# ----------------------------------------------------------------------------
# LOAD DETAIL  — called when the agent picks a relevant prior task
# ----------------------------------------------------------------------------
def get_task_detail(task_id: str, db_path: str = DB_PATH):
    """Return the task summary + all checkpoints + artifact POINTERS.

    Artifact bodies are not included — only their id + description, so the
    agent can decide whether any are worth pulling with get_artifact().

    Never creates the db file: nothing has been saved here yet if it's absent.
    """
    if not os.path.exists(db_path):
        return None
    conn = connect(db_path)
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        conn.close()
        return None
    out = dict(task)

    cps = conn.execute(
        "SELECT * FROM checkpoints WHERE task_id = ? ORDER BY seq", (task_id,)
    ).fetchall()
    out["checkpoints"] = []
    for cp in cps:
        cp_d = dict(cp)
        cp_d["decisions"] = json.loads(cp_d.get("decisions") or "[]")
        cp_d["open_items"] = json.loads(cp_d.get("open_items") or "[]")
        arts = conn.execute(
            "SELECT id, description FROM artifacts WHERE checkpoint_id = ?", (cp["id"],)
        ).fetchall()
        cp_d["artifacts"] = [dict(a) for a in arts]   # pointers only
        out["checkpoints"].append(cp_d)

    links = conn.execute(
        "SELECT to_task, relation, note FROM task_links WHERE from_task = ?", (task_id,)
    ).fetchall()
    out["links"] = [dict(l) for l in links]
    conn.close()
    return out


# ----------------------------------------------------------------------------
# LOAD HEAVY CONTENT  — the only path that reads an artifact body
# ----------------------------------------------------------------------------
def get_artifact(artifact_id: str, db_path: str = DB_PATH):
    if not os.path.exists(db_path):
        return None
    conn = connect(db_path)
    row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ----------------------------------------------------------------------------
# WRITE CHECKPOINT  — called at handoff / session end (the seal step)
# ----------------------------------------------------------------------------
def save_checkpoint(
    task_id: str,
    title: str,
    summary: str,
    outcome: str,
    decisions=None,
    open_items=None,
    artifacts=None,
    tags=None,
    status: str = "in_progress",
    db_path: str = DB_PATH,
):
    """Upsert the task, append one checkpoint, store any heavy artifacts.

    `artifacts` is a list of {"description": str, "content": str}. The content
    body is stored once and never re-read unless explicitly requested later.
    Returns {task_id, checkpoint_id, seq, compressed}.

    This is the only place memory gets created: the store at `db_path` is
    lazily initialized here (idempotent) rather than at session/server start,
    so nothing is written until a session actually decides to save one.
    """
    init_db(db_path)
    conn = connect(db_path)
    now = _now()
    with conn:
        existing = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE tasks SET title=?, summary=?, status=?, updated_at=? WHERE id=?",
                (title, summary, status, now, task_id),
            )
        else:
            conn.execute(
                "INSERT INTO tasks(id,title,summary,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (task_id, title, summary, status, now, now),
            )
        # keep FTS in sync
        conn.execute("DELETE FROM tasks_fts WHERE id = ?", (task_id,))
        conn.execute(
            "INSERT INTO tasks_fts(id, title, summary) VALUES (?,?,?)",
            (task_id, title, summary),
        )
        _ensure_tags(conn, task_id, tags)

        seq_row = conn.execute(
            "SELECT COALESCE(MAX(seq),0)+1 AS n FROM checkpoints WHERE task_id=?",
            (task_id,),
        ).fetchone()
        seq = seq_row["n"]
        cp_id = _id("cp")
        conn.execute(
            "INSERT INTO checkpoints(id,task_id,seq,outcome,decisions,open_items,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (cp_id, task_id, seq, outcome,
             json.dumps(decisions or [], ensure_ascii=False),
             json.dumps(open_items or [], ensure_ascii=False), now),
        )
        for art in artifacts or []:
            conn.execute(
                "INSERT INTO artifacts(id,checkpoint_id,description,content,created_at) "
                "VALUES (?,?,?,?,?)",
                (_id("art"), cp_id, art.get("description", ""), art.get("content", ""), now),
            )

    compressed = False
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM checkpoints WHERE task_id=?", (task_id,)
    ).fetchone()["c"]
    conn.close()
    if count >= COMPRESS_THRESHOLD:
        compressed = True  # signal the harness to run compress_task()
    return {"task_id": task_id, "checkpoint_id": cp_id, "seq": seq, "compressed": compressed}


# ----------------------------------------------------------------------------
# EXPLICIT LINK  — stable relationships only (not similarity)
# ----------------------------------------------------------------------------
def link_tasks(from_task: str, to_task: str, relation: str, note: str = "", db_path: str = DB_PATH):
    conn = connect(db_path)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO task_links(from_task,to_task,relation,note,created_at) "
            "VALUES (?,?,?,?,?)",
            (from_task, to_task, relation, note, _now()),
        )
    conn.close()
    return {"from": from_task, "to": to_task, "relation": relation}


def related_links(task_id: str, db_path: str = DB_PATH):
    """One-hop neighbours in both directions. (No graph DB needed for this.)"""
    conn = connect(db_path)
    rows = conn.execute(
        """SELECT from_task, to_task, relation, note FROM task_links
           WHERE from_task = ? OR to_task = ?""",
        (task_id, task_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ----------------------------------------------------------------------------
# COMPRESSION  — second-order squeeze when a task has too many checkpoints
# ----------------------------------------------------------------------------
def get_checkpoints_for_compression(task_id: str, keep_recent: int = 3, db_path: str = DB_PATH):
    """Return the OLD checkpoints (everything except the most recent N) that
    should be merged. The harness sends these to the model to summarize."""
    conn = connect(db_path)
    cps = conn.execute(
        "SELECT * FROM checkpoints WHERE task_id=? ORDER BY seq", (task_id,)
    ).fetchall()
    conn.close()
    old = [dict(c) for c in cps[:-keep_recent]] if len(cps) > keep_recent else []
    for c in old:
        c["decisions"] = json.loads(c.get("decisions") or "[]")
        c["open_items"] = json.loads(c.get("open_items") or "[]")
    return old


def apply_compression(task_id: str, merged_outcome: str, merged_decisions,
                      merged_open_items, keep_recent: int = 3, db_path: str = DB_PATH):
    """Replace old checkpoints with a single merged one. Recent N are untouched.
    Artifacts of merged checkpoints are re-parented to the merged checkpoint so
    no heavy content is lost."""
    conn = connect(db_path)
    now = _now()
    with conn:
        cps = conn.execute(
            "SELECT id FROM checkpoints WHERE task_id=? ORDER BY seq", (task_id,)
        ).fetchall()
        if len(cps) <= keep_recent:
            conn.close()
            return {"task_id": task_id, "merged": 0}
        old_ids = [c["id"] for c in cps[:-keep_recent]]

        merged_id = _id("cp")
        conn.execute(
            "INSERT INTO checkpoints(id,task_id,seq,outcome,decisions,open_items,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (merged_id, task_id, 0, merged_outcome,
             json.dumps(merged_decisions or [], ensure_ascii=False),
             json.dumps(merged_open_items or [], ensure_ascii=False), now),
        )
        ph = ",".join("?" * len(old_ids))
        conn.execute(
            f"UPDATE artifacts SET checkpoint_id=? WHERE checkpoint_id IN ({ph})",
            (merged_id, *old_ids),
        )
        conn.execute(f"DELETE FROM checkpoints WHERE id IN ({ph})", old_ids)
    conn.close()
    return {"task_id": task_id, "merged": len(old_ids), "merged_checkpoint": merged_id}
