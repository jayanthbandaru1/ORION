"""
Shared Google API error translation for the Calendar and Gmail MCP
servers — turns a raw HttpError into a message the model (and
therefore the user) can actually act on, per PHASE4.md: quota/rate-
limit responses caught and explained rather than crashing the request,
stale auth pointed at a clear re-auth step rather than a bare 401.
"""

from googleapiclient.errors import HttpError


def humanize_google_error(exc: HttpError) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = str(exc)

    if status == 401:
        return (
            "Google rejected this request as unauthenticated, even after a token refresh — "
            "run `python core/google_auth.py` again to sign in."
        )
    if status == 403 and ("quota" in reason.lower() or "rateLimitExceeded" in reason or "userRateLimitExceeded" in reason):
        return "Google API quota exceeded — wait a while before retrying, or check quota in the Google Cloud Console."
    if status == 429:
        return "Google API rate limit hit (429) — wait a moment and try again."
    if status == 404:
        return f"Google API: not found — {reason}"
    return f"Google API error: {reason}"
