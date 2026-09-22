from __future__ import annotations

from pathlib import Path
from typing import Sequence

from google.auth.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow


def get_credentials(
    credentials_file: Path,
    token_file: Path,
    scopes: Sequence[str],
) -> Credentials:
    if not credentials_file.is_file():
        raise FileNotFoundError(f"OAuth credentials file not found: {credentials_file}")

    credentials: UserCredentials | None = None
    if token_file.is_file():
        try:
            credentials = UserCredentials.from_authorized_user_file(
                str(token_file), scopes
            )
        except (ValueError, OSError):
            credentials = None

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception:
            credentials = None
        else:
            token_file.write_text(credentials.to_json(), encoding="utf-8")
            return credentials

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    credentials = flow.run_local_server(
        port=0,
        open_browser=False,
        access_type="offline",
        prompt="consent",
    )
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    return credentials
