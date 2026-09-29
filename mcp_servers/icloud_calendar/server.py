"""
ORION's iCloud Calendar MCP server (CalDAV).

A second, independent calendar source alongside mcp_servers/calendar/
(Google) — CLAUDE.md's "calendar integration is modular" principle
applies here too: this is an addition, not a replacement, so someone
whose events are split across a Google-connected Notion Calendar and a
personal iCloud calendar can have ORION see both.

iCloud has no per-app OAuth client the way Google does — auth is HTTP
Basic Auth against https://caldav.icloud.com with an Apple-ID
app-specific password (see core/icloud_auth.py). CalDAV also has no
single "primary" calendar concept the way Google has one; every tool's
`calendar_name` defaults to the first calendar returned for the account
and can be overridden — call icloud_calendar_list_calendars to see the
exact names available.

CalDAV has no server-side full-text search equivalent to Google's `q=`
parameter, so icloud_calendar_search fetches a date window and filters
client-side on summary/description/location.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.icloud_auth import ICloudAuthError, get_principal  # noqa: E402
from core.icloud_errors import humanize_icloud_error  # noqa: E402

mcp = FastMCP(
    name="orion-icloud-calendar",
    instructions=(
        "Read, search, and manage events on the user's iCloud (Apple) calendars — "
        "a separate account from Google Calendar. Call icloud_calendar_list_calendars "
        "first if calendar_name is unknown."
    ),
)

_calendars_cache = None


def _calendars():
    global _calendars_cache
    if _calendars_cache is None:
        _calendars_cache = get_principal().calendars()
    return _calendars_cache


def _get_calendar(calendar_name: str | None):
    calendars = _calendars()
    if not calendars:
        raise ValueError("No calendars found on this iCloud account.")
    if calendar_name is None:
        return calendars[0]
    for cal in calendars:
        if (cal.get_display_name() or "").lower() == calendar_name.lower():
            return cal
    available = ", ".join(cal.get_display_name() or "(unnamed)" for cal in calendars)
    raise ValueError(f"No iCloud calendar named '{calendar_name}'. Available: {available}")


def _parse_dt(value: str) -> datetime:
    """Same tolerant parsing as the Google Calendar server's _parse_dt —
    the model often omits an offset entirely, so a naive result is
    localized to the system timezone rather than sent bare."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


def _format_event(event) -> dict:
    comp = event.icalendar_component
    dtstart = comp.get("dtstart")
    dtend = comp.get("dtend")
    location = comp.get("location")
    description = comp.get("description")
    return {
        "uid": str(comp.get("uid", "")),
        "summary": str(comp.get("summary", "(no title)")),
        "start": dtstart.dt.isoformat() if dtstart else None,
        "end": dtend.dt.isoformat() if dtend else None,
        "location": str(location) if location else None,
        "description": str(description) if description else None,
    }


@mcp.tool()
def icloud_calendar_list_calendars() -> list[str]:
    """List the names of every calendar on the connected iCloud account."""
    try:
        return [cal.get_display_name() or "(unnamed)" for cal in _calendars()]
    except ICloudAuthError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def icloud_calendar_get_events(
    time_min: str | None = None,
    time_max: str | None = None,
    calendar_name: str | None = None,
) -> list[dict]:
    """List events in a time range on an iCloud calendar (default: now
    through 7 days from now). time_min/time_max are ISO 8601 datetimes.
    calendar_name defaults to the first calendar on the account — call
    icloud_calendar_list_calendars to see all available names."""
    now = datetime.now().astimezone()
    start = _parse_dt(time_min) if time_min else now
    end = _parse_dt(time_max) if time_max else now + timedelta(days=7)

    try:
        cal = _get_calendar(calendar_name)
        events = cal.date_search(start, end)
    except ICloudAuthError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError:
        raise
    except Exception as exc:  # caldav's DAVError family
        raise ValueError(humanize_icloud_error(exc)) from exc

    return [_format_event(e) for e in events]


@mcp.tool()
def icloud_calendar_search(
    query: str,
    time_min: str | None = None,
    time_max: str | None = None,
    calendar_name: str | None = None,
) -> list[dict]:
    """Search events by text across summary/description/location within a
    date window (default: 30 days back through 180 days ahead). CalDAV
    has no server-side full-text search, so this filters client-side
    after fetching the window."""
    now = datetime.now().astimezone()
    start = _parse_dt(time_min) if time_min else now - timedelta(days=30)
    end = _parse_dt(time_max) if time_max else now + timedelta(days=180)

    try:
        cal = _get_calendar(calendar_name)
        events = cal.date_search(start, end)
    except ICloudAuthError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(humanize_icloud_error(exc)) from exc

    query_lower = query.lower()
    formatted = [_format_event(e) for e in events]
    return [
        e
        for e in formatted
        if query_lower in (e["summary"] or "").lower()
        or query_lower in (e["description"] or "").lower()
        or query_lower in (e["location"] or "").lower()
    ]


@mcp.tool()
def icloud_calendar_create_event(
    summary: str,
    start: str,
    end: str,
    description: str | None = None,
    location: str | None = None,
    calendar_name: str | None = None,
) -> dict:
    """Create an event on an iCloud calendar. start/end are ISO 8601
    datetimes. SENSITIVE — confirm with the user before calling this for
    real."""
    try:
        cal = _get_calendar(calendar_name)
        event = cal.add_event(
            dtstart=_parse_dt(start),
            dtend=_parse_dt(end),
            summary=summary,
            description=description or "",
            location=location or "",
        )
    except ICloudAuthError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(humanize_icloud_error(exc)) from exc

    return _format_event(event)


@mcp.tool()
def icloud_calendar_update_event(
    uid: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
    location: str | None = None,
    calendar_name: str | None = None,
) -> dict:
    """Update fields on an existing iCloud event by its uid (only pass the
    fields that should change — get a uid from icloud_calendar_get_events
    or icloud_calendar_search). SENSITIVE."""
    try:
        cal = _get_calendar(calendar_name)
        event = cal.event_by_uid(uid)
        comp = event.icalendar_component
        if summary is not None:
            comp.pop("summary", None)
            comp.add("summary", summary)
        if start is not None:
            comp.pop("dtstart", None)
            comp.add("dtstart", _parse_dt(start))
        if end is not None:
            comp.pop("dtend", None)
            comp.add("dtend", _parse_dt(end))
        if description is not None:
            comp.pop("description", None)
            comp.add("description", description)
        if location is not None:
            comp.pop("location", None)
            comp.add("location", location)
        event.save()
    except ICloudAuthError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(humanize_icloud_error(exc)) from exc

    return _format_event(event)


@mcp.tool()
def icloud_calendar_delete_event(uid: str, calendar_name: str | None = None) -> str:
    """Permanently delete an iCloud calendar event by its uid. DESTRUCTIVE
    — confirm with the user before calling this for real."""
    try:
        cal = _get_calendar(calendar_name)
        event = cal.event_by_uid(uid)
        event.delete()
    except ICloudAuthError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(humanize_icloud_error(exc)) from exc

    return f"Deleted iCloud event {uid}"


if __name__ == "__main__":
    mcp.run()
