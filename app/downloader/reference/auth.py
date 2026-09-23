"""OAuth2 authentication helpers for Google APIs.

This module provides a function to obtain valid user credentials for
accessing Google Sheets (or other Google APIs) using the installed-app
OAuth2 flow. Credentials are cached on disk and refreshed automatically
when possible.
"""

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
    """Obtain valid OAuth2 credentials for the given scopes.

    The function follows this strategy:

    1. If a previously stored token exists and is still valid, return it.
    2. If the token has expired but a refresh token is available, refresh
       it and persist the new token.
    3. Otherwise start the installed-app OAuth2 flow (local server) and
       save the resulting credentials for future use.

    Args:
        credentials_file: Path to the OAuth client secrets JSON file
            downloaded from Google Cloud Console.
        token_file: Path where the authorised-user token will be stored
            (and from which it will be loaded on subsequent runs).
        scopes: Sequence of OAuth2 scopes required by the application.

    Returns:
        A valid :class:`~google.auth.credentials.Credentials` instance
        that can be used with Google API clients.

    Raises:
        FileNotFoundError: If ``credentials_file`` does not exist.
        Exception: Propagated from the OAuth flow or token refresh when
            authentication cannot be completed.
    """
    if not credentials_file.is_file():
        raise FileNotFoundError(f"OAuth credentials file not found: {credentials_file}")

    credentials: UserCredentials | None = None

    if token_file.is_file():
        try:
            credentials = UserCredentials.from_authorized_user_file(
                str(token_file),
                scopes,
            )
        except (ValueError, OSError):
            # Corrupted or incompatible token file — treat as missing.
            credentials = None

    if credentials is not None and credentials.valid:
        return credentials

    if credentials is not None and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception:
            # Refresh failed — fall through to full re-authentication.
            credentials = None
        else:
            _persist_token(token_file, credentials)
            return credentials

    # No usable token — start the interactive OAuth flow.
    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_file),
        scopes,
    )
    credentials = flow.run_local_server(
        port=0,
        open_browser=False,
        access_type="offline",
        prompt="consent",
    )
    _persist_token(token_file, credentials)
    return credentials


def _persist_token(token_file: Path, credentials: UserCredentials) -> None:
    """Write credentials to disk, creating parent directories if needed.

    Args:
        token_file: Destination path for the token JSON.
        credentials: Authorised-user credentials to serialise.
    """
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
