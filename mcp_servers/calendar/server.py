"""
ORION's Google Calendar MCP server.

Talks to the Google Calendar API directly (Notion Calendar has no API
of its own — it mirrors this account, so anything created/edited here
shows up there automatically; see CLAUDE.md's "Calendar — important
technical note").

`calendar_id` defaults to "primary" but every tool accepts an override
— this is how testing stays off the real calendar: point it at a
scratch calendar during development instead of "primary".
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastmcp import FastMCP
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.google_auth import get_credentials  # noqa: E402
from core.google_errors import humanize_google_error  # noqa: E402

mcp = FastMCP(
    name="orion-calendar",
    instructions="Read, search, and manage Google Calendar events. Use calendar_find_free_time before proposing a new event time.",
)

_service = None


def _client():
    global _service
    if _service is None:
        _service = build("calendar", "v3", credentials=get_credentials())
    return _service


def _parse_dt(value: str) -> datetime:
    """Accepts an ISO 8601 datetime (with or without a 'Z'/offset). The model
    often omits the offset entirely (e.g. "2026-08-20T00:00:00") — Google's API
    requires RFC3339 with one, so a naive result here is localized to the
    system timezone rather than sent to Google bare, which is a 400."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


def _event_dt(value: str) -> dict:
    """Build a Calendar API start/end object. events.list's timeMin/timeMax
    accept a bare RFC3339 offset, but events.insert/update reject the same
    thing with 'Missing time zone definition' unless a timeZone field is
    also present — found by hitting that error directly against the API.
    Normalizing to UTC here sidesteps needing this machine's IANA zone name
    (Windows doesn't expose one without an extra dependency); Google Calendar
    still displays the event in each viewer's own configured timezone."""
    dt = _parse_dt(value).astimezone(timezone.utc)
    return {"dateTime": dt.isoformat(), "timeZone": "UTC"}


def _format_event(event: dict) -> dict:
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event.get("id"),
        "summary": event.get("summary", "(no title)"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "location": event.get("location"),
        "description": event.get("description"),
        "status": event.get("status"),
        "html_link": event.get("htmlLink"),
    }


@mcp.tool()
def calendar_get_events(
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 20,
    calendar_id: str = "primary",
) -> list[dict]:
    """List events in a time range. time_min/time_max are ISO 8601 datetimes
    (default: now through 7 days from now if omitted)."""
    now = datetime.now().astimezone()
    start = _parse_dt(time_min) if time_min else now
    end = _parse_dt(time_max) if time_max else now + timedelta(days=7)

    try:
        result = (
            _client()
            .events()
            .list(
                calendarId=calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    return [_format_event(e) for e in result.get("items", [])]


@mcp.tool()
def calendar_search(query: str, max_results: int = 20, calendar_id: str = "primary") -> list[dict]:
    """Search events by text query across the whole calendar (titles, descriptions, attendees)."""
    try:
        result = (
            _client()
            .events()
            .list(calendarId=calendar_id, q=query, maxResults=max_results, singleEvents=True, orderBy="startTime")
            .execute()
        )
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    return [_format_event(e) for e in result.get("items", [])]


@mcp.tool()
def calendar_find_free_time(
    time_min: str,
    time_max: str,
    duration_minutes: int,
    calendar_id: str = "primary",
) -> list[dict]:
    """Find open slots of at least duration_minutes within [time_min, time_max]
    (both ISO 8601 datetimes). Returns a list of {start, end} candidate slots."""
    start = _parse_dt(time_min)
    end = _parse_dt(time_max)

    try:
        result = (
            _client()
            .freebusy()
            .query(body={"timeMin": start.isoformat(), "timeMax": end.isoformat(), "items": [{"id": calendar_id}]})
            .execute()
        )
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    busy = result["calendars"][calendar_id].get("busy", [])
    busy_ranges = sorted(
        (_parse_dt(b["start"]), _parse_dt(b["end"])) for b in busy
    )

    free_slots = []
    cursor = start
    for busy_start, busy_end in busy_ranges:
        if busy_start > cursor:
            gap = (busy_start - cursor).total_seconds() / 60
            if gap >= duration_minutes:
                free_slots.append({"start": cursor.isoformat(), "end": busy_start.isoformat()})
        cursor = max(cursor, busy_end)
    if end > cursor and (end - cursor).total_seconds() / 60 >= duration_minutes:
        free_slots.append({"start": cursor.isoformat(), "end": end.isoformat()})

    return free_slots


@mcp.tool()
def calendar_create_event(
    summary: str,
    start: str,
    end: str,
    description: str | None = None,
    location: str | None = None,
    calendar_id: str = "primary",
) -> dict:
    """Create a calendar event. start/end are ISO 8601 datetimes. SENSITIVE — confirm with the user before calling this for real."""
    body = {
        "summary": summary,
        "start": _event_dt(start),
        "end": _event_dt(end),
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location

    try:
        event = _client().events().insert(calendarId=calendar_id, body=body).execute()
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    return _format_event(event)


@mcp.tool()
def calendar_update_event(
    event_id: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
    location: str | None = None,
    calendar_id: str = "primary",
) -> dict:
    """Update fields on an existing event (only pass the fields that should change). SENSITIVE."""
    try:
        event = _client().events().get(calendarId=calendar_id, eventId=event_id).execute()

        if summary is not None:
            event["summary"] = summary
        if start is not None:
            event["start"] = _event_dt(start)
        if end is not None:
            event["end"] = _event_dt(end)
        if description is not None:
            event["description"] = description
        if location is not None:
            event["location"] = location

        updated = _client().events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    return _format_event(updated)


@mcp.tool()
def calendar_delete_event(event_id: str, calendar_id: str = "primary") -> str:
    """Permanently delete a calendar event. DESTRUCTIVE — confirm with the user before calling this for real."""
    try:
        _client().events().delete(calendarId=calendar_id, eventId=event_id).execute()
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    return f"Deleted event {event_id}"


if __name__ == "__main__":
    mcp.run()
