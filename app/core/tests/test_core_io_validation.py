"""Tests for CSV byte parsing and serialization at the core's boundaries."""

import pytest

from app.core.exceptions import CurrentCatalogError, SourceDataError
from app.core.merge_current import parse_current_csv, serialize_current_csv
from app.core.models import ExcludedRecord, ProductRecord
from app.core.source_io import parse_source_csv, serialize_excluded_csv

HEADER = "нс-код,Модель,Наличие,Розница,Дилер,,Серия,Бренд,Тип\n"


def test_source_csv_skips_the_header_and_pads_rows_to_nine_cells():
    content = (HEADER + "НС-1,Модель A\n").encode("utf-8")

    rows = parse_source_csv(content)

    assert rows == [("НС-1", "Модель A", None, None, None, None, None, None, None)]


def test_source_csv_turns_empty_cells_into_none():
    content = (HEADER + ",Группа,,,,,,,\n").encode("utf-8")

    row = parse_source_csv(content)[0]

    assert row[0] is None
    assert row[1] == "Группа"


def test_source_csv_accepts_a_utf8_bom():
    content = "\ufeff".encode("utf-8") + (HEADER + "НС-1,A\n").encode("utf-8")

    assert parse_source_csv(content)[0][0] == "НС-1"


def test_source_csv_with_only_a_header_has_no_rows():
    assert parse_source_csv(HEADER.encode("utf-8")) == []


def test_source_csv_rejects_invalid_utf8():
    with pytest.raises(SourceDataError, match="Could not parse source CSV"):
        parse_source_csv(b"\xff\xfe\x00broken")


def test_source_csv_rejects_oversized_fields():
    with pytest.raises(SourceDataError, match="Could not parse source CSV"):
        parse_source_csv(b"header\n" + b"x" * 200_000)


def make_excluded(**overrides):
    values = {
        "code": "НС-1",
        "model": "Модель",
        "availability": "0",
        "retail_price": None,
        "dealer_price": 5.0,
        "series": "",
        "brand": "Бренд",
        "type_": "Аксессуары",
        "reason": "Тип содержит «аксессуары»",
        "category": "Группа",
    }
    values.update(overrides)
    return ExcludedRecord(**values)


def test_excluded_csv_has_a_bom_a_header_and_semicolons():
    content = serialize_excluded_csv([make_excluded()])

    text = content.decode("utf-8")
    lines = text.splitlines()
    assert text.startswith("\ufeff")
    assert lines[0].lstrip("\ufeff").endswith("Категория;Причина исключения")
    assert lines[1].startswith("НС-1;Модель;0;;5.0;")
    assert lines[1].endswith("Группа;Тип содержит «аксессуары»")


def test_excluded_csv_without_records_still_contains_the_header():
    content = serialize_excluded_csv([])

    assert len(content.decode("utf-8").splitlines()) == 1


def test_product_record_row_uses_the_source_column_names():
    record = ProductRecord(
        code="НС-1",
        model="М",
        availability="3",
        retail_price=10.0,
        dealer_price=7.0,
        series="С",
        brand="Б",
        type_="Т",
        category="К",
    )

    row = record.as_csv_row()

    assert row["нс-код"] == "НС-1"
    assert row["Розница, BYN"] == 10.0
    assert row["Дилер, BYN"] == 7.0
    assert row["Категория"] == "К"


def test_excluded_record_row_carries_the_reason():
    row = make_excluded(reason="Дублирование модели").as_csv_row()

    assert row["Причина исключения"] == "Дублирование модели"
    assert row["Розница, BYN"] is None


def test_current_csv_round_trips_including_multiline_cells():
    header = ["name : Название", "body : Описание"]
    rows = [{"name : Название": "A;B", "body : Описание": "line 1\nline 2"}]

    parsed = parse_current_csv(serialize_current_csv(header, rows))

    assert parsed == (header, rows)


def test_current_csv_serialization_starts_with_a_bom():
    content = serialize_current_csv(["a : A"], [{"a : A": "1"}])

    assert content.startswith("\ufeff".encode("utf-8"))


def test_current_csv_rejects_invalid_utf8():
    with pytest.raises(CurrentCatalogError, match="Could not parse current catalog"):
        parse_current_csv(b"\xff\xfe\x00broken")


def test_current_csv_rejects_oversized_fields():
    with pytest.raises(CurrentCatalogError):
        parse_current_csv(b"a;b\n" + b"x" * 200_000)
