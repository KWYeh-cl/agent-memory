-- Agent memory system schema (SQLite)
-- Design rule: checkpoints/tasks/links are ROWS in fixed tables,
-- never one-table-per-task. Growth is carried by rows, not by table count.

-- Task index. Replaces the old memory.json "directory" role.
-- This is the only table scanned at task start, and only its light
-- columns are selected (never `content`-sized data lives here).
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    summary     TEXT,                      -- rolling one-line current state
    status      TEXT DEFAULT 'in_progress',-- in_progress / done / archived
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Tags normalized into a relation (so we can query precisely, not LIKE-match).
CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS task_tags (
    task_id  TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, tag_id)
);

-- Each checkpoint is a ROW, not a table.
CREATE TABLE IF NOT EXISTS checkpoints (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,          -- nth checkpoint within the task
    outcome     TEXT,                      -- what was achieved
    decisions   TEXT,                      -- JSON array: [{choice, reason}, ...]
    open_items  TEXT,                      -- JSON array: ["...", ...]
    created_at  TEXT NOT NULL
);

-- Large content lives here. `content` is NEVER pulled in normal queries;
-- only `description` (the light pointer) is read into context by default.
CREATE TABLE IF NOT EXISTS artifacts (
    id            TEXT PRIMARY KEY,
    checkpoint_id TEXT NOT NULL REFERENCES checkpoints(id) ON DELETE CASCADE,
    description   TEXT,                     -- one-line; this is what gets read
    content       TEXT,                     -- heavy body; loaded on demand only
    created_at    TEXT NOT NULL
);

-- Explicit, stable relationships between tasks (an edge table).
-- Similarity ("similar_to") is intentionally NOT stored here — it is
-- computed at query time (FTS / embeddings), because it changes as tasks arrive.
CREATE TABLE IF NOT EXISTS task_links (
    from_task   TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    to_task     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    relation    TEXT NOT NULL,             -- depends_on / supersedes / derived_from / ...
    note        TEXT,                      -- why this link exists
    created_at  TEXT NOT NULL,
    PRIMARY KEY (from_task, to_task, relation)
);

-- Full-text search over the light task fields, for "have I done this before?".
-- Start here; swap/augment with embeddings later without changing the tables above.
-- Standalone FTS5 table (kept in sync manually in save_checkpoint).
CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
    id UNINDEXED,
    title,
    summary
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_task ON checkpoints(task_id, seq);
CREATE INDEX IF NOT EXISTS idx_artifacts_cp     ON artifacts(checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_links_from       ON task_links(from_task);
CREATE INDEX IF NOT EXISTS idx_links_to         ON task_links(to_task);
