"""
Tests for the Tasks MCP server. No external API here — it's SQLite
via core/memory/store.py — so the only thing mocked is the database
path itself, pointed at a temp file instead of the real data/orion.db.
"""

from pathlib import Path

import pytest

from conftest import load_server_module

tasks_server = load_server_module("tasks_server_module", "mcp_servers/tasks/server.py")
from core.memory import store  # noqa: E402


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test_orion.db")
    store.init_db()


class TestTaskCreate:
    def test_creates_and_returns_task(self):
        task = tasks_server.task_create(title="Buy milk", due_at="2026-08-21T18:00:00", priority="high")
        assert task["title"] == "Buy milk"
        assert task["priority"] == "high"
        assert task["completed"] == 0

    def test_created_task_is_queryable(self):
        tasks_server.task_create(title="Test task")
        tasks = tasks_server.task_list()
        assert any(t["title"] == "Test task" for t in tasks)

    def test_optional_fields_default_to_none(self):
        task = tasks_server.task_create(title="No due date")
        assert task["due_at"] is None
        assert task["priority"] is None


class TestTaskList:
    def test_excludes_completed_by_default(self):
        t = tasks_server.task_create(title="Will complete")
        tasks_server.task_complete(t["id"])
        tasks_server.task_create(title="Still pending")

        pending = tasks_server.task_list()
        assert all(t["title"] != "Will complete" for t in pending)

    def test_includes_completed_when_asked(self):
        t = tasks_server.task_create(title="Will complete")
        tasks_server.task_complete(t["id"])

        all_tasks = tasks_server.task_list(include_completed=True)
        assert any(t["title"] == "Will complete" for t in all_tasks)


class TestTaskUpdate:
    def test_updates_only_given_fields(self):
        t = tasks_server.task_create(title="Original", priority="low")
        updated = tasks_server.task_update(t["id"], priority="high")
        assert updated["title"] == "Original"
        assert updated["priority"] == "high"

    def test_unknown_task_id_raises(self):
        with pytest.raises(ValueError, match="No task"):
            tasks_server.task_update(99999, title="Doesn't exist")


class TestTaskComplete:
    def test_marks_completed(self):
        t = tasks_server.task_create(title="Finish this")
        completed = tasks_server.task_complete(t["id"])
        assert completed["completed"] == 1


class TestTaskDelete:
    def test_removes_task(self):
        t = tasks_server.task_create(title="Delete me")
        tasks_server.task_delete(t["id"])
        remaining = tasks_server.task_list(include_completed=True)
        assert all(x["id"] != t["id"] for x in remaining)

    def test_unknown_task_id_raises(self):
        with pytest.raises(ValueError, match="No task"):
            tasks_server.task_delete(99999)
