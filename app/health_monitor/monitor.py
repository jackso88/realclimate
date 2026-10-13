"""Heartbeat tracking and direct Telegram alerts for application health."""

import logging
import math
import time
from typing import Callable

from confluent_kafka import Consumer, KafkaError
from confluent_kafka.admin import AdminClient

from app.health_monitor.models import HealthMonitorSettings, ServiceTransition
from app.messaging.config import load_client_settings
from app.messaging.kafka import sanitize_error
from app.messaging.models import Envelope
from app.messaging.topics import HEALTH_HEARTBEATS
from app.notifications.telegram import send_telegram_message

logger = logging.getLogger(__name__)


class HeartbeatTracker:
    """Track freshness and availability transitions for configured services.

    Args:
        services: Stable service names expected to publish heartbeats.
        timeout_seconds: Maximum permitted heartbeat age.
        startup_grace_seconds: Grace before missing first heartbeats alert.
        started_at: Monotonic clock value at monitor startup.
    """

    def __init__(
        self,
        services: tuple[str, ...],
        timeout_seconds: int,
        startup_grace_seconds: int,
        started_at: float,
    ) -> None:
        self.services = services
        self.timeout_seconds = timeout_seconds
        self.startup_grace_seconds = startup_grace_seconds
        self.grace_started_at = started_at
        self.last_seen: dict[str, float] = {}
        self.last_sent_at: dict[str, float] = {}
        self.status: dict[str, bool | None] = {service: None for service in services}

    def record(
        self,
        message: Envelope,
        *,
        now_monotonic: float,
        now_epoch: float,
    ) -> bool:
        """Record a fresh, recognized heartbeat envelope.

        Args:
            message: Decoded Kafka heartbeat envelope.
            now_monotonic: Current monotonic time for timeout comparisons.
            now_epoch: Current Unix timestamp for stale-message rejection.

        Returns:
            True when a fresh heartbeat was accepted; otherwise False.
        """
        if message.command != "heartbeat":
            return False
        service = message.payload.get("service")
        sent_at = message.payload.get("sent_at")
        if not isinstance(service, str) or service not in self.status:
            return False
        if not isinstance(sent_at, (int, float)) or isinstance(sent_at, bool):
            return False
        if not math.isfinite(sent_at):
            return False
        heartbeat_age = max(0.0, now_epoch - sent_at)
        if heartbeat_age > self.timeout_seconds or sent_at - now_epoch > 5:
            return False
        if sent_at <= self.last_sent_at.get(service, 0):
            return False

        self.last_sent_at[service] = float(sent_at)
        self.last_seen[service] = now_monotonic - heartbeat_age
        return True

    def begin_startup_grace(self, now_monotonic: float) -> None:
        """Restart the grace window after a Kafka outage or reconnection.

        Args:
            now_monotonic: Current monotonic time.
        """
        self.grace_started_at = now_monotonic

    def evaluate(self, now_monotonic: float) -> list[ServiceTransition]:
        """Return newly detected service availability transitions.

        Initial healthy heartbeats establish a baseline without sending
        notifications. Missing first heartbeats are ignored until the startup
        grace period expires.

        Args:
            now_monotonic: Current monotonic time.

        Returns:
            Outage and recovery transitions since the previous evaluation.
        """
        transitions = []
        for service in self.services:
            last_seen = self.last_seen.get(service)
            grace_active = (
                now_monotonic - self.grace_started_at < self.startup_grace_seconds
            )
            heartbeat_is_stale = (
                last_seen is None or now_monotonic - last_seen > self.timeout_seconds
            )
            if grace_active and heartbeat_is_stale:
                continue
            available = (
                last_seen is not None
                and now_monotonic - last_seen <= self.timeout_seconds
            )
            previous = self.status[service]
            self.status[service] = available
            if previous is not None and previous != available:
                transitions.append(ServiceTransition(service, available))
            elif previous is None and not available:
                transitions.append(ServiceTransition(service, False))
        return transitions


def _send_transition(
    transition: ServiceTransition,
    timeout_seconds: int,
    notifier: Callable[[str], None],
) -> bool:
    """Send one service state change directly to the administrator in Telegram.

    Args:
        transition: Newly observed up/down state.
        timeout_seconds: Heartbeat deadline used in outage text.
        notifier: Telegram message callback, injectable for unit tests.
    """
    if transition.available:
        text = f"✅ Сервис «{transition.service}» восстановил связь."
    else:
        text = (
            f"🚨 Сервис «{transition.service}» недоступен: heartbeat не поступал "
            f"более {timeout_seconds} секунд."
        )
    try:
        notifier(text)
    except Exception:
        logger.exception(
            "Could not send Telegram health alert for %s", transition.service
        )
        return False
    return True


def _send_broker_state(
    available: bool,
    error: str | None,
    notifier: Callable[[str], None],
) -> bool:
    """Send a Kafka outage or recovery message directly through Telegram.

    Args:
        available: Current Kafka connectivity state.
        error: Error text when Kafka is unavailable.
        notifier: Telegram message callback, injectable for unit tests.
    """
    if available:
        text = "✅ Kafka broker восстановил соединение."
    else:
        detail = f" Причина: {sanitize_error(error[:300])}" if error else ""
        text = f"🚨 Kafka broker недоступен.{detail}"
    try:
        notifier(text)
    except Exception:
        logger.exception("Could not send Telegram Kafka health alert")
        return False
    return True


def _check_broker(admin_client) -> tuple[bool, str | None]:
    """Check broker connectivity and return a bounded diagnostic on failure.

    Args:
        admin_client: Configured confluent-kafka AdminClient.

    Returns:
        A pair of availability and optional error details.
    """
    try:
        admin_client.list_topics(timeout=5)
    except Exception as error:
        return False, str(error)
    return True, None


def run_health_monitor(
    settings: HealthMonitorSettings,
    notifier: Callable[[str], None] = send_telegram_message,
) -> None:
    """Consume heartbeats, check Kafka, and send transition alerts.

    Telegram is called directly instead of publishing alerts to Kafka. This
    allows the monitor to report a Kafka outage and a stopped notification
    consumer as long as the host still has internet access.

    Args:
        settings: Kafka endpoint, monitored services, and timing thresholds.
        notifier: Telegram message sender; defaults to the Bot API client.
    """
    kafka_config = load_client_settings(settings.bootstrap_servers).to_dict()
    consumer = Consumer(
        {
            **kafka_config,
            "group.id": "health-monitor",
            "enable.auto.commit": True,
            "auto.offset.reset": "latest",
        }
    )
    admin_client = AdminClient(kafka_config)
    consumer.subscribe([HEALTH_HEARTBEATS])
    monotonic_now = time.monotonic()
    tracker = HeartbeatTracker(
        settings.monitored_services,
        settings.heartbeat_timeout_seconds,
        settings.startup_grace_seconds,
        monotonic_now,
    )
    kafka_available: bool | None = None
    next_broker_check = 0.0
    last_consumer_error_log = 0.0
    pending_alerts: list[tuple[str, ServiceTransition | bool, str | None]] = []
    next_alert_attempt = 0.0
    logger.info(
        "Health monitor started for services: %s",
        ", ".join(settings.monitored_services),
    )
    try:
        while True:
            try:
                message = consumer.poll(min(1.0, settings.check_interval_seconds))
            except Exception:
                message = None
                if (
                    time.monotonic() - last_consumer_error_log
                    >= settings.check_interval_seconds
                ):
                    logger.exception("Health heartbeat consumer poll failed")
                    last_consumer_error_log = time.monotonic()
            monotonic_now = time.monotonic()
            epoch_now = time.time()
            if message is not None:
                error = message.error()
                if error:
                    if (
                        error.code() != KafkaError._PARTITION_EOF
                        and monotonic_now - last_consumer_error_log
                        >= settings.check_interval_seconds
                    ):
                        logger.warning("Heartbeat consumer error: %s", error.str())
                        last_consumer_error_log = monotonic_now
                else:
                    try:
                        envelope = Envelope.decode(message.value())
                        tracker.record(
                            envelope,
                            now_monotonic=monotonic_now,
                            now_epoch=epoch_now,
                        )
                    except (AttributeError, KeyError, TypeError, ValueError):
                        logger.exception("Ignoring malformed health heartbeat")

            if monotonic_now >= next_broker_check:
                broker_is_available, broker_error = _check_broker(admin_client)
                next_broker_check = monotonic_now + settings.check_interval_seconds
                if kafka_available is None:
                    if not broker_is_available:
                        logger.error(
                            "Kafka broker is unavailable: %s",
                            sanitize_error(broker_error or "unknown error"),
                        )
                        pending_alerts.append(("broker", False, broker_error))
                    elif broker_is_available:
                        tracker.begin_startup_grace(monotonic_now)
                elif broker_is_available != kafka_available:
                    if broker_is_available:
                        logger.info("Kafka broker connection restored")
                    else:
                        logger.error(
                            "Kafka broker is unavailable: %s",
                            sanitize_error(broker_error or "unknown error"),
                        )
                    pending_alerts.append(("broker", broker_is_available, broker_error))
                    if broker_is_available:
                        tracker.begin_startup_grace(monotonic_now)
                kafka_available = broker_is_available

            if kafka_available:
                for transition in tracker.evaluate(monotonic_now):
                    pending_alerts.append(("service", transition, None))

            if pending_alerts and monotonic_now >= next_alert_attempt:
                alert_type, subject, detail = pending_alerts[0]
                if alert_type == "broker" and isinstance(subject, bool):
                    delivered = _send_broker_state(subject, detail, notifier)
                elif alert_type == "service" and isinstance(subject, ServiceTransition):
                    delivered = _send_transition(
                        subject,
                        settings.heartbeat_timeout_seconds,
                        notifier,
                    )
                else:
                    logger.error("Discarding malformed health alert: %s", alert_type)
                    delivered = True
                next_alert_attempt = monotonic_now + settings.check_interval_seconds
                if delivered:
                    pending_alerts.pop(0)
    finally:
        consumer.close()
