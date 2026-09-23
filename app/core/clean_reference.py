# -*- coding: utf-8 -*-
"""Clean the "1. Для заливки" sheet of the reference catalogue and
merge the result into an existing current.csv export.

The reference catalogue can come from either a ``.xlsx`` workbook
(read via openpyxl) or a plain ``.csv`` export of just that one sheet
(e.g. ``reference_auto.csv``, downloaded straight from Google Sheets
via File -> Download -> Comma-separated values, or an auto-published
CSV link) — ``load_source_rows`` picks the right reader from the file
extension. The CSV path exists because Drive API's ``.xlsx`` export
of the whole workbook has occasionally come back with unresolved
formulas (missing "Дилер" prices, odd "Наличие" values); exporting
just the one sheet as CSV avoids that.

Pipeline
--------
1.  Read the "1. Для заливки" sheet (xlsx) or its CSV export.
2.  Track the current section/group name from divider rows (no
    нс-код, text in the "Модель" column position) so every product
    row knows its category — used as current.csv's ``folder``.
3.  Drop rows whose product category is excluded, checking BOTH the
    "Тип" and "Серия" columns.
4.  Drop rows with an undefined "Тип" (empty cell).
5.  Drop rows where the retail price OR the dealer price is missing
    or equal to zero.
6.  For нс-коды that repeat, assign a stable, persisted unique code
    (``<code>-D01``, …) via ``duplicate_mapping.py``
    (see ``helpers.assign_duplicate_codes`` for the stability
    contract).
7.  The cleaned catalogue is kept in memory (``ProcessResult.kept``)
    — it is no longer written to its own CSV file — and merged into
    current.csv:
        - an existing article only has its amount/price refreshed;
        - an old artificial duplicate code that vanished is resolved
          by matching on "Модель" and renamed in place;
        - anything left over is appended as a brand-new row.
8.  Two files are written:
        - the updated current.csv;
        - every excluded row plus the reason it was dropped
          (``for_zalivka_excluded.csv``), for manual review.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

import openpyxl

from app.core.utils import (
    assign_duplicate_codes,
    category_exclusion_reason,
    load_duplicate_map,
    map_category_to_folder,
    normalize_ws,
    parse_price,
    price_exclusion_reason,
    REASON_DUPLICATE_MODEL,
    REASON_UNRESOLVED_GROUP,
    write_duplicate_map,
)
from app.core.merge_current import (
    format_merge_report,
    load_current_csv,
    merge_records_into_current,
    write_current_csv,
)
from app.core.models import DuplicateMap, ExcludedRecord, ProcessResult, ProductRecord

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

SRC_PATH = Path("../../storage/uploads/reference.csv")
SHEET_NAME = "1. Для заливки"

CURRENT_CSV_PATH = Path("../../storage/uploads/current.csv")
CURRENT_CSV_OUT_PATH = Path("../../storage/outputs/current.csv")

OUT_DIR = Path("../../storage/outputs")
EXCLUDED_CSV_PATH = OUT_DIR / "for_zalivka_excluded.csv"

# Module that stores the persistent нс-код duplicate mapping. Lives
# next to this script so it can be committed to version control and
# edited by hand if needed.
DUPLICATE_MAPPING_PATH = BASE_DIR / "duplicate_mapping.py"


# --------------------------------------------------------------------------
# Row-level processing (pure — no file I/O, easy to unit-test)
# --------------------------------------------------------------------------


def _drop_duplicate_models(
    provisional: list[ProductRecord], excluded: list[ExcludedRecord]
) -> tuple[list[ProductRecord], list[ExcludedRecord]]:
    """Drop every record whose "Модель" repeats among the provisional kept set.

    Unlike duplicate нс-коды (which get uniquified with a ``-D0N``
    suffix), a duplicated model is a data problem we don't try to
    resolve automatically — per the client's request, ALL rows
    sharing that model are excluded, not just the extras.

    Comparison is case-insensitive (whitespace-normalized, lower-
    cased), matching every other check in this pipeline.

    Args:
        provisional: Records that passed every other check (type,
            series, price, resolvable category) and are otherwise
            ready to be kept.
        excluded: The excluded-rows list so far; records dropped here
            are appended to it (not replaced).

    Returns:
        ``(kept, excluded)`` — ``kept`` has the duplicate-model
        records removed; ``excluded`` has them appended, each with
        reason ``REASON_DUPLICATE_MODEL``.
    """
    model_counts: dict[str, int] = {}
    for record in provisional:
        key = record.model.lower()
        model_counts[key] = model_counts.get(key, 0) + 1

    kept: list[ProductRecord] = []
    for record in provisional:
        key = record.model.lower()
        if model_counts[key] > 1:
            excluded.append(
                ExcludedRecord(
                    code=record.code,
                    model=record.model,
                    availability=record.availability,
                    retail_price=record.retail_price,
                    dealer_price=record.dealer_price,
                    series=record.series,
                    brand=record.brand,
                    type_=record.type_,
                    reason=REASON_DUPLICATE_MODEL,
                    category=record.category,
                )
            )
        else:
            kept.append(record)

    return kept, excluded


def process_rows(rows: Iterable[tuple], existing_map: DuplicateMap) -> ProcessResult:
    """Run the full cleaning pipeline over already-loaded sheet rows.

    Args:
        rows: Sheet rows (as returned by
            ``worksheet.iter_rows(values_only=True)``), NOT including
            the header row. Each row is expected to have at least 9
            columns in this order: нс-код, Модель, Наличие, Розница,
            Дилер, (unused), Серия, Бренд, Тип. Any columns beyond
            index 8 are ignored. A row with an empty нс-код is either
            a section-divider row (its "Модель"-position cell holds
            the new current category) or a blank spacer row.
        existing_map: Previously persisted duplicate-code mapping.

    Returns:
        A ``ProcessResult`` with the kept records, the excluded
        records (each with a reason), the updated duplicate map, how
        many rows were renamed, and how many divider rows were
        skipped.
    """
    provisional: list[ProductRecord] = []
    excluded: list[ExcludedRecord] = []
    skipped_divider_rows = 0
    current_category = ""

    for row in rows:
        code_raw = row[0]
        code = normalize_ws(code_raw)
        if code == "":
            # Section-divider / blank row — not a real product line.
            # If it carries text where "Модель" would be, it names
            # the category for every product row that follows.
            divider_text = normalize_ws(row[1])
            if divider_text:
                current_category = divider_text
            skipped_divider_rows += 1
            continue

        model = normalize_ws(row[1])
        availability = normalize_ws(row[2])
        retail_price = parse_price(row[3])
        dealer_price = parse_price(row[4])
        series = normalize_ws(row[6])
        brand = normalize_ws(row[7])
        type_value = row[8]
        type_normalized = normalize_ws(type_value)

        reason = category_exclusion_reason(type_value, series)
        if reason is None:
            reason = price_exclusion_reason(retail_price, dealer_price)

        folder = None
        if reason is None:
            folder = map_category_to_folder(current_category)
            if folder is None:
                reason = REASON_UNRESOLVED_GROUP

        if reason is not None:
            excluded.append(
                ExcludedRecord(
                    code=code,
                    model=model,
                    availability=availability,
                    retail_price=retail_price,
                    dealer_price=dealer_price,
                    series=series,
                    brand=brand,
                    type_=type_normalized,
                    reason=reason,
                    category=current_category,
                )
            )
            continue

        provisional.append(
            ProductRecord(
                code=code,
                model=model,
                availability=availability,
                retail_price=retail_price,  # type: ignore[arg-type]  # not None: reason would be set otherwise
                dealer_price=dealer_price,  # type: ignore[arg-type]
                series=series,
                brand=brand,
                type_=type_normalized,
                category=current_category,
                folder=folder,
            )
        )

    kept, excluded = _drop_duplicate_models(provisional, excluded)
    kept, updated_map, renamed_count = assign_duplicate_codes(kept, existing_map)

    return ProcessResult(
        kept=kept,
        excluded=excluded,
        updated_map=updated_map,
        renamed_count=renamed_count,
        skipped_divider_rows=skipped_divider_rows,
    )


# --------------------------------------------------------------------------
# File I/O
# --------------------------------------------------------------------------


def load_source_rows_from_xlsx(path: Path, sheet_name: str) -> list[tuple]:
    """Load every data row (i.e. excluding the header) of one sheet
    from a ``.xlsx`` workbook.

    Args:
        path: Path to the source ``.xlsx`` workbook.
        sheet_name: Name of the sheet to read.

    Returns:
        A list of row tuples, in file order.
    """
    workbook = openpyxl.load_workbook(path, data_only=True)
    worksheet = workbook[sheet_name]
    return list(
        worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, values_only=True)
    )


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
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

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
        return load_source_rows_from_csv(path)
    return load_source_rows_from_xlsx(path, sheet_name)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for record in excluded:
            writer.writerow(record.as_csv_row())


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main(
    src_path: Path = SRC_PATH,
    sheet_name: str = SHEET_NAME,
    current_csv_path: Path = CURRENT_CSV_PATH,
    current_csv_out_path: Path = CURRENT_CSV_OUT_PATH,
    excluded_csv_path: Path = EXCLUDED_CSV_PATH,
    mapping_path: Path = DUPLICATE_MAPPING_PATH,
) -> ProcessResult:
    """Run the full pipeline end-to-end: clean the source, merge into
    current.csv, and write the excluded-rows review file.

    Args:
        src_path: Source ``.xlsx`` workbook.
        sheet_name: Sheet to read from ``src_path``.
        current_csv_path: Existing current.csv export to merge into.
        current_csv_out_path: Where to write the merged current.csv.
        excluded_csv_path: Where to write the excluded rows + reasons.
        mapping_path: Where the persistent duplicate-code mapping
            module lives (read at the start, rewritten at the end).

    Returns:
        The ``ProcessResult`` for the run — ``result.kept`` is the
        in-memory cleaned catalogue, available for any further use
        beyond the current.csv merge.
    """
    rows = load_source_rows(src_path, sheet_name)
    existing_map = load_duplicate_map(mapping_path)

    result = process_rows(rows, existing_map)

    header, current_rows = load_current_csv(current_csv_path)
    merge_result = merge_records_into_current(
        result.kept, header, current_rows, result.updated_map, excluded=result.excluded
    )
    write_current_csv(merge_result.header, merge_result.rows, current_csv_out_path)

    write_excluded_csv(result.excluded, excluded_csv_path)
    write_duplicate_map(result.updated_map, mapping_path)

    print(f"Source data rows (excluding header): {len(rows)}")
    print(f"Skipped section-divider rows: {result.skipped_divider_rows}")
    print(f"Excluded (category/undefined type/bad price): {len(result.excluded)}")
    print(f"Kept in memory (cleaned catalogue): {len(result.kept)}")
    print(f"Rows assigned a new duplicate suffix this run: {result.renamed_count}")
    print("--- current.csv merge ---")
    print(
        f"Updated (existing article, amount/price refreshed): {len(merge_result.updated_articles)}"
    )
    print(
        f"Renamed (stale duplicate code -> matched by model): {len(merge_result.renamed_articles)}"
    )
    for old, new in merge_result.renamed_articles:
        print(f"    {old} -> {new}")
    print(f"Added (brand-new article): {len(merge_result.added_articles)}")
    print(
        f"Removed (dropped by this run's cleaning): {len(merge_result.removed_articles)}"
    )
    print(
        f"Untouched (present in current.csv, not found in today's data): {len(merge_result.untouched_articles)}"
    )
    print(f"Merged current.csv written to: {current_csv_out_path}")
    print(f"Excluded-rows file written to: {excluded_csv_path}")
    print(f"Duplicate mapping module written to: {mapping_path}")

    report_lines = format_merge_report(merge_result)
    if report_lines:
        print("--- detailed changes ---")
        for line in report_lines:
            print(line)

    return result


if __name__ == "__main__":
    main()
