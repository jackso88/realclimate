"""Tests for hiding articles that vanished from the supplier catalogue.

Covers the hide / un-hide life cycle in ``merge_records_into_current``, its
report lines, the persisted state codec, the full pipeline and the core
consumer's handling of the absent-articles state topic.
"""

from __future__ import annotations

from app.contracts.models import Envelope
from app.core import consumer, pipeline
from app.core.merge_current import (
    format_merge_report,
    merge_records_into_current,
    parse_current_csv,
    serialize_current_csv,
)
from app.core.models import CoreSettings, ProcessResult
from app.core.pipeline import (
    decode_absent_articles,
    encode_absent_articles,
    process_catalogue,
)
from app.core.tests.test_core_consumer import (
    FakeBus,
    FakePendingInputs,
    make_current,
    make_output,
    make_reference,
)
from app.core.tests.test_core_merge_current import (
    HEADER,
    make_current_row,
    make_excluded_record,
    make_record,
)
from app.messaging.topics import CORE_ABSENT_ARTICLES_STATE

ARTICLE = "article : Артикул"
HIDDEN = "hidden : Скрыто"
HIDE_LINE = "Артикул {} был скрыт по причине отсутствия в каталоге поставщика"
RETURN_LINE = "Артикул {} вновь появился в каталоге поставщика"
REFERENCE = b"code,model,stock,retail,dealer,unused,series,brand,type\n"


# --------------------------------------------------------------------------
# hiding articles that are missing from the supplier catalogue
# --------------------------------------------------------------------------


class TestHidingMissingArticles:
    def test_article_missing_from_supplier_is_hidden(self) -> None:
        current_rows = [
            make_current_row("NC-1", hidden="0"),
            make_current_row("NC-2", hidden="0"),
        ]

        result = merge_records_into_current(
            [make_record("NC-2")], HEADER, current_rows, {}
        )

        hidden = {row[ARTICLE]: row[HIDDEN] for row in result.rows}
        assert hidden == {"NC-1": "1", "NC-2": "0"}
        assert result.hidden_absent_articles == ["NC-1"]
        assert result.absent_articles == {"NC-1"}
        assert result.untouched_articles == []

    def test_hiding_changes_nothing_but_the_hidden_flag(self) -> None:
        current_rows = [make_current_row("NC-1", amount="3", price="70.00")]

        result = merge_records_into_current(
            [make_record("NC-2")], HEADER, current_rows, {}
        )

        row = result.rows[0]
        assert row[HIDDEN] == "1"
        assert row["amount : Количество"] == "3"
        assert row["price : Цена"] == "70.00"
        assert row["name : Название"] == "Untouched name for NC-1"

    def test_article_hidden_for_another_reason_is_not_tracked(self) -> None:
        current_rows = [make_current_row("NC-1", hidden="1")]

        result = merge_records_into_current(
            [make_record("NC-2")], HEADER, current_rows, {}
        )

        assert result.hidden_absent_articles == []
        assert result.absent_articles == set()
        assert result.untouched_articles == ["NC-1"]

    def test_tracked_article_stays_tracked_without_a_repeat_message(self) -> None:
        current_rows = [make_current_row("NC-1", hidden="1")]

        result = merge_records_into_current(
            [make_record("NC-2")], HEADER, current_rows, {}, absent_articles={"NC-1"}
        )

        assert result.hidden_absent_articles == []
        assert result.absent_articles == {"NC-1"}
        assert result.rows[0][HIDDEN] == "1"

    def test_manually_unhidden_tracked_article_is_hidden_again(self) -> None:
        current_rows = [make_current_row("NC-1", hidden="0")]

        result = merge_records_into_current(
            [make_record("NC-2")], HEADER, current_rows, {}, absent_articles={"NC-1"}
        )

        assert result.hidden_absent_articles == ["NC-1"]
        assert result.rows[0][HIDDEN] == "1"

    def test_empty_supplier_catalogue_hides_nothing(self) -> None:
        current_rows = [
            make_current_row("NC-1", hidden="0"),
            make_current_row("NC-2", hidden="1"),
        ]

        result = merge_records_into_current(
            [], HEADER, current_rows, {}, absent_articles={"NC-2"}
        )

        assert [row[HIDDEN] for row in result.rows] == ["0", "1"]
        assert result.hidden_absent_articles == []
        assert result.absent_articles == {"NC-2"}

    def test_ambiguous_rename_candidate_is_not_hidden(self) -> None:
        duplicate_map = {
            ("НС-1", "RAS-B", 1): "НС-1-D01",
            ("НС-2", "RAS-B", 1): "НС-2-D01",
        }
        current_rows = [make_current_row("НС-1-D01", hidden="0")]
        records = [
            make_record("НС-3333", model="RAS-B"),
            make_record("НС-4444", model="RAS-B"),
        ]

        result = merge_records_into_current(
            records, HEADER, current_rows, duplicate_map
        )

        assert result.rows[0][HIDDEN] == "0"
        assert result.hidden_absent_articles == []
        assert result.untouched_articles == ["НС-1-D01"]

    def test_article_dropped_by_cleaning_is_removed_not_hidden(self) -> None:
        current_rows = [make_current_row("NC-1", hidden="0")]

        result = merge_records_into_current(
            [make_record("NC-2")],
            HEADER,
            current_rows,
            {},
            excluded=[make_excluded_record("NC-1")],
            absent_articles={"NC-1"},
        )

        assert [article for article, _ in result.removed_articles] == ["NC-1"]
        assert result.hidden_absent_articles == []
        assert result.absent_articles == set()

    def test_row_deleted_from_the_cms_leaves_the_tracking_state(self) -> None:
        result = merge_records_into_current(
            [make_record("NC-2")], HEADER, [], {}, absent_articles={"NC-GONE"}
        )

        assert result.absent_articles == set()

    def test_catalogue_without_a_hidden_column_hides_nothing(self) -> None:
        header = [cell for cell in HEADER if not cell.startswith("hidden")]
        row = {cell: "" for cell in header}
        row[ARTICLE] = "NC-1"

        result = merge_records_into_current([make_record("NC-2")], header, [row], {})

        assert result.hidden_absent_articles == []
        assert result.untouched_articles == ["NC-1"]
        assert result.absent_articles == set()


# --------------------------------------------------------------------------
# articles that come back to the supplier catalogue
# --------------------------------------------------------------------------


class TestReappearedArticles:
    def test_tracked_article_that_returns_is_unhidden(self) -> None:
        current_rows = [make_current_row("NC-1", price="50.00", hidden="1")]

        result = merge_records_into_current(
            [make_record("NC-1", retail_price=50.0)],
            HEADER,
            current_rows,
            {},
            absent_articles={"NC-1"},
        )

        assert result.rows[0][HIDDEN] == "0"
        assert result.reappeared_articles == ["NC-1"]
        assert result.hidden_changes == []
        # Tracking continues until the CMS export shows the flag cleared.
        assert result.absent_articles == {"NC-1"}

    def test_tracking_stops_once_the_cms_shows_the_article_visible(self) -> None:
        current_rows = [make_current_row("NC-1", price="50.00", hidden="0")]

        result = merge_records_into_current(
            [make_record("NC-1", retail_price=50.0)],
            HEADER,
            current_rows,
            {},
            absent_articles={"NC-1"},
        )

        assert result.reappeared_articles == []
        assert result.absent_articles == set()

    def test_article_hidden_by_hand_is_not_unhidden_when_it_returns(self) -> None:
        current_rows = [make_current_row("NC-1", price="50.00", hidden="1")]

        result = merge_records_into_current(
            [make_record("NC-1", retail_price=60.0)], HEADER, current_rows, {}
        )

        assert result.rows[0][HIDDEN] == "1"
        assert result.reappeared_articles == []

    def test_returning_article_with_zero_price_stays_hidden(self) -> None:
        current_rows = [make_current_row("NC-1", price="50.00", hidden="1")]

        result = merge_records_into_current(
            [make_record("NC-1", retail_price=0.0)],
            HEADER,
            current_rows,
            {},
            absent_articles={"NC-1"},
        )

        assert result.rows[0][HIDDEN] == "1"
        assert result.reappeared_articles == ["NC-1"]
        assert result.absent_articles == set()

    def test_renamed_returning_article_uses_its_new_code(self) -> None:
        duplicate_map = {("НС-1", "RAS-B", 1): "НС-1-D01"}
        current_rows = [make_current_row("НС-1-D01", price="10.00", hidden="1")]
        record = make_record("НС-9999", model="RAS-B", retail_price=250.0)

        result = merge_records_into_current(
            [record],
            HEADER,
            current_rows,
            duplicate_map,
            absent_articles={"НС-1-D01"},
        )

        assert result.rows[0][HIDDEN] == "0"
        assert result.reappeared_articles == ["НС-9999"]
        assert result.absent_articles == {"НС-9999"}


# --------------------------------------------------------------------------
# report lines
# --------------------------------------------------------------------------


class TestReport:
    def test_hide_message_names_the_reason(self) -> None:
        result = merge_records_into_current(
            [make_record("NC-2")], HEADER, [make_current_row("NC-1")], {}
        )

        lines = format_merge_report(result)

        assert HIDE_LINE.format("NC-1") in lines
        assert lines.index(HIDE_LINE.format("NC-1")) < len(lines) - 1
        assert lines[-1].startswith("Были добавлены новые артикулы")

    def test_reappeared_message(self) -> None:
        current_rows = [make_current_row("NC-1", price="50.00", hidden="1")]
        result = merge_records_into_current(
            [make_record("NC-1", retail_price=50.0)],
            HEADER,
            current_rows,
            {},
            absent_articles={"NC-1"},
        )

        lines = format_merge_report(result)

        assert RETURN_LINE.format("NC-1") in lines
        assert not any("был скрыт по причине" in line for line in lines)

    def test_tracked_hidden_article_produces_no_lines(self) -> None:
        current_rows = [
            make_current_row("NC-1", hidden="1"),
            make_current_row("NC-2", amount="5", price="100.00"),
        ]
        record = make_record("NC-2", availability="5", retail_price=100.0)

        result = merge_records_into_current(
            [record], HEADER, current_rows, {}, absent_articles={"NC-1"}
        )

        assert format_merge_report(result) == []


# --------------------------------------------------------------------------
# persisted state codec
# --------------------------------------------------------------------------


class TestAbsentStateCodec:
    def test_round_trip(self) -> None:
        articles = {"NC-2", "NC-1"}
        assert decode_absent_articles(encode_absent_articles(articles)) == articles

    def test_encoding_is_sorted_and_json_safe(self) -> None:
        assert encode_absent_articles({"B", "A"}) == {"articles": ["A", "B"]}

    def test_empty_payload_decodes_to_empty_set(self) -> None:
        assert decode_absent_articles({}) == set()


# --------------------------------------------------------------------------
# full pipeline
# --------------------------------------------------------------------------


def run_pipeline(monkeypatch, kept_codes, current, absent):
    kept = [make_record(code) for code in kept_codes]
    monkeypatch.setattr(
        pipeline,
        "process_rows",
        lambda rows, mapping: ProcessResult(kept=kept, updated_map=mapping),
    )
    return process_catalogue(REFERENCE, current, {}, absent)


def hidden_flags(processed_csv):
    _, rows = parse_current_csv(processed_csv)
    return {row[ARTICLE]: row[HIDDEN] for row in rows}


def test_hide_and_restore_life_cycle_across_runs(monkeypatch):
    rows = [
        make_current_row("NC-1", price="100.00", amount="5.0"),
        make_current_row("NC-2", price="100.00", amount="5.0"),
    ]
    current = serialize_current_csv(HEADER, rows)

    first = run_pipeline(monkeypatch, ["NC-2"], current, set())
    assert HIDE_LINE.format("NC-1") in first.detailed_changes
    assert first.updated_absent_articles == {"NC-1"}
    assert hidden_flags(first.processed_csv) == {"NC-1": "1", "NC-2": "0"}

    # Nothing changed at the supplier: the next run is silent and idempotent.
    second = run_pipeline(
        monkeypatch, ["NC-2"], first.processed_csv, first.updated_absent_articles
    )
    assert second.detailed_changes == []
    assert second.updated_absent_articles == {"NC-1"}

    # The article returns: it is un-hidden and reported once.
    third = run_pipeline(
        monkeypatch,
        ["NC-1", "NC-2"],
        second.processed_csv,
        second.updated_absent_articles,
    )
    assert RETURN_LINE.format("NC-1") in third.detailed_changes
    assert hidden_flags(third.processed_csv) == {"NC-1": "0", "NC-2": "0"}

    # Once the CMS export shows it visible, tracking ends without a message.
    fourth = run_pipeline(
        monkeypatch,
        ["NC-1", "NC-2"],
        third.processed_csv,
        third.updated_absent_articles,
    )
    assert fourth.detailed_changes == []
    assert fourth.updated_absent_articles == set()


# --------------------------------------------------------------------------
# core consumer
# --------------------------------------------------------------------------


def test_core_passes_absent_state_to_the_pipeline_and_republishes_it(
    monkeypatch, tmp_path
):
    received = []
    output = make_output().model_copy(
        update={"updated_absent_articles": {"NC-9", "NC-1"}}
    )
    monkeypatch.setattr(
        consumer,
        "process_catalogue",
        lambda reference, current, duplicate_map, absent: (
            received.append(absent) or output
        ),
    )
    state = Envelope.create("absent_articles_state", {"articles": ["NC-1"]})
    settings = CoreSettings(excluded_csv_path=tmp_path / "excluded.csv")
    bus = FakeBus(absent_state=state)
    pending = FakePendingInputs()

    consumer.handle_process(make_reference(), bus, settings, pending)
    consumer.handle_process(make_current(), bus, settings, pending)

    assert received == [{"NC-1"}]
    _, message, key = next(
        event for event in bus.published if event[0] == CORE_ABSENT_ARTICLES_STATE
    )
    assert message.payload == {"articles": ["NC-1", "NC-9"]}
    assert key == "absent-articles"


def test_core_starts_with_empty_absent_state_when_topic_is_empty(
    monkeypatch, tmp_path
):
    received = []
    monkeypatch.setattr(
        consumer,
        "process_catalogue",
        lambda reference, current, duplicate_map, absent: (
            received.append(absent) or make_output()
        ),
    )
    settings = CoreSettings(excluded_csv_path=tmp_path / "excluded.csv")
    bus = FakeBus()
    pending = FakePendingInputs()

    consumer.handle_process(make_reference(), bus, settings, pending)
    consumer.handle_process(make_current(), bus, settings, pending)

    assert received == [set()]
    published = next(
        event[1] for event in bus.published if event[0] == CORE_ABSENT_ARTICLES_STATE
    )
    assert published.payload == {"articles": []}
