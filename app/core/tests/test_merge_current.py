# -*- coding: utf-8 -*-
"""Pytest suite for merge_current.py.

Run with::

    pytest test_merge_current.py -v
"""

from __future__ import annotations

from pathlib import Path

from app.core.merge_current import (
    build_new_row,
    column_short_key,
    format_merge_report,
    is_anomalous_price_change,
    load_current_csv,
    merge_records_into_current,
    write_current_csv,
)
from app.core.models import ExcludedRecord, ProductRecord

# A minimal but representative header, using the same "key : Label"
# shape as the real current.csv, restricted to the columns the merge
# logic actually reads/writes plus a couple of "untouched" ones to
# prove those survive round-trips unharmed.
HEADER = [
    "name : Название",
    "vendor : Производитель",
    "supplier : Поставщик",
    "image : Иллюстрация",
    "article : Артикул",
    "folder : Категория",
    "hidden : Скрыто",
    "amount : Количество",
    "amount_min : Мин. кол-во для заказа",
    "amount_multiplicity : Кратность добавления в заказ",
    "price : Цена",
    "currency : Валюта",
    "sef_url : ЧПУ",
]


def make_record(
    code: str,
    model: str = "Model",
    retail_price: float = 100.0,
    availability: str = "5",
    brand: str = "Brand",
    series: str = "Series",
    type_: str = "Type",
    category: str = "Category",
    folder: str = "Каталог кондиционеров,Сплит-системы",
) -> ProductRecord:
    return ProductRecord(
        code=code,
        model=model,
        availability=availability,
        retail_price=retail_price,
        dealer_price=retail_price / 2,
        series=series,
        brand=brand,
        type_=type_,
        category=category,
        folder=folder,
    )


def make_current_row(
    article: str, amount: str = "1", price: str = "50.00", **extra: str
) -> dict:
    row = {h: "" for h in HEADER}
    row["article : Артикул"] = article
    row["amount : Количество"] = amount
    row["price : Цена"] = price
    row["name : Название"] = extra.get("name", f"Untouched name for {article}")
    row["image : Иллюстрация"] = extra.get("image", "https://example.com/old.png")
    return row


def make_excluded_record(
    code: str,
    model: str = "Model",
    reason: str = "Цена не определена или равна нулю (Розница)",
) -> ExcludedRecord:
    return ExcludedRecord(
        code=code,
        model=model,
        availability="0",
        retail_price=None,
        dealer_price=None,
        series="Series",
        brand="Brand",
        type_="Type",
        reason=reason,
    )


# --------------------------------------------------------------------------
# column_short_key
# --------------------------------------------------------------------------


class TestColumnShortKey:
    def test_extracts_key_before_colon(self) -> None:
        assert column_short_key("price : Цена") == "price"

    def test_strips_surrounding_whitespace(self) -> None:
        assert column_short_key("  article  :  Артикул  ") == "article"


# --------------------------------------------------------------------------
# current.csv read/write round-trip
# --------------------------------------------------------------------------


class TestCurrentCsvRoundTrip:
    def test_write_then_load_preserves_header_and_rows(self, tmp_path: Path) -> None:
        rows = [make_current_row("NC-1"), make_current_row("NC-2")]
        path = tmp_path / "current.csv"

        write_current_csv(HEADER, rows, path)
        loaded_header, loaded_rows = load_current_csv(path)

        assert loaded_header == HEADER
        assert loaded_rows == rows

    def test_cyrillic_round_trips_cleanly(self, tmp_path: Path) -> None:
        rows = [make_current_row("НС-1", name="Кондиционер Electrolux")]
        path = tmp_path / "current.csv"

        write_current_csv(HEADER, rows, path)
        _, loaded_rows = load_current_csv(path)

        assert loaded_rows[0]["name : Название"] == "Кондиционер Electrolux"


# --------------------------------------------------------------------------
# build_new_row
# --------------------------------------------------------------------------


class TestBuildNewRow:
    def test_name_is_brand_series_model_joined_without_type(self) -> None:
        record = make_record("NC-1", model="M1", brand="Br", series="Se", type_="Ty")
        header_by_key = {h.split(":", 1)[0].strip(): h for h in HEADER}
        row = build_new_row(record, header_by_key, existing_sef_urls=set())
        assert row["name : Название"] == "Br Se M1"
        assert "Ty" not in row["name : Название"]

    def test_empty_series_is_skipped_in_name(self) -> None:
        record = make_record("NC-1", model="M1", brand="Br", series="", type_="Ty")
        header_by_key = {h.split(":", 1)[0].strip(): h for h in HEADER}
        row = build_new_row(record, header_by_key, existing_sef_urls=set())
        assert row["name : Название"] == "Br M1"

    def test_fixed_fields(self) -> None:
        record = make_record("NC-1")
        header_by_key = {h.split(":", 1)[0].strip(): h for h in HEADER}
        row = build_new_row(record, header_by_key, existing_sef_urls=set())
        assert row["supplier : Поставщик"] == "Русклимат-М"
        assert row["currency : Валюта"] == "BYN"
        assert row["amount_min : Мин. кол-во для заказа"] == "1"
        assert row["amount_multiplicity : Кратность добавления в заказ"] == "1"
        assert row["hidden : Скрыто"] == "0"

    def test_folder_uses_the_mapped_folder_not_the_raw_category(self) -> None:
        record = make_record(
            "NC-1",
            category="Полупромышленные системы Ballu On/Off Universal III",
            folder="Каталог кондиционеров,Полупромышленные кондиционеры",
        )
        header_by_key = {h.split(":", 1)[0].strip(): h for h in HEADER}
        row = build_new_row(record, header_by_key, existing_sef_urls=set())
        assert (
            row["folder : Категория"]
            == "Каталог кондиционеров,Полупромышленные кондиционеры"
        )

    def test_price_is_formatted_with_two_decimals(self) -> None:
        record = make_record("NC-1", retail_price=2990.0)
        header_by_key = {h.split(":", 1)[0].strip(): h for h in HEADER}
        row = build_new_row(record, header_by_key, existing_sef_urls=set())
        assert row["price : Цена"] == "2990.00"

    def test_non_numeric_availability_becomes_zero_amount(self) -> None:
        record = make_record("NC-1", availability="наличие уточняйте")
        header_by_key = {h.split(":", 1)[0].strip(): h for h in HEADER}
        row = build_new_row(record, header_by_key, existing_sef_urls=set())
        assert row["amount : Количество"] == "0.0"

    def test_sef_url_is_unique_among_existing(self) -> None:
        record = make_record("NC-1", brand="Foo", series="", type_="", model="Bar")
        header_by_key = {h.split(":", 1)[0].strip(): h for h in HEADER}
        existing = {"glavnaya-magazina/product/foo-bar"}
        row = build_new_row(record, header_by_key, existing_sef_urls=existing)
        assert row["sef_url : ЧПУ"] == "glavnaya-magazina/product/foo-bar-2"


# --------------------------------------------------------------------------
# merge_records_into_current
# --------------------------------------------------------------------------


class TestMergeRecordsIntoCurrent:
    def test_existing_article_only_gets_amount_and_price_updated(self) -> None:
        current_rows = [make_current_row("NC-1", amount="1", price="50.00")]
        record = make_record("NC-1", availability="7", retail_price=123.0)

        result = merge_records_into_current([record], HEADER, current_rows, {})

        assert result.updated_articles == ["NC-1"]
        assert result.added_articles == []
        row = result.rows[0]
        assert row["amount : Количество"] == "7.0"
        assert row["price : Цена"] == "123.00"
        # Untouched fields must survive exactly as they were.
        assert row["name : Название"] == "Untouched name for NC-1"
        assert row["image : Иллюстрация"] == "https://example.com/old.png"

    def test_unknown_article_is_added_as_new_row(self) -> None:
        record = make_record("NC-NEW", model="Fresh")
        result = merge_records_into_current([record], HEADER, [], {})

        assert result.added_articles == ["NC-NEW"]
        assert result.updated_articles == []
        assert len(result.rows) == 1
        assert result.rows[0]["article : Артикул"] == "NC-NEW"

    def test_article_missing_from_current_csv_stays_untouched(self) -> None:
        current_rows = [make_current_row("NC-OLD")]
        result = merge_records_into_current([], HEADER, current_rows, {})

        assert result.untouched_articles == ["NC-OLD"]
        assert result.rows == current_rows

    def test_stale_duplicate_code_is_renamed_via_model_match(self) -> None:
        # Simulate: НС-1 used to be a duplicate; "-D01" was assigned to
        # model "RAS-B". The supplier has since fixed the duplication
        # and RAS-B now ships under a brand-new real code.
        duplicate_map = {("НС-1", "RAS-B", 1): "НС-1-D01"}
        current_rows = [make_current_row("НС-1-D01", amount="1", price="10.00")]
        new_record = make_record(
            "НС-9999", model="RAS-B", retail_price=250.0, availability="3"
        )

        result = merge_records_into_current(
            [new_record], HEADER, current_rows, duplicate_map
        )

        assert result.renamed_articles == [("НС-1-D01", "НС-9999")]
        assert result.added_articles == []
        row = result.rows[0]
        assert row["article : Артикул"] == "НС-9999"
        assert row["price : Цена"] == "250.00"
        assert row["amount : Количество"] == "3.0"
        # Non-price/amount fields are still untouched by a rename.
        assert row["name : Название"] == "Untouched name for НС-1-D01"

    def test_ambiguous_rename_candidates_are_left_untouched(self) -> None:
        # Two different assigned codes both recorded the same model —
        # should not happen in practice, but if it does we must not
        # guess; leave the row alone.
        duplicate_map = {
            ("НС-1", "RAS-B", 1): "НС-1-D01",
            ("НС-2", "RAS-B", 1): "НС-2-D01",
        }
        current_rows = [make_current_row("НС-1-D01")]
        candidate_a = make_record("НС-3333", model="RAS-B")
        candidate_b = make_record("НС-4444", model="RAS-B")

        result = merge_records_into_current(
            [candidate_a, candidate_b], HEADER, current_rows, duplicate_map
        )

        assert result.untouched_articles == ["НС-1-D01"]
        # Both candidates, having no home, are added as new rows.
        assert sorted(result.added_articles) == ["НС-3333", "НС-4444"]

    def test_direct_match_takes_priority_over_rename_heuristics(self) -> None:
        # If the "-D01" code itself is still present in today's data,
        # it's a normal update, not a rename — even if it's also in
        # the duplicate map.
        duplicate_map = {("НС-1", "RAS-B", 1): "НС-1-D01"}
        current_rows = [make_current_row("НС-1-D01", amount="1", price="10.00")]
        record = make_record(
            "НС-1-D01", model="RAS-B", retail_price=88.0, availability="2"
        )

        result = merge_records_into_current(
            [record], HEADER, current_rows, duplicate_map
        )

        assert result.updated_articles == ["НС-1-D01"]
        assert result.renamed_articles == []

    def test_mixed_batch_update_add_and_rename_together(self) -> None:
        duplicate_map = {("НС-1", "RAS-B", 1): "НС-1-D01"}
        current_rows = [
            make_current_row("NC-KEEP", amount="1", price="10.00"),
            make_current_row("НС-1-D01", amount="1", price="10.00"),
            make_current_row("NC-GONE"),
        ]
        records = [
            make_record("NC-KEEP", retail_price=11.0, availability="9"),  # update
            make_record("НС-5555", model="RAS-B", retail_price=99.0),  # rename target
            make_record("NC-BRAND-NEW", model="Fresh"),  # add
        ]

        result = merge_records_into_current(
            records, HEADER, current_rows, duplicate_map
        )

        assert result.updated_articles == ["NC-KEEP"]
        assert result.renamed_articles == [("НС-1-D01", "НС-5555")]
        assert result.added_articles == ["NC-BRAND-NEW"]
        assert result.untouched_articles == ["NC-GONE"]
        assert len(result.rows) == 4


# --------------------------------------------------------------------------
# removal of articles whose row was dropped by this run's cleaning
# --------------------------------------------------------------------------


class TestRemovalOfExcludedArticles:
    def test_bare_code_match_is_removed(self) -> None:
        current_rows = [make_current_row("NC-1")]
        excluded = [make_excluded_record("NC-1")]

        result = merge_records_into_current(
            [], HEADER, current_rows, {}, excluded=excluded
        )

        assert result.removed_articles == [
            ("NC-1", "Цена не определена или равна нулю (Розница)")
        ]
        assert result.rows == []
        assert result.untouched_articles == []

    def test_removal_reason_matches_the_excluded_records_reason(self) -> None:
        current_rows = [make_current_row("NC-1")]
        excluded = [make_excluded_record("NC-1", reason="Дублирование модели")]

        result = merge_records_into_current(
            [], HEADER, current_rows, {}, excluded=excluded
        )

        assert result.removed_articles == [("NC-1", "Дублирование модели")]

    def test_duplicate_mapping_variant_is_also_removed(self) -> None:
        # The excluded row's bare code is "NC-1", but current.csv
        # actually holds the "-D01" variant that duplicate_map
        # recorded for that exact (code, model) pair.
        duplicate_map = {("NC-1", "RAS-B", 1): "NC-1-D01"}
        current_rows = [make_current_row("NC-1-D01")]
        excluded = [make_excluded_record("NC-1", model="RAS-B")]

        result = merge_records_into_current(
            [], HEADER, current_rows, duplicate_map, excluded=excluded
        )

        assert result.removed_articles == [
            ("NC-1-D01", "Цена не определена или равна нулю (Розница)")
        ]

    def test_a_still_kept_article_sharing_the_same_bare_code_is_not_removed(
        self,
    ) -> None:
        # NC-1's group: one model got excluded, but another model with
        # the same original code is still kept (and bare-assigned to
        # NC-1 itself). The live row must survive.
        current_rows = [make_current_row("NC-1", amount="5", price="100.00")]
        kept_record = make_record("NC-1", model="ModelKept", retail_price=100.0)
        excluded = [make_excluded_record("NC-1", model="ModelExcluded")]

        result = merge_records_into_current(
            [kept_record], HEADER, current_rows, {}, excluded=excluded
        )

        assert result.removed_articles == []
        assert result.updated_articles == ["NC-1"]
        assert [r["article : Артикул"] for r in result.rows] == ["NC-1"]

    def test_unrelated_current_row_is_not_removed(self) -> None:
        current_rows = [make_current_row("NC-UNRELATED")]
        excluded = [make_excluded_record("NC-1")]

        result = merge_records_into_current(
            [], HEADER, current_rows, {}, excluded=excluded
        )

        assert result.removed_articles == []
        assert result.untouched_articles == ["NC-UNRELATED"]

    def test_no_excluded_records_means_no_removals(self) -> None:
        current_rows = [make_current_row("NC-1")]
        result = merge_records_into_current([], HEADER, current_rows, {})
        assert result.removed_articles == []
        assert result.untouched_articles == ["NC-1"]

    def test_removed_article_message_is_reported(self) -> None:
        current_rows = [make_current_row("NC-1")]
        excluded = [make_excluded_record("NC-1", reason="Дублирование модели")]

        result = merge_records_into_current(
            [], HEADER, current_rows, {}, excluded=excluded
        )
        lines = format_merge_report(result)

        assert "Артикул NC-1 был исключен по причине: 'Дублирование модели'" in lines


# --------------------------------------------------------------------------
# is_anomalous_price_change
# --------------------------------------------------------------------------


class TestIsAnomalousPriceChange:
    def test_small_change_is_not_anomalous(self) -> None:
        assert is_anomalous_price_change(100.0, 110.0) is False

    def test_move_over_fifty_percent_up_is_anomalous(self) -> None:
        assert is_anomalous_price_change(100.0, 151.0) is True

    def test_move_over_fifty_percent_down_is_anomalous(self) -> None:
        assert is_anomalous_price_change(100.0, 49.0) is True

    def test_exactly_fifty_percent_is_not_anomalous(self) -> None:
        # Strictly greater than 50%, not "50% or more".
        assert is_anomalous_price_change(100.0, 150.0) is False

    def test_unparseable_old_price_is_anomalous(self) -> None:
        assert is_anomalous_price_change(None, 100.0) is True

    def test_zero_old_price_is_anomalous(self) -> None:
        assert is_anomalous_price_change(0.0, 10.0) is True


# --------------------------------------------------------------------------
# price/amount change tracking on the MergeResult
# --------------------------------------------------------------------------


class TestChangeTracking:
    def test_price_change_is_recorded(self) -> None:
        current_rows = [make_current_row("NC-1", amount="5", price="100.00")]
        record = make_record("NC-1", availability="5", retail_price=120.0)
        result = merge_records_into_current([record], HEADER, current_rows, {})
        assert result.price_changes == [("NC-1", 100.0, 120.0)]

    def test_unchanged_price_is_not_recorded(self) -> None:
        current_rows = [make_current_row("NC-1", amount="5", price="100.00")]
        record = make_record("NC-1", availability="5", retail_price=100.0)
        result = merge_records_into_current([record], HEADER, current_rows, {})
        assert result.price_changes == []

    def test_amount_change_is_recorded(self) -> None:
        current_rows = [make_current_row("NC-1", amount="5", price="100.00")]
        record = make_record("NC-1", availability="9", retail_price=100.0)
        result = merge_records_into_current([record], HEADER, current_rows, {})
        assert result.amount_changes == [("NC-1", 5.0, 9.0)]

    def test_anomalous_price_change_is_flagged(self) -> None:
        current_rows = [make_current_row("NC-1", amount="5", price="100.00")]
        record = make_record("NC-1", availability="5", retail_price=300.0)
        result = merge_records_into_current([record], HEADER, current_rows, {})
        assert result.anomalous_price_articles == ["NC-1"]

    def test_moderate_price_change_is_not_flagged(self) -> None:
        current_rows = [make_current_row("NC-1", amount="5", price="100.00")]
        record = make_record("NC-1", availability="5", retail_price=110.0)
        result = merge_records_into_current([record], HEADER, current_rows, {})
        assert result.anomalous_price_articles == []

    def test_rename_reports_changes_under_the_new_code(self) -> None:
        duplicate_map = {("НС-1", "RAS-B", 1): "НС-1-D01"}
        current_rows = [make_current_row("НС-1-D01", amount="1", price="10.00")]
        new_record = make_record(
            "НС-9999", model="RAS-B", retail_price=15.0, availability="2"
        )
        result = merge_records_into_current(
            [new_record], HEADER, current_rows, duplicate_map
        )
        assert result.price_changes == [("НС-9999", 10.0, 15.0)]
        assert result.amount_changes == [("НС-9999", 1.0, 2.0)]

    def test_brand_new_articles_produce_no_change_entries(self) -> None:
        record = make_record("NC-NEW", model="Fresh")
        result = merge_records_into_current([record], HEADER, [], {})
        assert result.price_changes == []
        assert result.amount_changes == []
        assert result.anomalous_price_articles == []


# --------------------------------------------------------------------------
# format_merge_report
# --------------------------------------------------------------------------


class TestFormatMergeReport:
    def test_price_change_message(self) -> None:
        current_rows = [make_current_row("NC-1", amount="5", price="100.00")]
        record = make_record("NC-1", availability="5", retail_price=120.0)
        result = merge_records_into_current([record], HEADER, current_rows, {})
        lines = format_merge_report(result)
        assert "Артикул NC-1, цена изменилась с 100.00 на 120.00" in lines

    def test_amount_change_message(self) -> None:
        current_rows = [make_current_row("NC-1", amount="5", price="100.00")]
        record = make_record("NC-1", availability="9", retail_price=100.0)
        result = merge_records_into_current([record], HEADER, current_rows, {})
        lines = format_merge_report(result)
        assert "Артикул NC-1, количество изменилось с 5 на 9" in lines

    def test_anomaly_warning_follows_its_price_line(self) -> None:
        current_rows = [make_current_row("NC-1", amount="5", price="100.00")]
        record = make_record("NC-1", availability="5", retail_price=1000.0)
        result = merge_records_into_current([record], HEADER, current_rows, {})
        lines = format_merge_report(result)
        price_idx = lines.index("Артикул NC-1, цена изменилась с 100.00 на 1000.00")
        assert (
            lines[price_idx + 1]
            == "\nВНИМАНИЕ!!!! NC-1, аномальное изменение цены!!!\n"
        )

    def test_new_articles_are_listed_on_one_line(self) -> None:
        records = [make_record("NC-A", model="A"), make_record("NC-B", model="B")]
        result = merge_records_into_current(records, HEADER, [], {})
        lines = format_merge_report(result)
        assert "Были добавлены новые артикулы: \nNC-A\nNC-B" in lines

    def test_no_changes_produces_no_lines(self) -> None:
        current_rows = [make_current_row("NC-1", amount="5", price="100.00")]
        record = make_record("NC-1", availability="5", retail_price=100.0)
        result = merge_records_into_current([record], HEADER, current_rows, {})
        assert format_merge_report(result) == []

    def test_unparseable_old_price_shown_as_placeholder(self) -> None:
        current_rows = [make_current_row("NC-1", amount="5", price="уточняйте")]
        record = make_record("NC-1", availability="5", retail_price=100.0)
        result = merge_records_into_current([record], HEADER, current_rows, {})
        lines = format_merge_report(result)
        assert "Артикул NC-1, цена изменилась с не указана на 100.00" in lines
