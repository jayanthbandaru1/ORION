"""
ORION's proactive layer — a background scheduler that checks upcoming
calendar events and due tasks on its own initiative, without any chat
turn prompting it, and pushes real notifications over the realtime
WebSocket (core/realtime.py). Nothing in ORION acted unprompted before
this; the spec's "proactive behavior... no foundation exists yet" (see
CLAUDE.md) is what this fixes.

Reuses the orchestrator's own `tool_to_client` map to call the exact
same calendar_get_events / icloud_calendar_get_events / task_list tools
a chat turn would — not a second, parallel read path. Each integration's
failure (e.g. iCloud not configured with credentials yet) is caught
independently so one broken/unconfigured tool doesn't silence proactive
checks for everything else.
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Any

from core import realtime
from core.orchestrator import _extract_text

POLL_SECONDS = 120
EVENT_LOOKAHEAD_MINUTES = 20
TASK_DUE_LOOKAHEAD_HOURS = 24

CALENDAR_TOOLS = ["calendar_get_events", "icloud_calendar_get_events"]

# Configurable on/off per the spec ("proactive behavior must be
# configurable... should never become annoying") — toggled via
# POST /proactive/toggle, read by the PROACTIVE tab.
enabled = True

# A calendar event or task only ever notifies once per server run — an
# in-memory set is enough (a restarted server re-noticing something
# still genuinely upcoming isn't a bug, it's correct behavior).
_notified: set[str] = set()

_RECENT_MAXLEN = 50
_recent: list[dict[str, Any]] = []


def _record(notification: dict[str, Any]) -> None:
    _recent.append(notification)
    if len(_recent) > _RECENT_MAXLEN:
        del _recent[: len(_recent) - _RECENT_MAXLEN]


def get_recent() -> list[dict[str, Any]]:
    return list(reversed(_recent))


async def _check_calendars(orchestrator) -> list[dict[str, Any]]:
    now = datetime.now().astimezone()
    window_end = now + timedelta(minutes=EVENT_LOOKAHEAD_MINUTES)
    notifications = []

    for tool_name in CALENDAR_TOOLS:
        client = orchestrator.tool_to_client.get(tool_name)
        if client is None:
            continue
        try:
            result = await client.call_tool(
                tool_name, {"time_min": now.isoformat(), "time_max": window_end.isoformat()}
            )
            events = json.loads(_extract_text(result))
        except Exception:
            continue  # this calendar source is down/unconfigured — don't block the other one

        for event in events or []:
            event_key = event.get("id") or event.get("uid")
            if not event_key:
                continue
            key = f"event:{tool_name}:{event_key}"
            if key in _notified:
                continue
            _notified.add(key)
            notifications.append(
                {
                    "id": key,
                    "type": "notification",
                    "category": "calendar",
                    "title": f"Upcoming: {event.get('summary', '(no title)')}",
                    "body": f"Starts {event.get('start', 'soon')}",
                    "created_at": time.time(),
                }
            )
    return notifications


async def _check_tasks(orchestrator) -> list[dict[str, Any]]:
    client = orchestrator.tool_to_client.get("task_list")
    if client is None:
        return []
    try:
        result = await client.call_tool("task_list", {})
        tasks = json.loads(_extract_text(result))
    except Exception:
        return []

    now = datetime.now().astimezone()
    notifications = []
    for task in tasks or []:
        if task.get("completed"):
            continue
        due_at = task.get("due_at")
        if not due_at:
            continue
        try:
            due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
            if due.tzinfo is None:
                due = due.astimezone()
        except ValueError:
            continue

        hours_until_due = (due - now).total_seconds() / 3600
        if hours_until_due > TASK_DUE_LOOKAHEAD_HOURS:
            continue

        key = f"task:{task['id']}"
        if key in _notified:
            continue
        _notified.add(key)
        label = "Overdue" if hours_until_due < 0 else "Due soon"
        notifications.append(
            {
                "id": key,
                "type": "notification",
                "category": "task",
                "title": f"{label}: {task['title']}",
                "body": f"Due {due_at}",
                "created_at": time.time(),
            }
        )
    return notifications


async def check_once(orchestrator) -> list[dict[str, Any]]:
    """Runs one proactive check immediately — used by the background loop
    and directly testable without waiting for the real interval."""
    if not enabled:
        return []
    notifications = await _check_calendars(orchestrator)
    notifications += await _check_tasks(orchestrator)
    for notification in notifications:
        _record(notification)
        await realtime.manager.broadcast(notification)
    return notifications


async def proactive_loop(orchestrator) -> None:
    while True:
        try:
            await check_once(orchestrator)
        except Exception:
            pass  # a single bad cycle shouldn't kill proactive checks forever
        await asyncio.sleep(POLL_SECONDS)
