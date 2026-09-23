"""Unit tests for utility helpers."""

from __future__ import annotations

import csv
from pathlib import Path

from app.downloader.reference.utils import save_data_to_csv


class TestSaveDataToCsv:
    """Tests for :func:`save_data_to_csv`."""

    def test_writes_rows(self, tmp_path: Path) -> None:
        output = tmp_path / "data.csv"
        data = [
            ["header1", "header2"],
            ["value1", "value2"],
            ["value3", "value4"],
        ]

        save_data_to_csv(output, data)

        assert output.is_file()
        with output.open(encoding="utf-8", newline="") as file:
            rows = list(csv.reader(file))
        assert rows == data

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        output = tmp_path / "nested" / "dir" / "out.csv"
        save_data_to_csv(output, [["a", "b"]])
        assert output.is_file()

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        output = tmp_path / "from_str.csv"
        save_data_to_csv(str(output), [["x"]])
        assert output.is_file()

    def test_empty_data(self, tmp_path: Path) -> None:
        output = tmp_path / "empty.csv"
        save_data_to_csv(output, [])
        assert output.read_text(encoding="utf-8") == ""
