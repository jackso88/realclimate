# -*- coding: utf-8 -*-
"""Read current.csv, merge in the cleaned catalogue, write it back out.

Column mapping (see docstrings below for the exact rules):
    - an article already present in current.csv -> only "amount" and
      "price" are refreshed, every other column is left untouched;
    - an article that used to be an artificial duplicate code
      (``НС-xxxxx-D0N``) and is missing from today's data -> resolved
      by looking up its ``Модель`` in ``duplicate_mapping`` and
      matching that model against today's records, then the article
      itself is renamed in place;
    - an article whose row was dropped by the cleaning pipeline this
      run (bad price, excluded category, unresolved group, duplicate
      model, ...) -> removed from current.csv entirely;
    - a genuinely new article -> a brand-new row is built from the
      field mapping given by the client (see ``build_new_row``).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Optional

from app.core.utils import build_unique_sef_url, parse_amount, parse_price
from app.core.models import DuplicateMap, ExcludedRecord, MergeResult, ProductRecord

CSV_DELIMITER = ";"
CSV_ENCODING = "utf-8-sig"  # BOM so Excel detects UTF-8/Cyrillic correctly

# A price move bigger than this fraction (in either direction) is
# flagged as a likely data-entry mistake worth a human's attention.
ANOMALOUS_PRICE_CHANGE_THRESHOLD = 0.5  # 50%

# Fixed values for brand-new rows, exactly as specified by the client.
NEW_ROW_SUPPLIER = "Русклимат-М"
NEW_ROW_CURRENCY = "BYN"
NEW_ROW_AMOUNT_MIN = "1"
NEW_ROW_AMOUNT_MULTIPLICITY = "1"
NEW_ROW_HIDDEN = "0"
NEW_ROW_SEO_NOINDEX = "0"
NEW_ROW_SMT_TYPE = "0"
SEF_URL_PREFIX = "glavnaya-magazina/product"


def column_short_key(header_cell: str) -> str:
    """Extract the short machine key from a two-part header cell.

    current.csv headers look like ``"name : Название"``; the part
    before the first colon is the stable machine-readable key.

    Args:
        header_cell: One raw header cell, e.g. ``"price : Цена"``.

    Returns:
        The short key, e.g. ``"price"``.
    """
    return header_cell.split(":", 1)[0].strip()


def load_current_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read current.csv.

    Args:
        path: Path to the existing current.csv export.

    Returns:
        A tuple of ``(header, rows)`` — the header as it appears in
        the file (used verbatim when writing back out) and every data
        row as a dict keyed by that same header.
    """
    with path.open(newline="", encoding=CSV_ENCODING) as handle:
        reader = csv.DictReader(handle, delimiter=CSV_DELIMITER)
        header = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return header, rows


def write_current_csv(
    header: list[str], rows: list[dict[str, str]], path: Path
) -> None:
    """Write current.csv back out, preserving the original header.

    Args:
        header: Column header, exactly as read from the source file.
        rows: Every row to write (existing rows, in their original
            order, followed by newly added ones).
        path: Destination path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=CSV_ENCODING) as handle:
        writer = csv.DictWriter(handle, fieldnames=header, delimiter=CSV_DELIMITER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_new_row(
    record: ProductRecord,
    header_by_short_key: dict[str, str],
    existing_sef_urls: set[str],
) -> dict[str, str]:
    """Build a brand-new current.csv row for a record with no existing article.

    Field mapping (as specified by the client):
        name         = "{Бренд} {Серия} {Модель}" (empty parts skipped;
                       "Тип" is deliberately NOT included)
        vendor       = Бренд
        supplier     = "Русклимат-М" (fixed)
        article      = нс-код
        folder       = mapped folder path, resolved from the source
                       group/section name via
                       ``helpers.map_category_to_folder`` back in
                       ``clean_reference.process_rows`` (e.g.
                       "Каталог кондиционеров,Сплит-системы")
        hidden       = "0"
        amount       = Наличие, parsed to a number (non-numeric
                       statuses such as "наличие уточняйте" become 0
                       — same rule used when refreshing existing rows)
        amount_min   = "1" (fixed)
        amount_multiplicity = "1" (fixed)
        price        = Розница, formatted with 2 decimals
        currency     = "BYN" (fixed)
        seo_noindex  = "0" (fixed)
        seo_title / seo_description / seo_keywords = name
        sef_url      = "glavnaya-magazina/product/{slug(name)}", de-duplicated
        smt_type     = "0" (fixed)
        everything else (image, code_1c, note, body, unit, weight,
        weight_unit, dimensions, smt_title, smt_description,
        smt_image, uuid, uuid_mod) is left blank — we have no source
        data for it, to be filled in by hand later.

    Args:
        record: The cleaned catalogue record with no existing
            current.csv article.
        header_by_short_key: Maps each short column key (e.g.
            ``"price"``) to the exact header cell used in this
            current.csv file (e.g. ``"price : Цена"``).
        existing_sef_urls: Every ``sef_url`` already in use; the
            newly built URL is added to this set in place so the
            next call in the same run stays unique too.

    Returns:
        A full row dict, keyed by the original header cells, ready
        to append to current.csv's rows.
    """
    name_parts = [record.brand, record.series, record.model]
    name = " ".join(part for part in name_parts if part)

    sef_url = build_unique_sef_url(name, existing_sef_urls, prefix=SEF_URL_PREFIX)
    existing_sef_urls.add(sef_url)

    values_by_short_key = {
        "name": name,
        "vendor": record.brand,
        "supplier": NEW_ROW_SUPPLIER,
        "image": "",
        "article": record.code,
        "code_1c": "",
        "folder": record.folder,
        "hidden": NEW_ROW_HIDDEN,
        "note": "",
        "body": "",
        "amount": str(parse_amount(record.availability)),
        "amount_min": NEW_ROW_AMOUNT_MIN,
        "amount_multiplicity": NEW_ROW_AMOUNT_MULTIPLICITY,
        "unit": "",
        "weight": "",
        "weight_unit": "",
        "dimensions": "",
        "price": f"{record.retail_price:.2f}",
        "currency": NEW_ROW_CURRENCY,
        "seo_noindex": NEW_ROW_SEO_NOINDEX,
        "seo_title": name,
        "seo_description": name,
        "seo_keywords": name,
        "sef_url": sef_url,
        "smt_title": "",
        "smt_description": "",
        "smt_image": "",
        "smt_type": NEW_ROW_SMT_TYPE,
        "uuid": "",
        "uuid_mod": "",
    }

    row = {header: "" for header in header_by_short_key.values()}
    for short_key, value in values_by_short_key.items():
        header_cell = header_by_short_key.get(short_key)
        if header_cell is not None:
            row[header_cell] = value
    return row


def is_anomalous_price_change(old_price: Optional[float], new_price: float) -> bool:
    """Decide whether a price move is large enough to flag for a human.

    Args:
        old_price: The previous price, or ``None`` if it couldn't be
            parsed (treated as anomalous, since there's no baseline
            to trust).
        new_price: The new price.

    Returns:
        ``True`` if the price moved by more than
        ``ANOMALOUS_PRICE_CHANGE_THRESHOLD`` (50%) in either
        direction, or if there was no usable previous price to
        compare against.
    """
    if old_price is None or old_price == 0:
        return True
    relative_change = abs(new_price - old_price) / old_price
    return relative_change > ANOMALOUS_PRICE_CHANGE_THRESHOLD


def _apply_amount_and_price(
    row: dict[str, str], record: ProductRecord, header_by_short_key: dict[str, str]
) -> tuple[Optional[tuple[Optional[float], float]], Optional[tuple[float, float]]]:
    """Overwrite the amount/price cells of an existing row, in place,
    and report what (if anything) actually changed.

    Args:
        row: The current.csv row to update, mutated in place.
        record: The cleaned catalogue record supplying the new values.
        header_by_short_key: Maps short column keys to this file's
            actual header cells.

    Returns:
        ``(price_change, amount_change)`` — each is ``None`` if that
        value didn't change, otherwise ``(old, new)``. ``old`` for
        price may itself be ``None`` if the previous cell wasn't a
        parseable number.
    """
    amount_header = header_by_short_key.get("amount")
    price_header = header_by_short_key.get("price")

    price_change: Optional[tuple[Optional[float], float]] = None
    amount_change: Optional[tuple[float, float]] = None

    if price_header is not None:
        old_price = parse_price(row.get(price_header))
        new_price = record.retail_price
        row[price_header] = f"{new_price:.2f}"
        if old_price != new_price:
            price_change = (old_price, new_price)

    if amount_header is not None:
        old_amount = parse_amount(row.get(amount_header))
        new_amount = parse_amount(record.availability)
        row[amount_header] = str(new_amount)
        if old_amount != new_amount:
            amount_change = (old_amount, new_amount)

    return price_change, amount_change


def _build_removal_reasons(
    excluded: list[ExcludedRecord], duplicate_map: DuplicateMap
) -> dict[str, str]:
    """Map every current.csv article that a dropped row could still
    correspond to, onto the reason it was dropped.

    A row excluded this run is identified by its bare нс-код — but if
    that код used to be part of a duplicate group, its current.csv
    article might actually be a suffixed code such as ``NC-1-D01``
    that ``assign_duplicate_codes`` produced on an earlier run. We
    reverse-search ``duplicate_map`` for entries recorded under the
    same original code AND the same model to also catch that case —
    the exact same technique used to resolve renames.

    Args:
        excluded: Every row the cleaning pipeline dropped this run.
        duplicate_map: The persisted duplicate-code mapping.

    Returns:
        ``{candidate_article: reason}``. When two excluded rows would
        map to the same candidate article (shouldn't normally happen),
        the first one wins.
    """
    reasons: dict[str, str] = {}
    for record in excluded:
        candidates = {record.code}
        for (orig_code, model, _occurrence), assigned_code in duplicate_map.items():
            if orig_code == record.code and model == record.model:
                candidates.add(assigned_code)
        for candidate in candidates:
            reasons.setdefault(candidate, record.reason)
    return reasons


def merge_records_into_current(
    records: list[ProductRecord],
    header: list[str],
    current_rows: list[dict[str, str]],
    duplicate_map: DuplicateMap,
    excluded: Optional[list[ExcludedRecord]] = None,
) -> MergeResult:
    """Merge cleaned catalogue records into current.csv's existing rows.

    Each current.csv row is handled by the first matching case below:
        1. Its article matches a kept record's code exactly -> update
           that row's amount/price in place.
        2. Its article was dropped by the cleaning pipeline this run
           (see ``excluded``) -> the row is removed from current.csv
           entirely.
        3. Its article holds an artificial duplicate code (from
           ``duplicate_map``) whose recorded model matches some kept
           record's model, and that old article isn't claimed by
           anything else -> treat this as the same physical product
           having been renamed; rewrite the row's article (and
           refresh amount/price).
        4. Otherwise -> left untouched (presumably discontinued, or
           an ambiguous rename we won't guess at).
    Every kept record not claimed by an update or a rename is then
    appended as a brand-new row.

    Args:
        records: This run's cleaned, kept catalogue.
        header: current.csv's column header (used to build brand-new
            rows and to resolve short keys like ``"price"``).
        current_rows: current.csv's existing data rows.
        duplicate_map: The persisted duplicate-нс-код mapping — used
            to explain *why* an old article might have gone missing
            (a model-based rename or removal is only attempted for
            codes it recognises).
        excluded: Rows the cleaning pipeline dropped this run (bad
            price, excluded category, unresolved group, duplicate
            model, ...). If any of them already has a row in
            current.csv, that row is removed. Defaults to none.

    Returns:
        A ``MergeResult`` with the final row set and a breakdown of
        what happened to each article.
    """
    header_by_short_key = {column_short_key(h): h for h in header}
    article_header = header_by_short_key["article"]

    records_by_code: dict[str, ProductRecord] = {r.code: r for r in records}
    removal_reason_by_article = _build_removal_reasons(excluded or [], duplicate_map)
    claimed_codes: set[str] = set()

    existing_sef_urls = {
        row.get(header_by_short_key.get("sef_url", ""), "") for row in current_rows
    }
    existing_sef_urls.discard("")

    # Reverse lookup: assigned code (bare or "-D0N") -> the model(s)
    # duplicate_map recorded for it, so a vanished artificial article
    # can be traced back to "what product was this, by model".
    model_by_assigned_code: dict[str, set[str]] = defaultdict(set)
    for (_orig_code, model, _occurrence), assigned_code in duplicate_map.items():
        model_by_assigned_code[assigned_code].add(model)

    result = MergeResult(header=header)

    def _record_changes(article: str, price_change, amount_change) -> None:
        if price_change is not None:
            old_price, new_price = price_change
            result.price_changes.append((article, old_price, new_price))
            if is_anomalous_price_change(old_price, new_price):
                result.anomalous_price_articles.append(article)
        if amount_change is not None:
            old_amount, new_amount = amount_change
            result.amount_changes.append((article, old_amount, new_amount))

    # --- single pass over every existing row -----------------------
    for row in current_rows:
        article = row[article_header]
        record = records_by_code.get(article)

        if record is not None:
            # Case 1: still a valid, kept article -> refresh in place.
            price_change, amount_change = _apply_amount_and_price(
                row, record, header_by_short_key
            )
            _record_changes(article, price_change, amount_change)
            claimed_codes.add(article)
            result.updated_articles.append(article)
            result.rows.append(row)
            continue

        if article in removal_reason_by_article:
            # Case 2: this run's cleaning pipeline dropped it -> the
            # row is removed from current.csv, not merely left stale.
            reason = removal_reason_by_article[article]
            result.removed_articles.append((article, reason))
            continue

        candidate_models = model_by_assigned_code.get(article)
        matches = (
            [
                r
                for r in records
                if r.model in candidate_models and r.code not in claimed_codes
            ]
            if candidate_models
            else []
        )

        if len(matches) == 1:
            # Case 3: stale artificial duplicate code -> rename.
            new_record = matches[0]
            row[article_header] = new_record.code
            price_change, amount_change = _apply_amount_and_price(
                row, new_record, header_by_short_key
            )
            # Report changes under the NEW code — that's what this
            # article is called from now on.
            _record_changes(new_record.code, price_change, amount_change)
            claimed_codes.add(new_record.code)
            result.renamed_articles.append((article, new_record.code))
            result.rows.append(row)
        else:
            # Case 4: zero matches (or a real ambiguity with more than
            # one) -> nothing to safely change; leave the row as-is.
            result.untouched_articles.append(article)
            result.rows.append(row)

    # --- anything left over is a brand-new article ------------------
    for record in records:
        if record.code in claimed_codes:
            continue
        new_row = build_new_row(record, header_by_short_key, existing_sef_urls)
        result.rows.append(new_row)
        result.added_articles.append(record.code)
        claimed_codes.add(record.code)

    return result


def format_merge_report(result: MergeResult) -> list[str]:
    """Turn a ``MergeResult`` into the informative, human-readable
    messages the client asked for.

    Message shapes (exactly as specified):
        - price change:  "Артикул {артикул}, цена изменилась с ... на ..."
        - amount change: "Артикул {артикул}, количество изменилось с ... на ..."
        - anomalous price change (>50% either way): printed right
          after the corresponding price-change line, so it's seen in
          context: "ВНИМАНИЕ!!!! {Артикул}, аномальное изменение цены!!!"
        - removed article (its row was dropped by the cleaning
          pipeline this run): "Артикул {article} был исключен по
          причине {причина}"
        - new articles: one combined line listing every added
          артикул: "Были добавлены новые артикулы: ..., ..., ..."

    Args:
        result: The outcome of ``merge_records_into_current``.

    Returns:
        Report lines, in a sensible reading order: all price/amount
        changes (grouped per article, anomaly warning right after its
        price line), then removals, then the new-articles summary line.
    """
    anomalous = set(result.anomalous_price_articles)
    amount_change_by_article = {
        article: (old, new) for article, old, new in result.amount_changes
    }

    lines: list[str] = []
    reported_amount_articles: set[str] = set()

    for article, old_price, new_price in result.price_changes:
        old_str = f"{old_price:.2f}" if old_price is not None else "не указана"
        lines.append(
            f"Артикул {article}, цена изменилась с {old_str} на {new_price:.2f}"
        )
        if article in anomalous:
            lines.append(f"\nВНИМАНИЕ!!!! {article}, аномальное изменение цены!!!\n")

        # Keep a price change and its amount change on adjacent lines
        # for the same article, when both happened.
        if article in amount_change_by_article:
            old_amount, new_amount = amount_change_by_article[article]
            lines.append(
                f"Артикул {article}, количество изменилось с {old_amount:g} на {new_amount:g}"
            )
            reported_amount_articles.add(article)

    for article, old_amount, new_amount in result.amount_changes:
        if article in reported_amount_articles:
            continue
        lines.append(
            f"Артикул {article}, количество изменилось с {old_amount:g} на {new_amount:g}"
        )

    for article, reason in result.removed_articles:
        lines.append(f"Артикул {article} был исключен по причине: '{reason}'")

    if result.added_articles:
        lines.append(
            "Были добавлены новые артикулы: \n" + "\n".join(result.added_articles)
        )

    return lines
