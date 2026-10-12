"""Initialize the persisted Google Sheets OAuth token without downloading CSV."""

from app.downloader.reference.google_oauth import get_credentials
from app.downloader.reference.config import SCOPES, load_settings
from app.logging_config import configure_logging


def main() -> None:
    """Run the interactive OAuth flow once and persist its refresh token."""
    configure_logging()
    settings = load_settings()
    get_credentials(settings.credentials_file, settings.token_file, SCOPES)


if __name__ == "__main__":
    main()
