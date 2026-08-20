"""
ORION's Gmail MCP server.

Shares the same OAuth client/consent as the Calendar server (see
core/google_auth.py) — one grant, both scopes. Every send stays
SENSITIVE per CLAUDE.md's permission model: drafts are cheap and
private, sends are real and irreversible.
"""

import base64
import sys
from email.mime.text import MIMEText
from pathlib import Path

from fastmcp import FastMCP
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.google_auth import get_credentials  # noqa: E402
from core.google_errors import humanize_google_error  # noqa: E402

mcp = FastMCP(
    name="orion-gmail",
    instructions="Search, read, and draft Gmail. gmail_send_draft actually sends mail — SENSITIVE, confirm with the user first.",
)

_service = None


def _client():
    global _service
    if _service is None:
        _service = build("gmail", "v1", credentials=get_credentials())
    return _service


def _header(headers: list[dict], name: str) -> str | None:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return None


def _b64_decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode(errors="replace")


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _b64_decode(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    # Fall back to whatever's in the body even if it's not plain text.
    data = payload.get("body", {}).get("data")
    return _b64_decode(data) if data else ""


@mcp.tool()
def gmail_search(query: str, max_results: int = 10) -> list[dict]:
    """Search Gmail with standard Gmail search syntax (e.g. 'is:unread from:john'). Returns id, from, subject, date, snippet."""
    try:
        result = _client().users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        messages = result.get("messages", [])

        out = []
        for m in messages:
            msg = (
                _client()
                .users()
                .messages()
                .get(userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
            headers = msg["payload"]["headers"]
            out.append({
                "id": msg["id"],
                "thread_id": msg["threadId"],
                "from": _header(headers, "From"),
                "subject": _header(headers, "Subject"),
                "date": _header(headers, "Date"),
                "snippet": msg.get("snippet"),
            })
        return out
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc


@mcp.tool()
def gmail_get_message(message_id: str) -> dict:
    """Get the full content (headers + plain-text body) of a single message."""
    try:
        msg = _client().users().messages().get(userId="me", id=message_id, format="full").execute()
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    headers = msg["payload"]["headers"]
    return {
        "id": msg["id"],
        "thread_id": msg["threadId"],
        "from": _header(headers, "From"),
        "to": _header(headers, "To"),
        "subject": _header(headers, "Subject"),
        "date": _header(headers, "Date"),
        "body": _extract_body(msg["payload"]),
    }


@mcp.tool()
def gmail_get_thread(thread_id: str) -> list[dict]:
    """Get every message in a thread, in order."""
    try:
        thread = _client().users().threads().get(userId="me", id=thread_id, format="full").execute()
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    out = []
    for msg in thread.get("messages", []):
        headers = msg["payload"]["headers"]
        out.append({
            "id": msg["id"],
            "from": _header(headers, "From"),
            "to": _header(headers, "To"),
            "subject": _header(headers, "Subject"),
            "date": _header(headers, "Date"),
            "body": _extract_body(msg["payload"]),
        })
    return out


@mcp.tool()
def gmail_create_draft(to: str, subject: str, body: str, thread_id: str | None = None) -> dict:
    """Create a Gmail draft. Nothing is sent — drafts are private and SAFE.
    Pass thread_id to draft it as a reply within an existing thread."""
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    draft_body = {"message": {"raw": raw}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id

    try:
        draft = _client().users().drafts().create(userId="me", body=draft_body).execute()
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    return {"draft_id": draft["id"], "to": to, "subject": subject}


@mcp.tool()
def gmail_update_draft(draft_id: str, to: str, subject: str, body: str) -> dict:
    """Replace a draft's contents. Gmail's API replaces the whole message, so
    pass to/subject/body together even if only one is changing. SAFE."""
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    try:
        draft = (
            _client()
            .users()
            .drafts()
            .update(userId="me", id=draft_id, body={"message": {"raw": raw}})
            .execute()
        )
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    return {"draft_id": draft["id"], "to": to, "subject": subject}


@mcp.tool()
def gmail_send_draft(draft_id: str) -> str:
    """Send an existing draft for real. SENSITIVE — this actually delivers mail; confirm with the user before calling this for real."""
    try:
        sent = _client().users().drafts().send(userId="me", body={"id": draft_id}).execute()
    except HttpError as exc:
        raise ValueError(humanize_google_error(exc)) from exc

    return f"Sent message {sent['id']}"


if __name__ == "__main__":
    mcp.run()
