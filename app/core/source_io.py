"""In-memory CSV parsing and excluded-row serialization."""

from __future__ import annotations

import csv
import io

from app.core.exceptions import SourceDataError
from app.core.models import ExcludedRecord


def parse_source_csv(content: bytes) -> list[tuple]:
    """Parse supplier CSV bytes into the row shape expected by process_rows.

    Args:
        content: UTF-8 or UTF-8-BOM CSV bytes with a header row.

    Returns:
        Data rows as tuples, padded to nine cells; empty cells become ``None``.

    Raises:
        SourceDataError: If the bytes are not valid UTF-8 or CSV content.
    """
    try:
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    except (csv.Error, UnicodeError) as error:
        raise SourceDataError(f"Could not parse source CSV content: {error}") from error

    normalized = []
    for row in rows[1:]:
        padded = row + [""] * max(0, 9 - len(row))
        normalized.append(tuple(value or None for value in padded))
    return normalized


def serialize_excluded_csv(excluded: list[ExcludedRecord]) -> bytes:
    """Serialize excluded rows as an Excel-friendly UTF-8 CSV byte string.

    Args:
        excluded: Records omitted from the processed catalogue, including each
            record's reason for exclusion.

    Returns:
        Semicolon-delimited CSV bytes with a UTF-8 BOM and review columns.
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
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter=";")
    writer.writeheader()
    writer.writerows(record.as_csv_row() for record in excluded)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
