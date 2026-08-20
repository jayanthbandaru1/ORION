"""
Shared Google OAuth for the Calendar and Gmail MCP servers.

One Desktop-app OAuth client (GOOGLE_CLIENT_ID/SECRET in .env), one
consent screen, both scopes granted at once — Calendar and Gmail don't
need separate logins. The refresh token is written back into .env
after the first interactive consent, per CLAUDE.md's "tokens stored
outside the repo, in .env." Every run after that is silent (refresh
only, no browser).

Run standalone once to do the interactive consent before starting the
server for the first time:
    python core/google_auth.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv, set_key
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)

# Both scopes requested together so one consent covers both servers.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
]

TOKEN_URI = "https://oauth2.googleapis.com/token"


def _client_config() -> dict:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set in .env — "
            "add them before running the Calendar or Gmail server."
        )
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }
    }


def _run_consent_flow() -> Credentials:
    """Opens a browser for the user to sign in and grant access. Interactive —
    only ever needed once, the first time there's no refresh token yet."""
    flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    set_key(str(ENV_PATH), "GOOGLE_REFRESH_TOKEN", creds.refresh_token)
    return creds


def get_credentials() -> Credentials:
    """Valid Credentials for Calendar/Gmail API calls. Refreshes silently
    if a refresh token is already in .env; runs the interactive consent
    flow (opens a browser) only the first time, when there isn't one."""
    load_dotenv(ENV_PATH, override=True)
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")

    if not refresh_token:
        return _run_consent_flow()

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


if __name__ == "__main__":
    get_credentials()
    print("Google OAuth consent complete — refresh token saved to .env.")
