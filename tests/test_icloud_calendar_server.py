"""
Tests for the iCloud Calendar MCP server. The real CalDAV client is
mocked — these check the logic that's actually ours: datetime handling
(shared with the Google Calendar server's _parse_dt), event formatting
out of an icalendar component, calendar-name resolution (CalDAV has no
"primary" alias the way Google does), and client-side text search
(CalDAV has no server-side full-text search).
"""

import pytest

from conftest import load_server_module

icloud_server = load_server_module("icloud_calendar_server_module", "mcp_servers/icloud_calendar/server.py")


class FakeComponent(dict):
    """Minimal stand-in for icalendar's dict-like VEVENT component —
    supports the .get/.pop/.add subset the server actually uses."""

    def add(self, key, value):
        self[key] = value


class FakeProp:
    """Stand-in for icalendar's vDDDTypes wrapper, which exposes the
    real datetime via .dt."""

    def __init__(self, dt):
        self.dt = dt

    def __str__(self):
        return str(self.dt)


class FakeEvent:
    def __init__(self, uid, summary, start=None, end=None, location=None, description=None):
        comp = FakeComponent()
        comp["uid"] = uid
        comp["summary"] = summary
        if start is not None:
            comp["dtstart"] = FakeProp(start)
        if end is not None:
            comp["dtend"] = FakeProp(end)
        if location is not None:
            comp["location"] = location
        if description is not None:
            comp["description"] = description
        self.icalendar_component = comp
        self.saved = False
        self.deleted = False

    def save(self):
        self.saved = True

    def delete(self):
        self.deleted = True


class FakeCalendar:
    def __init__(self, display_name, events=None):
        self._display_name = display_name
        self._events = events or []
        self.date_search_calls = []
        self.add_event_calls = []

    def get_display_name(self):
        return self._display_name

    def date_search(self, start, end):
        self.date_search_calls.append((start, end))
        return self._events

    def add_event(self, **kwargs):
        self.add_event_calls.append(kwargs)
        return FakeEvent(
            uid="new-uid",
            summary=kwargs.get("summary"),
            start=kwargs.get("dtstart"),
            end=kwargs.get("dtend"),
            location=kwargs.get("location"),
            description=kwargs.get("description"),
        )

    def event_by_uid(self, uid):
        for e in self._events:
            if e.icalendar_component["uid"] == uid:
                return e
        raise ValueError(f"no event {uid}")


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    monkeypatch.setattr(icloud_server, "_calendars_cache", None)
    yield
    monkeypatch.setattr(icloud_server, "_calendars_cache", None)


def _mock_calendars(monkeypatch, calendars):
    monkeypatch.setattr(icloud_server, "_calendars_cache", calendars)


class TestParseDatetime:
    def test_naive_datetime_gets_localized(self):
        dt = icloud_server._parse_dt("2026-08-20T12:00:00")
        assert dt.tzinfo is not None

    def test_offset_datetime_is_preserved(self):
        dt = icloud_server._parse_dt("2026-08-20T12:00:00-07:00")
        assert dt.utcoffset().total_seconds() == -7 * 3600

    def test_z_suffix_is_utc(self):
        dt = icloud_server._parse_dt("2026-08-20T12:00:00Z")
        assert dt.utcoffset().total_seconds() == 0


class TestFormatEvent:
    def test_extracts_expected_fields(self):
        event = FakeEvent(
            uid="abc-123",
            summary="Test Meeting",
            start=icloud_server._parse_dt("2026-08-20T14:00:00Z"),
            end=icloud_server._parse_dt("2026-08-20T15:00:00Z"),
            location="Room 5",
            description="Discuss things",
        )
        formatted = icloud_server._format_event(event)
        assert formatted["uid"] == "abc-123"
        assert formatted["summary"] == "Test Meeting"
        assert formatted["location"] == "Room 5"
        assert formatted["description"] == "Discuss things"

    def test_missing_optional_fields_are_none(self):
        event = FakeEvent(uid="x", summary="Bare Event")
        formatted = icloud_server._format_event(event)
        assert formatted["start"] is None
        assert formatted["location"] is None


class TestGetCalendar:
    def test_defaults_to_first_calendar(self, monkeypatch):
        cal_a, cal_b = FakeCalendar("Home"), FakeCalendar("Work")
        _mock_calendars(monkeypatch, [cal_a, cal_b])
        assert icloud_server._get_calendar(None) is cal_a

    def test_finds_calendar_by_name_case_insensitive(self, monkeypatch):
        cal_a, cal_b = FakeCalendar("Home"), FakeCalendar("Work")
        _mock_calendars(monkeypatch, [cal_a, cal_b])
        assert icloud_server._get_calendar("WORK") is cal_b

    def test_unknown_name_lists_available_calendars(self, monkeypatch):
        _mock_calendars(monkeypatch, [FakeCalendar("Home"), FakeCalendar("Work")])
        with pytest.raises(ValueError, match="Home, Work"):
            icloud_server._get_calendar("Nonexistent")

    def test_no_calendars_raises(self, monkeypatch):
        _mock_calendars(monkeypatch, [])
        with pytest.raises(ValueError, match="No calendars found"):
            icloud_server._get_calendar(None)


class TestListCalendars:
    def test_returns_display_names(self, monkeypatch):
        _mock_calendars(monkeypatch, [FakeCalendar("Home"), FakeCalendar("Work")])
        assert icloud_server.icloud_calendar_list_calendars() == ["Home", "Work"]


class TestGetEvents:
    def test_returns_formatted_events(self, monkeypatch):
        ev = FakeEvent(
            uid="1", summary="Meeting",
            start=icloud_server._parse_dt("2026-08-20T10:00:00Z"),
            end=icloud_server._parse_dt("2026-08-20T11:00:00Z"),
        )
        cal = FakeCalendar("Home", events=[ev])
        _mock_calendars(monkeypatch, [cal])
        events = icloud_server.icloud_calendar_get_events(
            time_min="2026-08-20T00:00:00", time_max="2026-08-21T00:00:00"
        )
        assert len(events) == 1
        assert events[0]["summary"] == "Meeting"


class TestSearch:
    def test_filters_by_summary_substring(self, monkeypatch):
        ev1 = FakeEvent(uid="1", summary="Dentist appointment")
        ev2 = FakeEvent(uid="2", summary="Team sync")
        cal = FakeCalendar("Home", events=[ev1, ev2])
        _mock_calendars(monkeypatch, [cal])
        results = icloud_server.icloud_calendar_search(query="dentist")
        assert len(results) == 1
        assert results[0]["uid"] == "1"

    def test_filters_by_location_substring(self, monkeypatch):
        ev1 = FakeEvent(uid="1", summary="Standup", location="Zoom")
        ev2 = FakeEvent(uid="2", summary="Lunch", location="Cafeteria")
        cal = FakeCalendar("Home", events=[ev1, ev2])
        _mock_calendars(monkeypatch, [cal])
        results = icloud_server.icloud_calendar_search(query="cafeteria")
        assert len(results) == 1
        assert results[0]["uid"] == "2"


class TestCreateEvent:
    def test_passes_expected_fields_to_add_event(self, monkeypatch):
        cal = FakeCalendar("Home")
        _mock_calendars(monkeypatch, [cal])
        result = icloud_server.icloud_calendar_create_event(
            summary="New Event", start="2026-08-20T10:00:00-07:00", end="2026-08-20T11:00:00-07:00"
        )
        assert result["summary"] == "New Event"
        kwargs = cal.add_event_calls[0]
        assert kwargs["summary"] == "New Event"
        assert kwargs["dtstart"].utcoffset().total_seconds() == -7 * 3600

    def test_unknown_calendar_name_raises_before_creating(self, monkeypatch):
        cal = FakeCalendar("Home")
        _mock_calendars(monkeypatch, [cal])
        with pytest.raises(ValueError, match="No iCloud calendar named"):
            icloud_server.icloud_calendar_create_event(
                summary="X", start="2026-08-20T10:00:00", end="2026-08-20T11:00:00",
                calendar_name="Nonexistent",
            )
        assert cal.add_event_calls == []


class TestUpdateEvent:
    def test_updates_only_given_fields(self, monkeypatch):
        ev = FakeEvent(uid="1", summary="Old Title", location="Old Room")
        cal = FakeCalendar("Home", events=[ev])
        _mock_calendars(monkeypatch, [cal])
        result = icloud_server.icloud_calendar_update_event(uid="1", summary="New Title")
        assert result["summary"] == "New Title"
        assert result["location"] == "Old Room"
        assert ev.saved is True


class TestDeleteEvent:
    def test_deletes_matching_event(self, monkeypatch):
        ev = FakeEvent(uid="1", summary="To Delete")
        cal = FakeCalendar("Home", events=[ev])
        _mock_calendars(monkeypatch, [cal])
        result = icloud_server.icloud_calendar_delete_event(uid="1")
        assert "Deleted iCloud event 1" == result
        assert ev.deleted is True


class TestAuthError:
    def test_missing_credentials_surface_as_value_error(self, monkeypatch):
        def _raise():
            raise icloud_server.ICloudAuthError("ICLOUD_APPLE_ID / ICLOUD_APP_PASSWORD not set in .env")

        monkeypatch.setattr(icloud_server, "_calendars_cache", None)
        monkeypatch.setattr(icloud_server, "get_principal", lambda: (_ for _ in ()).throw(
            icloud_server.ICloudAuthError("not configured")
        ))
        with pytest.raises(ValueError, match="not configured"):
            icloud_server.icloud_calendar_list_calendars()
