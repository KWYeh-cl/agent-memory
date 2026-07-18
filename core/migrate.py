"""Utilities for merging legacy agent-memory SQLite stores into one root DB."""

from __future__ import annotations

import os
import sqlite3
from typing import Iterable

import memory


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.abspath(a) == os.path.abspath(b)


def legacy_db_candidates() -> list[str]:
    """Common locations used by older installs/apps before root unification."""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".codex", memory.DB_FILE),
        os.path.join(home, ".claude", memory.DB_FILE),
        os.path.join(home, "AppData", "Roaming", "vibeflow", memory.DB_FILE),
        os.path.join(home, "Library", "Application Support", "vibeflow", memory.DB_FILE),
        os.path.join(home, ".config", "vibeflow", memory.DB_FILE),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for path in candidates:
        norm = os.path.abspath(os.path.expanduser(path))
        key = os.path.normcase(norm)
        if key not in seen:
            seen.add(key)
            out.append(norm)
    return out


def merge_database(source_db: str, target_db: str = memory.DB_PATH) -> dict[str, int | str | bool]:
    """Merge one source DB into target DB without overwriting checkpoint bodies.

    Tasks with the same id keep the newer rolling summary/status by updated_at.
    Checkpoints, artifacts, tags, and links are inserted when their primary keys
    are not already present. FTS is rebuilt for all merged tasks.
    """
    source = os.path.abspath(os.path.expanduser(source_db))
    target = os.path.abspath(os.path.expanduser(target_db))
    result: dict[str, int | str | bool] = {
        "source": source,
        "target": target,
        "skipped": False,
        "tasks": 0,
        "checkpoints": 0,
        "artifacts": 0,
        "links": 0,
    }
    if not os.path.exists(source) or _same_file(source, target):
        result["skipped"] = True
        return result

    memory.init_db(target)
    conn = sqlite3.connect(target)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("ATTACH DATABASE ? AS src", (source,))
        with conn:
            before = conn.total_changes
            conn.execute(
                """
                INSERT INTO tasks(id, title, summary, status, created_at, updated_at)
                SELECT id, title, summary, status, created_at, updated_at FROM src.tasks
                WHERE true
                ON CONFLICT(id) DO UPDATE SET
                  title = CASE
                    WHEN excluded.updated_at > tasks.updated_at THEN excluded.title
                    ELSE tasks.title
                  END,
                  summary = CASE
                    WHEN excluded.updated_at > tasks.updated_at THEN excluded.summary
                    ELSE tasks.summary
                  END,
                  status = CASE
                    WHEN excluded.updated_at > tasks.updated_at THEN excluded.status
                    ELSE tasks.status
                  END,
                  updated_at = CASE
                    WHEN excluded.updated_at > tasks.updated_at THEN excluded.updated_at
                    ELSE tasks.updated_at
                  END
                """
            )
            result["tasks"] = conn.total_changes - before

            conn.execute(
                "INSERT OR IGNORE INTO tags(name) SELECT name FROM src.tags"
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO task_tags(task_id, tag_id)
                SELECT tt.task_id, dst.id
                  FROM src.task_tags tt
                  JOIN src.tags st ON st.id = tt.tag_id
                  JOIN tags dst ON dst.name = st.name
                """
            )

            before = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO checkpoints(
                  id, task_id, seq, outcome, decisions, open_items, created_at
                )
                SELECT id, task_id, seq, outcome, decisions, open_items, created_at
                  FROM src.checkpoints
                """
            )
            result["checkpoints"] = conn.total_changes - before

            before = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO artifacts(
                  id, checkpoint_id, description, content, created_at
                )
                SELECT a.id, a.checkpoint_id, a.description, a.content, a.created_at
                  FROM src.artifacts a
                  JOIN checkpoints c ON c.id = a.checkpoint_id
                """
            )
            result["artifacts"] = conn.total_changes - before

            before = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO task_links(
                  from_task, to_task, relation, note, created_at
                )
                SELECT l.from_task, l.to_task, l.relation, l.note, l.created_at
                  FROM src.task_links l
                  JOIN tasks f ON f.id = l.from_task
                  JOIN tasks t ON t.id = l.to_task
                """
            )
            result["links"] = conn.total_changes - before

            conn.execute("DELETE FROM tasks_fts")
            conn.execute(
                "INSERT INTO tasks_fts(id, title, summary) SELECT id, title, summary FROM tasks"
            )
    finally:
        try:
            conn.execute("DETACH DATABASE src")
        except sqlite3.Error:
            pass
        conn.close()
    return result


def merge_databases(
    sources: Iterable[str] | None = None,
    target_db: str = memory.DB_PATH,
) -> list[dict[str, int | str | bool]]:
    return [merge_database(source, target_db) for source in (sources or legacy_db_candidates())]


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Merge agent-memory DBs into the root store.")
    parser.add_argument("sources", nargs="*", help="Source DB paths. Defaults to common legacy locations.")
    parser.add_argument("--target", default=memory.DB_PATH, help="Target root DB path.")
    args = parser.parse_args()
    print(json.dumps(merge_databases(args.sources or None, args.target), indent=2))


if __name__ == "__main__":
    main()
