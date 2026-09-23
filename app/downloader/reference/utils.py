"""Utility helpers for the reference downloader."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Sequence


def save_data_to_csv(
    output_path: Path | str,
    data: Sequence[Sequence[str]],
) -> None:
    """Write a two-dimensional sequence of strings to a CSV file.

    The file is created (or overwritten) with UTF-8 encoding and the
    standard CSV dialect (comma-separated, minimal quoting).

    Args:
        output_path: Destination file path. Parent directories are
            created automatically if they do not exist.
        data: Rows of string values. Each inner sequence becomes one
            CSV row.

    Raises:
        OSError: If the file cannot be written.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerows(data)
