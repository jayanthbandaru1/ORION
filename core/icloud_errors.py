"""
Shared iCloud CalDAV error translation for the iCloud Calendar MCP
server — mirrors core/google_errors.py's role for the Google servers.
"""

from caldav.lib import error as caldav_error


def humanize_icloud_error(exc: Exception) -> str:
    if isinstance(exc, caldav_error.AuthorizationError):
        return (
            "Apple rejected these iCloud credentials — check ICLOUD_APPLE_ID and "
            "ICLOUD_APP_PASSWORD in .env (the app-specific password may have been revoked)."
        )
    if isinstance(exc, caldav_error.NotFoundError):
        return f"iCloud Calendar: not found — {exc}"
    if isinstance(exc, caldav_error.RateLimitError):
        return "iCloud CalDAV rate limit hit — wait a moment and try again."
    if isinstance(exc, caldav_error.DAVError):
        return f"iCloud Calendar error: {exc}"
    return f"iCloud Calendar error: {exc}"
