"""
Tests for core/proactive.py — the background scheduler behind the
PROACTIVE tab. The orchestrator's tool_to_client map is faked (a bare
object with .call_tool returning an MCP-shaped result), so these check
the logic that's actually ours: the lookahead windows, dedup via
_notified, and that a disabled toggle genuinely skips checking rather
than just suppressing the broadcast.
"""

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from core import proactive


class FakeContentBlock:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, payload):
        self.content = [FakeContentBlock(json.dumps(payload))]


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return FakeResult(self.payload)


class FailingClient:
    async def call_tool(self, name, args):
        raise RuntimeError("integration down")


class FakeOrchestrator:
    def __init__(self, tool_to_client):
        self.tool_to_client = tool_to_client


@pytest.fixture(autouse=True)
def reset_proactive_state(monkeypatch):
    proactive._notified.clear()
    proactive._recent.clear()
    proactive.enabled = True
    broadcasts = []

    async def fake_broadcast(message):
        broadcasts.append(message)

    monkeypatch.setattr(proactive.realtime.manager, "broadcast", fake_broadcast)
    yield broadcasts
    proactive._notified.clear()
    proactive._recent.clear()
    proactive.enabled = True


def _soon_iso(minutes):
    return (datetime.now().astimezone() + timedelta(minutes=minutes)).isoformat()


class TestCheckCalendars:
    def test_upcoming_event_produces_a_notification(self, reset_proactive_state):
        broadcasts = reset_proactive_state
        events = [{"id": "evt1", "summary": "Standup", "start": _soon_iso(10)}]
        orch = FakeOrchestrator({"calendar_get_events": FakeClient(events)})

        notifications = asyncio.run(proactive.check_once(orch))

        assert len(notifications) == 1
        assert notifications[0]["category"] == "calendar"
        assert "Standup" in notifications[0]["title"]
        assert broadcasts == notifications

    def test_same_event_does_not_notify_twice(self):
        events = [{"id": "evt1", "summary": "Standup", "start": _soon_iso(10)}]
        orch = FakeOrchestrator({"calendar_get_events": FakeClient(events)})

        first = asyncio.run(proactive.check_once(orch))
        second = asyncio.run(proactive.check_once(orch))

        assert len(first) == 1
        assert len(second) == 0

    def test_unconfigured_calendar_tool_is_skipped_silently(self):
        orch = FakeOrchestrator({})  # neither calendar tool registered
        notifications = asyncio.run(proactive.check_once(orch))
        assert notifications == []

    def test_one_failing_calendar_source_does_not_block_the_other(self):
        events = [{"id": "evt1", "summary": "Standup", "start": _soon_iso(10)}]
        orch = FakeOrchestrator(
            {
                "calendar_get_events": FailingClient(),
                "icloud_calendar_get_events": FakeClient(events),
            }
        )
        notifications = asyncio.run(proactive.check_once(orch))
        assert len(notifications) == 1
        assert "Standup" in notifications[0]["title"]


class TestCheckTasks:
    def test_task_due_soon_produces_a_notification(self):
        tasks = [{"id": 1, "title": "Finish report", "due_at": _soon_iso(60), "completed": 0}]
        orch = FakeOrchestrator({"task_list": FakeClient(tasks)})
        notifications = asyncio.run(proactive.check_once(orch))
        assert len(notifications) == 1
        assert notifications[0]["category"] == "task"
        assert "Due soon" in notifications[0]["title"]

    def test_overdue_task_is_labeled_overdue(self):
        overdue_iso = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
        tasks = [{"id": 2, "title": "Old task", "due_at": overdue_iso, "completed": 0}]
        orch = FakeOrchestrator({"task_list": FakeClient(tasks)})
        notifications = asyncio.run(proactive.check_once(orch))
        assert "Overdue" in notifications[0]["title"]

    def test_completed_tasks_are_never_notified(self):
        tasks = [{"id": 3, "title": "Done already", "due_at": _soon_iso(5), "completed": 1}]
        orch = FakeOrchestrator({"task_list": FakeClient(tasks)})
        notifications = asyncio.run(proactive.check_once(orch))
        assert notifications == []

    def test_task_without_due_date_is_never_notified(self):
        tasks = [{"id": 4, "title": "Someday", "due_at": None, "completed": 0}]
        orch = FakeOrchestrator({"task_list": FakeClient(tasks)})
        notifications = asyncio.run(proactive.check_once(orch))
        assert notifications == []

    def test_task_due_far_in_the_future_is_not_notified_yet(self):
        tasks = [{"id": 5, "title": "Next month", "due_at": _soon_iso(60 * 24 * 30), "completed": 0}]
        orch = FakeOrchestrator({"task_list": FakeClient(tasks)})
        notifications = asyncio.run(proactive.check_once(orch))
        assert notifications == []


class TestEnabledToggle:
    def test_disabled_skips_checking_entirely(self):
        proactive.enabled = False
        events = [{"id": "evt1", "summary": "Standup", "start": _soon_iso(10)}]
        client = FakeClient(events)
        orch = FakeOrchestrator({"calendar_get_events": client})

        notifications = asyncio.run(proactive.check_once(orch))

        assert notifications == []
        assert client.calls == []  # genuinely skipped, not just suppressed after calling


class TestRecent:
    def test_get_recent_returns_newest_first(self):
        events = [{"id": "evt1", "summary": "First", "start": _soon_iso(10)}]
        orch1 = FakeOrchestrator({"calendar_get_events": FakeClient(events)})
        asyncio.run(proactive.check_once(orch1))

        events2 = [{"id": "evt2", "summary": "Second", "start": _soon_iso(15)}]
        orch2 = FakeOrchestrator({"calendar_get_events": FakeClient(events2)})
        asyncio.run(proactive.check_once(orch2))

        recent = proactive.get_recent()
        assert recent[0]["title"].endswith("Second")
        assert recent[1]["title"].endswith("First")
