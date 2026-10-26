"""Heartbeat tracking and direct Telegram alerts for application health."""

import logging
import math
import time
from typing import Callable

from confluent_kafka import Consumer, KafkaError
from confluent_kafka.admin import AdminClient

from app.health_monitor.models import (
    STUCK,
    HealthMonitorSettings,
    ServiceTransition,
)
from app.messaging.config import load_client_settings
from app.messaging.kafka import sanitize_error
from app.contracts.models import Envelope
from app.messaging.topics import HEALTH_HEARTBEATS
from app.notifications.bot.telegram import send_telegram_message

logger = logging.getLogger(__name__)


class HeartbeatTracker:
    """Track freshness and availability transitions for configured services.

    Args:
        services: Stable service names expected to publish heartbeats.
        timeout_seconds: Maximum permitted heartbeat age.
        startup_grace_seconds: Grace before missing first heartbeats alert.
        started_at: Monotonic clock value at monitor startup.
        max_busy_seconds: Longest a worker may spend on one message before it
            is reported as stuck.
        busy_limits: Per-service replacements for ``max_busy_seconds``.
    """

    def __init__(
        self,
        services: tuple[str, ...],
        timeout_seconds: int,
        startup_grace_seconds: int,
        started_at: float,
        max_busy_seconds: int = 5400,
        busy_limits: dict[str, int] | None = None,
    ) -> None:
        self.services = services
        self.timeout_seconds = timeout_seconds
        self.startup_grace_seconds = startup_grace_seconds
        self.grace_started_at = started_at
        self.max_busy_seconds = max_busy_seconds
        self.busy_limits = busy_limits or {}
        self.last_seen: dict[str, float] = {}
        self.last_sent_at: dict[str, float] = {}
        self.busy_seconds: dict[str, float] = {}
        self.status: dict[str, bool | None] = {service: None for service in services}
        self.stuck: dict[str, bool] = {service: False for service in services}

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
        self.busy_seconds[service] = self._reported_busy_seconds(message)
        return True

    @staticmethod
    def _reported_busy_seconds(message: Envelope) -> float:
        """Read how long the sender says it has been busy with one message.

        Heartbeats from older workers have no such field, and a malformed value
        must not make the monitor reject an otherwise valid heartbeat, so both
        count as "not busy".

        Args:
            message: A heartbeat that already passed validation.

        Returns:
            The reported busy time in seconds, or 0.0 when absent or invalid.
        """
        busy = message.payload.get("busy_seconds", 0)
        if isinstance(busy, bool) or not isinstance(busy, (int, float)):
            return 0.0
        if not math.isfinite(busy) or busy < 0:
            return 0.0
        return float(busy)

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

        A worker whose heartbeats keep arriving can still be stuck: the
        heartbeat comes from a background thread, so it continues while the main
        loop is blocked on one message. Such a worker is reported once its
        reported busy time passes its limit, and again when it recovers.

        Args:
            now_monotonic: Current monotonic time.

        Returns:
            Outage, recovery, stuck and unstuck transitions since the previous
            evaluation.
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
                transitions.append(
                    ServiceTransition(service=service, available=available)
                )
            elif previous is None and not available:
                transitions.append(ServiceTransition(service=service, available=False))

            if not available:
                # An outage is reported on its own; "stuck" only describes a
                # worker that is still alive.
                self.stuck[service] = False
                continue
            limit = self.busy_limits.get(service, self.max_busy_seconds)
            busy = self.busy_seconds.get(service, 0.0)
            is_stuck = busy > limit
            if is_stuck != self.stuck[service]:
                self.stuck[service] = is_stuck
                transitions.append(
                    ServiceTransition(
                        service=service,
                        available=not is_stuck,
                        kind=STUCK,
                        busy_seconds=busy,
                        limit_seconds=limit,
                    )
                )
        return transitions


def _format_duration(seconds: float) -> str:
    """Format a duration for an alert: seconds when short, minutes otherwise.

    Args:
        seconds: Duration in seconds.

    Returns:
        Text such as ``"45 с"`` or ``"90 мин"``.
    """
    if seconds < 120:
        return f"{int(seconds)} с"
    return f"{int(seconds // 60)} мин"


def _transition_text(transition: ServiceTransition, timeout_seconds: int) -> str:
    """Build the Telegram text for one service state change.

    Args:
        transition: Newly observed state change.
        timeout_seconds: Heartbeat deadline used in outage text.

    Returns:
        The message to send to the administrator.
    """
    service = transition.service
    if transition.kind == STUCK:
        if transition.available:
            return f"✅ Сервис «{service}» завершил обработку сообщения."
        return (
            f"⚠️ Сервис «{service}» уже {_format_duration(transition.busy_seconds)} "
            "обрабатывает одно сообщение (лимит "
            f"{_format_duration(transition.limit_seconds)}). Процесс отвечает, "
            "но, возможно, завис."
        )
    if transition.available:
        return f"✅ Сервис «{service}» восстановил связь."
    return (
        f"🚨 Сервис «{service}» недоступен: heartbeat не поступал "
        f"более {timeout_seconds} секунд."
    )


def _send_transition(
    transition: ServiceTransition,
    timeout_seconds: int,
    notifier: Callable[[str], None],
) -> bool:
    """Send one service state change directly to the administrator in Telegram.

    Args:
        transition: Newly observed state change.
        timeout_seconds: Heartbeat deadline used in outage text.
        notifier: Telegram message callback, injectable for unit tests.
    """
    text = _transition_text(transition, timeout_seconds)
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
        max_busy_seconds=settings.max_busy_seconds,
        busy_limits=settings.busy_limit_overrides,
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
                    if transition.kind == STUCK and not transition.available:
                        logger.warning(
                            "Service %s has handled one message for %.0f s "
                            "(limit %d s)",
                            transition.service,
                            transition.busy_seconds,
                            transition.limit_seconds,
                        )
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
