import logging

from app.core.clean_reference import main as clean_reference
from app.downloader.current.cli import main as current_cli
from app.downloader.reference.cli import main as reference_cli
from app.logging_config import configure_logging
from app.uploader.cli import main as uploader_cli

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    logger.info("Starting catalogue update")
    for step_name, step in (
        ("reference download", reference_cli),
        ("current export", current_cli),
        ("catalogue processing", clean_reference),
        ("processed catalogue upload and import", uploader_cli),
    ):
        logger.info("Starting %s", step_name)
        result = step()
        if result == 1:
            raise SystemExit(f"{step_name} failed")
    logger.info("Catalogue update completed")


if __name__ == "__main__":
    main()
