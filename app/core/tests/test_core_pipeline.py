"""Tests for in-memory source parsing and output serialization."""

import csv
import io

from app.core.merge_current import parse_current_csv, serialize_current_csv
from app.core.pipeline import (
    decode_duplicate_map,
    encode_duplicate_map,
    process_catalogue,
)
from app.core.source_io import parse_source_csv, serialize_excluded_csv


def test_parse_source_csv_pads_short_rows_and_removes_bom():
    content = "\ufeffcode,model,stock,retail,dealer,unused,series,brand,type\nA,Model,2,3,1,,S,B,T\n".encode()
    assert parse_source_csv(content) == [
        ("A", "Model", "2", "3", "1", None, "S", "B", "T")
    ]


def test_current_csv_round_trip_stays_in_memory():
    header = ["article : Артикул", "price : Цена"]
    rows = [{header[0]: "SKU", header[1]: "1.25"}]
    content = serialize_current_csv(header, rows)
    assert content.startswith(b"\xef\xbb\xbf")
    assert parse_current_csv(content) == (header, rows)


def test_empty_excluded_csv_is_still_header_only():
    output = serialize_excluded_csv([]).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(output), delimiter=";"))
    assert rows[0][0] == "нс-код"
    assert len(rows) == 1


def test_pipeline_returns_outputs_without_writing_source_or_processed_files():
    reference = b"code,model,stock,retail,dealer,unused,series,brand,type\n"
    current = "article : Артикул\n".encode("utf-8-sig")

    output = process_catalogue(reference, current, duplicate_map={})

    assert parse_current_csv(output.processed_csv) == (["article : Артикул"], [])
    assert output.excluded_csv.startswith(b"\xef\xbb\xbf")
    assert output.detailed_changes == []


def test_duplicate_mapping_state_is_json_safe_and_round_trips():
    mapping = {("TEST-CODE", "Test model", 2): "TEST-CODE-D01"}
    assert decode_duplicate_map(encode_duplicate_map(mapping)) == mapping
