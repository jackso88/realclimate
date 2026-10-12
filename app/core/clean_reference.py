"""Pure row-cleaning operations for supplier catalogue data."""

from __future__ import annotations

from typing import Iterable

from app.core.models import DuplicateMap, ExcludedRecord, ProcessResult, ProductRecord
from app.core.utils import (
    REASON_DUPLICATE_MODEL,
    REASON_UNRESOLVED_GROUP,
    assign_duplicate_codes,
    category_exclusion_reason,
    map_category_to_folder,
    normalize_ws,
    parse_price,
    price_exclusion_reason,
)


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
