"""
Shared iCloud CalDAV auth for the iCloud Calendar MCP server.

Unlike Google, iCloud has no per-app OAuth client to register. Apple's
CalDAV endpoint (https://caldav.icloud.com) authenticates with the full
Apple ID email plus an app-specific password — required because Apple
mandates 2FA for third-party CalDAV/IMAP clients and won't accept the
real Apple ID password for this. Generate one at
https://appleid.apple.com under "Sign-In and Security" ->
"App-Specific Passwords", then set ICLOUD_APPLE_ID / ICLOUD_APP_PASSWORD
in .env — never the real Apple ID password, and never hardcoded here.
"""

import os
from pathlib import Path

import caldav
from caldav.lib import error as caldav_error
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)

ICLOUD_CALDAV_URL = "https://caldav.icloud.com/"


class ICloudAuthError(Exception):
    """ICLOUD_APPLE_ID/ICLOUD_APP_PASSWORD missing or rejected by Apple —
    distinct from a normal CalDAV request error so the caller can point
    at the .env setup step instead of a raw 401/403."""


_principal = None


def get_principal() -> caldav.Principal:
    """The authenticated CalDAV principal for the configured iCloud
    account, cached after the first successful connection for the life
    of the server process."""
    global _principal
    if _principal is not None:
        return _principal

    load_dotenv(ENV_PATH, override=True)
    apple_id = os.environ.get("ICLOUD_APPLE_ID")
    app_password = os.environ.get("ICLOUD_APP_PASSWORD")
    if not apple_id or not app_password:
        raise ICloudAuthError(
            "ICLOUD_APPLE_ID / ICLOUD_APP_PASSWORD not set in .env — generate an "
            "app-specific password at https://appleid.apple.com (Sign-In and Security "
            "> App-Specific Passwords) and add both to .env before using iCloud Calendar tools."
        )

    client = caldav.DAVClient(url=ICLOUD_CALDAV_URL, username=apple_id, password=app_password)
    try:
        _principal = client.principal()
    except caldav_error.AuthorizationError as exc:
        raise ICloudAuthError(
            "Apple rejected these iCloud credentials — check ICLOUD_APPLE_ID and "
            "ICLOUD_APP_PASSWORD in .env (the app-specific password may have been revoked)."
        ) from exc
    return _principal


if __name__ == "__main__":
    principal = get_principal()
    names = [cal.get_display_name() for cal in principal.calendars()]
    print(f"iCloud CalDAV connected — {len(names)} calendar(s): {', '.join(names)}")
