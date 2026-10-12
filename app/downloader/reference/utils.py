"""Utility helpers for the reference downloader."""

from __future__ import annotations

import csv
from io import StringIO
from typing import Sequence


def serialize_data_to_csv(data: Sequence[Sequence[str]]) -> bytes:
    """Serialize spreadsheet rows into UTF-8 CSV bytes without disk I/O."""
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerows(data)
    return buffer.getvalue().encode("utf-8")
