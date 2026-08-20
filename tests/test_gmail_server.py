"""
Tests for the Gmail MCP server. The Gmail API is mocked — these check
MIME construction, header/body extraction, and error humanization.
"""

import base64
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from conftest import load_server_module

gmail_server = load_server_module("gmail_server_module", "mcp_servers/gmail/server.py")


@pytest.fixture(autouse=True)
def mock_service(monkeypatch):
    service = MagicMock()
    monkeypatch.setattr(gmail_server, "_service", service)
    return service


def _http_error(status: int, reason: str = "error") -> HttpError:
    resp = type("Resp", (), {"status": status, "reason": reason})()
    return HttpError(resp, reason.encode())


class TestHeaderExtraction:
    def test_finds_header_case_insensitively(self):
        headers = [{"name": "Subject", "value": "Hello"}, {"name": "From", "value": "a@b.com"}]
        assert gmail_server._header(headers, "subject") == "Hello"
        assert gmail_server._header(headers, "FROM") == "a@b.com"

    def test_missing_header_returns_none(self):
        assert gmail_server._header([], "Subject") is None


class TestExtractBody:
    def test_plain_text_top_level(self):
        text = "Hello world"
        data = base64.urlsafe_b64encode(text.encode()).decode()
        payload = {"mimeType": "text/plain", "body": {"data": data}}
        assert gmail_server._extract_body(payload) == text

    def test_recurses_into_multipart(self):
        text = "Nested body"
        data = base64.urlsafe_b64encode(text.encode()).decode()
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {}},
                {"mimeType": "text/plain", "body": {"data": data}},
            ],
        }
        assert gmail_server._extract_body(payload) == text

    def test_falls_back_when_no_plain_text_part(self):
        # Regression: an HTML-only marketing email has no text/plain part
        # at all — the fallback must return something, not crash or drop it.
        html = "<html><body>Hi</body></html>"
        data = base64.urlsafe_b64encode(html.encode()).decode()
        payload = {"mimeType": "text/html", "body": {"data": data}}
        assert gmail_server._extract_body(payload) == html


class TestCreateDraft:
    def test_builds_correct_mime_message(self, mock_service):
        mock_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {"id": "d1"}

        result = gmail_server.gmail_create_draft(to="x@example.com", subject="Hi", body="Test body")

        assert result == {"draft_id": "d1", "to": "x@example.com", "subject": "Hi"}
        sent_body = mock_service.users.return_value.drafts.return_value.create.call_args.kwargs["body"]
        raw = base64.urlsafe_b64decode(sent_body["message"]["raw"])
        assert b"Test body" in raw
        assert b"x@example.com" in raw

    def test_thread_id_included_when_given(self, mock_service):
        mock_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {"id": "d2"}
        gmail_server.gmail_create_draft(to="x@example.com", subject="Re: Hi", body="Reply", thread_id="t123")
        sent_body = mock_service.users.return_value.drafts.return_value.create.call_args.kwargs["body"]
        assert sent_body["message"]["threadId"] == "t123"

    def test_http_error_is_humanized(self, mock_service):
        mock_service.users.return_value.drafts.return_value.create.return_value.execute.side_effect = _http_error(401)
        with pytest.raises(ValueError, match="re-auth|authenticated"):
            gmail_server.gmail_create_draft(to="x@example.com", subject="Hi", body="Test")


class TestSendDraft:
    def test_sends_by_draft_id(self, mock_service):
        mock_service.users.return_value.drafts.return_value.send.return_value.execute.return_value = {"id": "m1"}
        result = gmail_server.gmail_send_draft(draft_id="d1")
        assert "m1" in result
        mock_service.users.return_value.drafts.return_value.send.assert_called_once_with(userId="me", body={"id": "d1"})
