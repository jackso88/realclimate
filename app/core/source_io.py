"""File input and output helpers for supplier reference data."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import openpyxl

from app.core.exceptions import SourceDataError
from app.core.models import ExcludedRecord

logger = logging.getLogger(__name__)
SHEET_NAME = "1. Для заливки"


def load_source_rows_from_xlsx(path: Path, sheet_name: str) -> list[tuple]:
    """Load every data row (i.e. excluding the header) of one sheet
    from a ``.xlsx`` workbook.

    Args:
        path: Path to the source ``.xlsx`` workbook.
        sheet_name: Name of the sheet to read.

    Returns:
        A list of row tuples, in file order.
    """
    try:
        workbook = openpyxl.load_workbook(path, data_only=True)
        worksheet = workbook[sheet_name]
        return list(
            worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, values_only=True)
        )
    except (OSError, KeyError, ValueError) as error:
        raise SourceDataError(
            f"Could not read source workbook {path}: {error}"
        ) from error


def load_source_rows_from_csv(path: Path) -> list[tuple]:
    """Load every data row (i.e. excluding the header) from a CSV
    export of the "1. Для заливки" sheet.

    The file is expected to use the sheet's own column order —
    нс-код, Модель, Наличие, Розница, Дилер, (unused), Серия, Бренд,
    Тип, … — exactly what you get from Google Sheets' File -> Download
    -> Comma-separated values (.csv) run on that one sheet, or an
    auto-published CSV export of it (comma-delimited, UTF-8, quoted
    fields where needed).

    Args:
        path: Path to the CSV file.

    Returns:
        A list of row tuples, in file order. Rows are padded to at
        least 9 columns and empty cells become ``None``, so the
        result has the exact same shape ``process_rows`` gets from
        ``load_source_rows_from_xlsx`` — nothing downstream needs to
        care which one produced it.
    """
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))
    except (OSError, csv.Error, UnicodeError) as error:
        raise SourceDataError(f"Could not read source CSV {path}: {error}") from error

    data_rows = rows[1:]  # drop the header row
    normalized_rows: list[tuple] = []
    for row in data_rows:
        padded = list(row) + [""] * max(0, 9 - len(row))
        normalized_rows.append(
            tuple(value if value != "" else None for value in padded)
        )
    return normalized_rows


def load_source_rows(path: Path, sheet_name: str = SHEET_NAME) -> list[tuple]:
    """Load every data row of the reference catalogue, from either a
    ``.xlsx`` workbook or a ``.csv`` export of its "1. Для заливки"
    sheet.

    Dispatches purely on ``path``'s file extension: ``.csv`` goes to
    ``load_source_rows_from_csv``, anything else (``.xlsx``, ``.xlsm``,
    …) goes to ``load_source_rows_from_xlsx``.

    Args:
        path: Path to the source file.
        sheet_name: Sheet to read — only used for the ``.xlsx`` path.

    Returns:
        A list of row tuples, in file order.
    """
    if path.suffix.lower() == ".csv":
        rows = load_source_rows_from_csv(path)
    else:
        rows = load_source_rows_from_xlsx(path, sheet_name)
    logger.info("Loaded %d supplier rows from %s", len(rows), path)
    return rows


def write_excluded_csv(excluded: list[ExcludedRecord], path: Path) -> None:
    """Write the excluded-rows CSV used for manual review.

    Args:
        excluded: Every dropped row, each carrying its reason.
        path: Destination file path.
    """
    fieldnames = [
        "нс-код",
        "Модель",
        "Наличие",
        "Розница, BYN",
        "Дилер, BYN",
        "Серия",
        "Бренд",
        "Тип",
        "Категория",
        "Причина исключения",
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            for record in excluded:
                writer.writerow(record.as_csv_row())
    except OSError as error:
        raise SourceDataError(
            f"Could not write excluded rows to {path}: {error}"
        ) from error
