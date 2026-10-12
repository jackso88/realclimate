"""Weekday hourly daemon that triggers the catalogue pipeline."""

import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.logging_config import configure_logging
from app.scheduler.producer import publish_core_run

logger = logging.getLogger(__name__)


def main() -> None:
    """Start the blocking scheduler for weekday catalogue updates.

    The job runs at minute zero of each hour from 09:00 through 17:00 in the
    configured timezone. It allows one active run and coalesces missed runs.
    """
    configure_logging()
    timezone = os.getenv("SCHEDULE_TIMEZONE", "Europe/Minsk")
    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(
        publish_core_run,
        CronTrigger(day_of_week="mon-fri", hour="9-17", minute=0, timezone=timezone),
        id="hourly-catalogue-run",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    logger.info("Scheduler active: weekdays 09:00–17:00 (%s)", timezone)
    scheduler.start()


if __name__ == "__main__":
    main()
