"""Tests for the Telegram Bot API client."""

import traceback
from unittest.mock import Mock

import pytest
import requests
import json
import urllib3
import io
from app.notifications.bot import telegram
from app.notifications.bot.exceptions import TelegramDeliveryError
from urllib3.exceptions import ProtocolError
from app.notifications.bot.telegram import _send_part


def send(token):
    _send_part(token, "42", "hello", 5.0, "kafka:9092")


def make_response(status=200, body=None, headers=None):
    payload = json.dumps(body if body is not None else {"ok": True}).encode()
    return urllib3.HTTPResponse(
        body=io.BytesIO(payload),
        status=status,
        headers={"Content-Type": "application/json", **(headers or {})},
        preload_content=False,
        request_method="POST",
    )


def sent_texts(post):
    return [call.kwargs["json"]["text"] for call in post.call_args_list]


def test_message_is_posted_to_the_bot_endpoint(post, token_url):
    telegram.send_telegram_message("hello")

    post.assert_called_once_with(
        token_url,
        json={"chat_id": "42", "text": "hello"},
        timeout=15,
    )


def test_timeout_can_be_customised(post):
    telegram.send_telegram_message("hello", timeout=3)

    assert post.call_args.kwargs["timeout"] == 3


def test_missing_bot_token_is_reported_by_name(post, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")

    with pytest.raises(KeyError, match="TELEGRAM_BOT_TOKEN"):
        telegram.send_telegram_message("hello")

    post.assert_not_called()


def test_missing_chat_id_is_reported_by_name(post, monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID")

    with pytest.raises(KeyError, match="TELEGRAM_CHAT_ID"):
        telegram.send_telegram_message("hello")

    post.assert_not_called()


def test_a_rejected_notification_raises(post):
    post.response.json.return_value = {"ok": False, "description": "chat not found"}

    with pytest.raises(TelegramDeliveryError, match="rejected"):
        telegram.send_telegram_message("hello")


def test_delivery_errors_are_still_runtime_errors(post):
    post.response.json.return_value = {"ok": False}

    with pytest.raises(RuntimeError):
        telegram.send_telegram_message("hello")


# ------------------------------------------------- errors never expose the token


def test_http_errors_become_delivery_errors_without_the_token(post, token_url, token):
    post.response.raise_for_status.side_effect = requests.HTTPError(
        f"400 Client Error: Bad Request for url: {token_url}"
    )

    with pytest.raises(TelegramDeliveryError) as error:
        telegram.send_telegram_message("hello")

    assert "400 Client Error" in str(error.value)
    assert token not in str(error.value)
    assert "bot<redacted>" in str(error.value)


def test_network_errors_become_delivery_errors_without_the_token(post, token):
    post.side_effect = requests.ConnectionError(
        "HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries "
        f"exceeded with url: /bot{token}/sendMessage (Caused by timeout)"
    )

    with pytest.raises(TelegramDeliveryError) as error:
        telegram.send_telegram_message("hello")

    assert token not in str(error.value)
    assert "Max retries exceeded" in str(error.value)


def test_a_bare_token_without_the_bot_prefix_is_redacted_too(post, token):
    post.side_effect = requests.ConnectionError(f"proxy rejected {token}")

    with pytest.raises(TelegramDeliveryError) as error:
        telegram.send_telegram_message("hello")

    assert token not in str(error.value)


def test_the_token_does_not_reach_the_logged_traceback(post, token_url, token):
    post.response.raise_for_status.side_effect = requests.HTTPError(
        f"400 Client Error: Bad Request for url: {token_url}"
    )

    with pytest.raises(TelegramDeliveryError) as error:
        telegram.send_telegram_message("hello")

    logged = "".join(traceback.format_exception(error.value))
    assert token not in logged
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_telegrams_own_explanation_is_included_in_the_error(post):
    failed = Mock()
    failed.json.return_value = {"description": "Bad Request: message is too long"}
    post.response.raise_for_status.side_effect = requests.HTTPError(
        "400 Client Error", response=failed
    )

    with pytest.raises(TelegramDeliveryError, match="message is too long"):
        telegram.send_telegram_message("hello")


def test_an_unreadable_error_body_does_not_hide_the_original_problem(post):
    failed = Mock()
    failed.json.side_effect = ValueError("not json")
    post.response.raise_for_status.side_effect = requests.HTTPError(
        "502 Bad Gateway", response=failed
    )

    with pytest.raises(TelegramDeliveryError, match="502 Bad Gateway"):
        telegram.send_telegram_message("hello")


def test_a_non_json_success_response_is_a_delivery_error(post):
    post.response.json.side_effect = ValueError("Expecting value")

    with pytest.raises(TelegramDeliveryError, match="Expecting value"):
        telegram.send_telegram_message("hello")


# ------------------------------------------------------------- long messages


def test_a_short_message_is_sent_once_without_a_part_label(post, pauses):
    telegram.send_telegram_message("hello")

    assert sent_texts(post) == ["hello"]
    assert pauses == []


def test_a_long_report_is_sent_as_numbered_parts_in_order(post, pauses):
    lines = [f"Артикул НС-{number:07d}, цена изменилась" for number in range(300)]

    telegram.send_telegram_message("\n".join(lines))

    texts = sent_texts(post)
    assert len(texts) > 1
    assert texts[0].startswith(f"[1/{len(texts)}]\n")
    assert texts[-1].startswith(f"[{len(texts)}/{len(texts)}]\n")
    body = "\n".join(text.split("\n", 1)[1] for text in texts)
    assert body.split("\n") == lines


def test_every_part_fits_the_telegram_limit_including_its_label(post, pauses):
    codes = ", ".join(f"НС-{number:07d}" for number in range(2000))

    telegram.send_telegram_message(f"Были добавлены новые артикулы: {codes}")

    texts = sent_texts(post)
    assert len(texts) > 1
    assert all(
        len(text) <= telegram.load_settings().telegram_message_limit for text in texts
    )


def test_a_pause_separates_consecutive_parts(post, pauses):
    telegram.send_telegram_message("x" * 9000)

    assert len(pauses) == post.call_count - 1
    assert set(pauses) == {telegram.load_settings().pause_between_parts_seconds}


def test_a_failure_in_a_later_part_raises_after_earlier_parts_were_sent(
    post, pauses, token_url, token
):
    post.response.raise_for_status.side_effect = [
        None,
        requests.HTTPError(f"500 Server Error for url: {token_url}"),
    ]

    with pytest.raises(TelegramDeliveryError) as error:
        telegram.send_telegram_message("x" * 9000)

    assert post.call_count == 2
    assert token not in str(error.value)


# ------------------------------------------------------------- split_message


def test_text_within_the_limit_is_returned_unchanged():
    assert telegram.split_message("short text", limit=100) == ["short text"]


def test_text_exactly_at_the_limit_is_not_split():
    text = "a" * 50

    assert telegram.split_message(text, limit=50) == [text]


def test_lines_are_kept_whole_when_splitting_a_multiline_text():
    text = "aaaa\nbbbb\ncccc\ndddd"

    assert telegram.split_message(text, limit=10) == ["aaaa\nbbbb", "cccc\ndddd"]


def test_a_long_line_is_cut_after_a_comma_not_inside_an_item():
    text = "Были добавлены: " + ", ".join(f"НС-{number:03d}" for number in range(40))

    parts = telegram.split_message(text, limit=60)

    assert len(parts) > 1
    assert all(len(part) <= 60 for part in parts)
    assert all(part.endswith(",") for part in parts[:-1])
    rejoined = " ".join(parts)
    assert rejoined == text


def test_a_line_without_commas_is_cut_at_a_space():
    parts = telegram.split_message("one two three four five six", limit=12)

    assert parts == ["one two", "three four", "five six"]


def test_a_single_unbroken_word_is_hard_cut_as_a_last_resort():
    parts = telegram.split_message("x" * 25, limit=10)

    assert parts == ["x" * 10, "x" * 10, "x" * 5]


@pytest.mark.parametrize("limit", [7, 20, 100])
def test_no_content_is_lost_or_duplicated(limit):
    text = "alpha beta\ngamma, delta epsilon\n\nzeta eta theta iota kappa"

    parts = telegram.split_message(text, limit=limit)

    assert all(len(part) <= limit for part in parts)
    assert "".join("".join(parts).split()) == "".join(text.split())


# ------------------------------------------------------------- Retrying post requests


def test_success_first_try_no_retries(net, token):
    net.queue = [make_response(200)]
    send(token)
    assert net.requests == 1
    assert net.sleeps == []


def test_retries_503_then_succeeds(net, token):
    net.queue = [make_response(503), make_response(503), make_response(200)]
    send(token)
    assert net.requests == 3


def test_gives_up_after_total_retries(net, token):
    net.queue = [make_response(503) for _ in range(10)]
    with pytest.raises(TelegramDeliveryError) as exc:
        send(token)
    assert net.requests == 4
    assert token not in str(exc.value)
    assert exc.value.__cause__ is None


def test_exhausted_retries_keep_telegram_description(net, token):
    body = {"ok": False, "description": "Too Many Requests: retry later"}
    net.queue = [make_response(503, body) for _ in range(10)]
    with pytest.raises(
        TelegramDeliveryError, match="Too Many Requests: retry later"
    ) as exc:
        send(token)
    assert net.requests == 4
    assert token not in str(exc.value)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_statuses_from_forcelist_are_retried(net, status, token):
    net.queue = [make_response(status), make_response(200)]
    send(token)
    assert net.requests == 2


def test_400_is_not_retried(net, token):
    net.queue = [make_response(400, {"ok": False, "description": "Bad Request"})]
    with pytest.raises(TelegramDeliveryError, match="Bad Request"):
        send(token)
    assert net.requests == 1


@pytest.mark.parametrize(
    "status,description",
    [
        (401, "Unauthorized"),
        (404, "Not Found"),
    ],
)
def test_auth_and_not_found_are_not_retried(net, status, description, token):
    net.queue = [make_response(status, {"ok": False, "description": description})]
    with pytest.raises(TelegramDeliveryError, match=description) as exc:
        send(token)
    assert net.requests == 1
    assert net.sleeps == []
    assert token not in str(exc.value)


def test_ok_false_with_200_is_not_retried(net, token):
    net.queue = [make_response(200, {"ok": False})]
    with pytest.raises(TelegramDeliveryError, match="rejected"):
        send(token)
    assert net.requests == 1


def test_connection_error_is_retried(net, token):
    net.queue = [ProtocolError("connection aborted"), make_response(200)]
    send(token)
    assert net.requests == 2


def test_backoff_sleeps_between_retries(net, token):
    net.queue = [make_response(503), make_response(503), make_response(200)]
    send(token)
    assert len(net.sleeps) >= 1  # пауза есть только между повторами


def test_retry_after_header_is_respected(net, token):
    net.queue = [make_response(503, headers={"Retry-After": "7"}), make_response(200)]
    send(token)
    assert 7.0 in net.sleeps


def test_rate_limit_acquired_once_despite_retries(net, token):
    net.queue = [make_response(503), make_response(503), make_response(200)]
    send(token)
    assert net.requests == 3
    assert net.rate_calls == [
        ("kafka:9092", "notifications_bot", "telegram:admin_chat")
    ]
