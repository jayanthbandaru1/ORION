"""
ORION's conversation memory: SQLite-backed history so restarting the
server doesn't lose past conversations.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent.parent / "data" / "orion.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT,
    created_at TEXT NOT NULL,
    tool_calls_json TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    due_at TEXT,
    priority TEXT,
    completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def create_conversation(title: str | None = None) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (created_at, title) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), title),
        )
        return cur.lastrowid


def conversation_exists(conversation_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return row is not None


def add_message(
    conversation_id: int,
    role: str,
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> None:
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at, tool_calls_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, datetime.now(timezone.utc).isoformat(), tool_calls_json),
        )


def get_messages(conversation_id: int, limit: int = 20) -> list[dict[str, Any]]:
    # TODO: smarter truncation — this just keeps the last N turns
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content, tool_calls_json FROM messages "
            "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()

    messages = []
    for row in reversed(rows):
        msg: dict[str, Any] = {"role": row["role"], "content": row["content"]}
        if row["tool_calls_json"]:
            msg["tool_calls"] = json.loads(row["tool_calls_json"])
        messages.append(msg)
    return messages


def create_task(title: str, due_at: str | None = None, priority: str | None = None) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, due_at, priority, completed, created_at) VALUES (?, ?, ?, 0, ?)",
            (title, due_at, priority, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def get_task(task_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def list_tasks(include_completed: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM tasks" if include_completed else "SELECT * FROM tasks WHERE completed = 0"
    with _connect() as conn:
        rows = conn.execute(query + " ORDER BY due_at IS NULL, due_at, id").fetchall()
    return [dict(row) for row in rows]


def update_task(
    task_id: int,
    title: str | None = None,
    due_at: str | None = None,
    priority: str | None = None,
) -> dict[str, Any] | None:
    task = get_task(task_id)
    if task is None:
        return None
    with _connect() as conn:
        conn.execute(
            "UPDATE tasks SET title = ?, due_at = ?, priority = ? WHERE id = ?",
            (
                title if title is not None else task["title"],
                due_at if due_at is not None else task["due_at"],
                priority if priority is not None else task["priority"],
                task_id,
            ),
        )
    return get_task(task_id)


def complete_task(task_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        conn.execute("UPDATE tasks SET completed = 1 WHERE id = ?", (task_id,))
    return get_task(task_id)


def delete_task(task_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0
