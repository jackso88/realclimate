"""Validate Google Sheets credentials without downloading spreadsheet data."""

from app.downloader.reference.config import SCOPES, configure_logging, load_settings
from app.downloader.reference.google_oauth import (
    get_credentials,
    get_service_account_credentials,
)


def main() -> None:
    """Initialize credentials for the configured Google auth mode."""
    configure_logging()
    settings = load_settings()
    if getattr(settings, "auth_mode", "user") == "service_account":
        get_service_account_credentials(settings.service_account_file, SCOPES)
    else:
        get_credentials(settings.credentials_file, settings.token_file, SCOPES)


if __name__ == "__main__":
    main()
