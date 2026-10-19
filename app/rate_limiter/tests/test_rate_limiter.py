"""Unit tests for centralized provider rate limiting."""

from unittest.mock import Mock

import pytest
import requests

from app.contracts.models import Envelope
from app.messaging import rate_limit
from app.messaging.exceptions import RetryableMessageError
from app.messaging.rate_limit import rate_limit_google_client, rate_limit_session
from app.rate_limiter.config import configure_logging, load_settings
from app.rate_limiter.consumer import handle_request
from app.rate_limiter.models import RateLimiterSettings
from app.rate_limiter.redis_client import RedisCommandError
from app.rate_limiter.redis_store import RedisPermitStore


def test_settings_use_conservative_default_intervals(monkeypatch):
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    monkeypatch.delenv("RATE_LIMITER_REDIS_URL", raising=False)
    monkeypatch.delenv("RATE_LIMIT_CMS_MIN_INTERVAL_MS", raising=False)
    monkeypatch.delenv("RATE_LIMIT_GOOGLE_SHEETS_MIN_INTERVAL_MS", raising=False)
    monkeypatch.delenv("RATE_LIMIT_TELEGRAM_CHAT_MIN_INTERVAL_MS", raising=False)

    settings = load_settings()

    assert settings.cms_min_interval_ms == 5500
    assert settings.google_sheets_min_interval_ms == 1112
    assert settings.telegram_admin_chat_min_interval_ms == 3334


def test_settings_read_provider_specific_intervals(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker:9093")
    monkeypatch.setenv("RATE_LIMITER_REDIS_URL", "redis://redis:6379/2")
    monkeypatch.setenv("RATE_LIMIT_CMS_MIN_INTERVAL_MS", "6000")
    monkeypatch.setenv("RATE_LIMIT_GOOGLE_SHEETS_MIN_INTERVAL_MS", "1200")
    monkeypatch.setenv("RATE_LIMIT_TELEGRAM_CHAT_MIN_INTERVAL_MS", "4000")

    settings = load_settings()

    assert settings.bootstrap_servers == "broker:9093"
    assert settings.redis_url == "redis://redis:6379/2"
    assert settings.cms_min_interval_ms == 6000
    assert settings.google_sheets_min_interval_ms == 1200
    assert settings.telegram_admin_chat_min_interval_ms == 4000


def test_settings_reject_nonpositive_interval(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_CMS_MIN_INTERVAL_MS", "0")

    with pytest.raises(ValueError, match="Invalid rate-limiter settings"):
        load_settings()


def test_configure_logging_sets_standard_format(monkeypatch):
    basic_config = Mock()
    monkeypatch.setattr("app.rate_limiter.config.logging.basicConfig", basic_config)

    configure_logging()

    assert basic_config.call_args.kwargs["level"]
    assert "%(asctime)s" in basic_config.call_args.kwargs["format"]


def test_redis_store_reserves_one_permit_then_reports_remaining_ttl():
    redis = Mock()
    redis.set_if_absent.side_effect = [True, False]
    redis.ttl_milliseconds.return_value = 2500
    store = RedisPermitStore(redis)

    assert store.acquire("cms:account", 5500) == (True, 0)
    assert store.acquire("cms:account", 5500) == (False, 2500)
    assert redis.set_if_absent.call_args_list[0].args == (
        "rate-limit:cms:account",
        5500,
    )


def test_redis_store_rejects_nonpositive_interval():
    with pytest.raises(ValueError, match="positive"):
        RedisPermitStore(Mock()).acquire("cms:account", 0)


def test_consumer_uses_bucket_interval_and_replies(monkeypatch):
    settings = RateLimiterSettings(bootstrap_servers="broker", redis_url="redis://r")
    store = Mock()
    store.acquire.return_value = (False, 1200)
    reply = Mock()
    monkeypatch.setattr("app.rate_limiter.consumer.publish_reply", reply)
    message = Envelope.create(
        "acquire_permit",
        {"bucket": "google:sheets"},
        correlation_id="request-1",
        reply_to="rate.limit.responses",
    )

    handle_request(message, object(), settings, store)

    store.acquire.assert_called_once_with("google:sheets", 1112)
    assert reply.call_args.args[0] is not None
    assert reply.call_args.args[1:] == (
        message,
        {"granted": False, "retry_after_ms": 1200},
    )


def test_consumer_returns_typed_error_for_unknown_bucket(monkeypatch):
    settings = RateLimiterSettings(bootstrap_servers="broker", redis_url="redis://r")
    store = Mock()
    reply = Mock()
    monkeypatch.setattr("app.rate_limiter.consumer.publish_reply", reply)
    message = Envelope.create("acquire_permit", {"bucket": "unknown"})

    handle_request(message, object(), settings, store)

    store.acquire.assert_not_called()
    assert reply.call_args.kwargs["error"] == "'Unknown rate-limit bucket: unknown'"


@pytest.mark.parametrize(
    ("command", "payload", "expected"),
    [
        ("unexpected", {"bucket": "cms:account"}, "Unsupported rate-limit command"),
        ("acquire_permit", {}, "missing a bucket"),
        ("acquire_permit", {"bucket": 123}, "missing a bucket"),
        ("acquire_permit", {"bucket": ""}, "missing a bucket"),
    ],
)
def test_consumer_rejects_invalid_request(command, payload, expected, monkeypatch):
    settings = RateLimiterSettings(bootstrap_servers="broker", redis_url="redis://r")
    store = Mock()
    reply = Mock()
    monkeypatch.setattr("app.rate_limiter.consumer.publish_reply", reply)
    message = Envelope.create(command, payload)

    handle_request(message, object(), settings, store)

    store.acquire.assert_not_called()
    assert expected in reply.call_args.kwargs["error"]


def test_consumer_denies_permit_when_redis_is_unavailable(monkeypatch):
    settings = RateLimiterSettings(bootstrap_servers="broker", redis_url="redis://r")
    store = Mock()
    store.acquire.side_effect = OSError("connection refused")
    reply = Mock()
    monkeypatch.setattr("app.rate_limiter.consumer.publish_reply", reply)
    message = Envelope.create("acquire_permit", {"bucket": "cms:account"})

    handle_request(message, object(), settings, store)

    assert reply.call_args.kwargs["error"].startswith("RATE_LIMIT_BACKEND_UNAVAILABLE")


def test_consumer_handles_redis_command_error(monkeypatch):
    settings = RateLimiterSettings(bootstrap_servers="broker", redis_url="redis://r")
    store = Mock()
    store.acquire.side_effect = RedisCommandError("READONLY")
    reply = Mock()
    monkeypatch.setattr("app.rate_limiter.consumer.publish_reply", reply)
    message = Envelope.create("acquire_permit", {"bucket": "cms:account"})

    handle_request(message, object(), settings, store)

    assert reply.call_args.kwargs["error"].startswith("RATE_LIMIT_BACKEND_UNAVAILABLE")


def test_session_requests_permit_before_http_request(monkeypatch):
    client = Mock()
    events = []
    client.acquire.side_effect = lambda bucket: events.append(("permit", bucket))
    monkeypatch.setattr(
        "app.messaging.rate_limit.get_rate_limit_client", lambda *_: client
    )
    session = Mock()
    http_request = Mock(
        side_effect=lambda *args, **kwargs: events.append(("http", args))
    )
    session.request = http_request

    rate_limit_session(session, "broker", "worker", "cms:account")
    result = session.request("GET", "https://cms.invalid")

    assert result is None
    assert events == [
        ("permit", "cms:account"),
        ("http", ("GET", "https://cms.invalid")),
    ]


def test_session_does_not_send_http_if_rate_limiter_fails(monkeypatch):
    client = Mock()
    client.acquire.side_effect = RetryableMessageError("Redis is down")
    monkeypatch.setattr(
        "app.messaging.rate_limit.get_rate_limit_client", lambda *_: client
    )
    session = Mock()
    http_request = Mock()
    session.request = http_request
    rate_limit_session(session, "broker", "worker", "cms:account")

    with pytest.raises(RetryableMessageError):
        session.request("GET", "https://cms.invalid")

    http_request.assert_not_called()


def test_google_client_limits_api_and_refresh_sessions(monkeypatch):
    authorized_session = Mock()
    refresh_session = requests.Session()
    adapter = Mock(max_retries=3)
    refresh_session.adapters = {"https://": adapter}
    authorized_session._auth_request_session = refresh_session
    client = Mock()
    client.http_client.session = authorized_session
    wrapped = []
    monkeypatch.setattr(
        "app.messaging.rate_limit.rate_limit_session",
        lambda session, *args: wrapped.append((session, args)),
    )

    rate_limit_google_client(client, "broker")

    assert wrapped == [
        (
            authorized_session,
            ("broker", "downloader_reference", "google:sheets"),
        ),
        (
            refresh_session,
            ("broker", "downloader_reference", "google:sheets"),
        ),
    ]
    assert adapter.max_retries == 0


def test_rate_limit_client_is_cached_per_broker_and_service(monkeypatch):
    rate_limit._CLIENTS.clear()
    created = []

    class FakeRateLimitClient:
        def __init__(self, bootstrap_servers, service_name):
            created.append((bootstrap_servers, service_name, self))

    monkeypatch.setattr(rate_limit, "RateLimitClient", FakeRateLimitClient)

    first = rate_limit.get_rate_limit_client("broker", "worker")
    again = rate_limit.get_rate_limit_client("broker", "worker")
    other = rate_limit.get_rate_limit_client("broker", "other")

    assert first is again
    assert first is not other
    assert len(created) == 2
    rate_limit._CLIENTS.clear()


def test_direct_http_call_acquires_named_bucket(monkeypatch):
    client = Mock()
    monkeypatch.setattr(rate_limit, "get_rate_limit_client", lambda *_: client)

    rate_limit.acquire_rate_limit("broker", "notification", "telegram:admin_chat")

    client.acquire.assert_called_once_with("telegram:admin_chat")


def test_session_helper_rejects_objects_without_request_method():
    with pytest.raises(TypeError, match="callable request method"):
        rate_limit_session(object(), "broker", "worker", "cms:account")


def test_google_client_without_refresh_session_only_wraps_api_session(monkeypatch):
    session = requests.Session()
    client = Mock()
    client.http_client.session = session
    wrapped = Mock()
    monkeypatch.setattr("app.messaging.rate_limit.rate_limit_session", wrapped)

    rate_limit_google_client(client, "broker")

    wrapped.assert_called_once_with(
        session,
        "broker",
        "downloader_reference",
        "google:sheets",
    )


def test_rate_limiter_main_wires_redis_store_and_worker(monkeypatch):
    settings = RateLimiterSettings(
        bootstrap_servers="broker", redis_url="redis://redis:6379/2"
    )
    run_worker = Mock()
    redis_client = Mock()
    store = Mock()
    monkeypatch.setattr("app.rate_limiter.consumer.configure_logging", Mock())
    monkeypatch.setattr("app.rate_limiter.consumer.load_settings", lambda: settings)
    monkeypatch.setattr(
        "app.rate_limiter.consumer.RedisClient.from_url", lambda _: redis_client
    )
    monkeypatch.setattr("app.rate_limiter.consumer.RedisPermitStore", lambda _: store)
    monkeypatch.setattr("app.rate_limiter.consumer.run_consumer", run_worker)

    from app.rate_limiter.consumer import main

    main()

    args, kwargs = run_worker.call_args
    assert args[:3] == ("broker", "rate.limit.requests", "rate-limiter-service")
    assert args[3].keywords == {"settings": settings, "store": store}
    assert kwargs == {"service_name": "rate_limiter"}
