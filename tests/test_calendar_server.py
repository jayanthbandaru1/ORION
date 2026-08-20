"""
Tests for the Calendar MCP server. The Google API itself is mocked —
these check the request-shaping and response-parsing logic that's
actually ours: datetime handling (the two real bugs found during live
testing, see the Phase 2 fix commit), event formatting, and error
humanization.
"""

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from conftest import load_server_module

calendar_server = load_server_module("calendar_server_module", "mcp_servers/calendar/server.py")


@pytest.fixture(autouse=True)
def mock_service(monkeypatch):
    service = MagicMock()
    monkeypatch.setattr(calendar_server, "_service", service)
    return service


def _http_error(status: int, reason: str = "error") -> HttpError:
    resp = type("Resp", (), {"status": status, "reason": reason})()
    return HttpError(resp, reason.encode())


class TestParseDatetime:
    def test_naive_datetime_gets_localized(self):
        dt = calendar_server._parse_dt("2026-08-20T12:00:00")
        assert dt.tzinfo is not None

    def test_offset_datetime_is_preserved(self):
        dt = calendar_server._parse_dt("2026-08-20T12:00:00-07:00")
        assert dt.utcoffset().total_seconds() == -7 * 3600

    def test_z_suffix_is_utc(self):
        dt = calendar_server._parse_dt("2026-08-20T12:00:00Z")
        assert dt.utcoffset().total_seconds() == 0


class TestEventDatetime:
    def test_always_includes_timezone_field(self):
        # Regression test: events.insert/update rejected a bare offset
        # with "Missing time zone definition" even though events.list
        # accepted the same thing — _event_dt exists specifically to
        # avoid hitting that again.
        result = calendar_server._event_dt("2026-08-20T12:00:00-07:00")
        assert result["timeZone"] == "UTC"
        assert "dateTime" in result

    def test_normalizes_to_utc_correctly(self):
        result = calendar_server._event_dt("2026-08-20T12:00:00-07:00")
        assert "19:00:00" in result["dateTime"]  # 12:00 PDT (-07:00) == 19:00 UTC


class TestFormatEvent:
    def test_extracts_expected_fields(self):
        event = {
            "id": "abc123",
            "summary": "Test Event",
            "start": {"dateTime": "2026-08-20T12:00:00Z"},
            "end": {"dateTime": "2026-08-20T13:00:00Z"},
            "status": "confirmed",
            "htmlLink": "https://example.com/event",
        }
        formatted = calendar_server._format_event(event)
        assert formatted["id"] == "abc123"
        assert formatted["summary"] == "Test Event"
        assert formatted["start"] == "2026-08-20T12:00:00Z"

    def test_missing_summary_gets_placeholder(self):
        event = {"id": "x", "start": {}, "end": {}}
        formatted = calendar_server._format_event(event)
        assert formatted["summary"] == "(no title)"


class TestCalendarGetEvents:
    def test_returns_formatted_events(self, mock_service):
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "1",
                    "summary": "Meeting",
                    "start": {"dateTime": "2026-08-20T10:00:00Z"},
                    "end": {"dateTime": "2026-08-20T11:00:00Z"},
                }
            ]
        }
        events = calendar_server.calendar_get_events(time_min="2026-08-20T00:00:00", time_max="2026-08-21T00:00:00")
        assert len(events) == 1
        assert events[0]["summary"] == "Meeting"

    def test_http_error_is_humanized_not_raw(self, mock_service):
        mock_service.events.return_value.list.return_value.execute.side_effect = _http_error(429, "rate limited")
        with pytest.raises(ValueError, match="rate limit"):
            calendar_server.calendar_get_events()


class TestCalendarCreateEvent:
    def test_sends_utc_normalized_body(self, mock_service):
        mock_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "new1",
            "summary": "New Event",
            "start": {"dateTime": "2026-08-20T17:00:00Z"},
            "end": {"dateTime": "2026-08-20T18:00:00Z"},
        }
        result = calendar_server.calendar_create_event(
            summary="New Event", start="2026-08-20T10:00:00-07:00", end="2026-08-20T11:00:00-07:00"
        )
        assert result["id"] == "new1"
        sent_body = mock_service.events.return_value.insert.call_args.kwargs["body"]
        assert sent_body["start"]["timeZone"] == "UTC"
        assert sent_body["summary"] == "New Event"

    def test_defaults_to_primary_calendar(self, mock_service):
        mock_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "x", "summary": "E", "start": {}, "end": {},
        }
        calendar_server.calendar_create_event(summary="E", start="2026-08-20T10:00:00", end="2026-08-20T11:00:00")
        assert mock_service.events.return_value.insert.call_args.kwargs["calendarId"] == "primary"


class TestCalendarDeleteEvent:
    def test_calls_delete_with_event_id(self, mock_service):
        calendar_server.calendar_delete_event(event_id="abc123", calendar_id="primary")
        mock_service.events.return_value.delete.assert_called_once_with(calendarId="primary", eventId="abc123")

    def test_http_error_on_delete_is_humanized(self, mock_service):
        mock_service.events.return_value.delete.return_value.execute.side_effect = _http_error(404, "not found")
        with pytest.raises(ValueError, match="not found"):
            calendar_server.calendar_delete_event(event_id="missing")
