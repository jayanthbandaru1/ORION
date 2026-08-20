"""
ORION's tasks/reminders MCP server.

Reuses the Phase 1 SQLite database (core/memory/store.py) rather than
standing up a separate store — tasks are structured memory, same as
conversation history. Actual notification delivery is out of scope
for the beta (see CLAUDE.md's Foundations section); creating and
querying tasks is what this server does.
"""

import sys
from pathlib import Path

from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.memory import store  # noqa: E402

store.init_db()

mcp = FastMCP(
    name="orion-tasks",
    instructions="Create and manage tasks/reminders. Cross-reference the calendar tools when a task implies scheduled time (e.g. 'study for 3 hours this weekend').",
)


@mcp.tool()
def task_list(include_completed: bool = False) -> list[dict]:
    """List tasks, soonest due first. Excludes completed tasks unless include_completed is true."""
    return store.list_tasks(include_completed=include_completed)


@mcp.tool()
def task_create(title: str, due_at: str | None = None, priority: str | None = None) -> dict:
    """Create a task. due_at is an ISO 8601 datetime if given; priority is freeform (e.g. 'high')."""
    task_id = store.create_task(title, due_at=due_at, priority=priority)
    return store.get_task(task_id)


@mcp.tool()
def task_update(
    task_id: int,
    title: str | None = None,
    due_at: str | None = None,
    priority: str | None = None,
) -> dict:
    """Update a task's title, due date, and/or priority (only pass what's changing)."""
    task = store.update_task(task_id, title=title, due_at=due_at, priority=priority)
    if task is None:
        raise ValueError(f"No task with id {task_id}")
    return task


@mcp.tool()
def task_complete(task_id: int) -> dict:
    """Mark a task as completed."""
    task = store.complete_task(task_id)
    if task is None:
        raise ValueError(f"No task with id {task_id}")
    return task


@mcp.tool()
def task_delete(task_id: int) -> str:
    """Delete a task. REVERSIBLE (the task is gone, but nothing external is affected)."""
    if not store.delete_task(task_id):
        raise ValueError(f"No task with id {task_id}")
    return f"Deleted task {task_id}"


if __name__ == "__main__":
    mcp.run()
