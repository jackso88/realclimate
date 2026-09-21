# -*- coding: utf-8 -*-
"""Dataclasses shared across the cleaning / merging pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

# Type of the persistent duplicate-code mapping. The key uniquely (and
# stably) identifies one physical duplicate row:
#   (original_нс-код, model, occurrence_of_this_code_model_pair)
# "occurrence" starts at 1 and disambiguates the rare case where the
# same code AND the same model repeat verbatim (e.g. identical
# consumables listed twice).
DuplicateKey = tuple[str, str, int]
DuplicateMap = dict[DuplicateKey, str]


@dataclass
class ProductRecord:
    """One kept row of the catalogue, after all cleaning steps.

    Attributes:
        code: нс-код, whitespace-normalized. May later be rewritten
            with a ``-D0N`` suffix by ``assign_duplicate_codes``.
        model: Product model / article name ("Модель" column).
        availability: Raw availability cell, whitespace-normalized.
            Kept as text because the source mixes numbers ("12") and
            statuses ("наличие уточняйте").
        retail_price: Retail price in BYN ("Розница"), already
            parsed to a float. Never ``None`` on a kept record,
            because rows with a missing/zero price are excluded
            before this dataclass is built.
        dealer_price: Dealer price in BYN ("Дилер"), same guarantee
            as ``retail_price``.
        series: Product line ("Серия" column).
        brand: Brand name ("Бренд" column).
        type_: Product category ("Тип" column). Trailing underscore
            avoids shadowing the built-in ``type``.
        category: Section/group name the row belongs to in the
            source sheet, taken from the nearest preceding
            section-divider row (e.g. "СПЛИТ-СИСТЕМЫ Electrolux
            Inverter"). Kept as raw text for human review.
        folder: The mapped current.csv "folder" value, resolved from
            ``category`` via ``helpers.map_category_to_folder``.
            Always set for a kept record — rows whose category
            couldn't be resolved never make it into ``kept``.
    """

    code: str
    model: str
    availability: str
    retail_price: float
    dealer_price: float
    series: str
    brand: str
    type_: str
    category: str = ""
    folder: str = ""

    def as_csv_row(self) -> dict[str, Union[str, float]]:
        """Render this record as a flat dict ready for csv.DictWriter."""
        return {
            "нс-код": self.code,
            "Модель": self.model,
            "Наличие": self.availability,
            "Розница, BYN": self.retail_price,
            "Дилер, BYN": self.dealer_price,
            "Серия": self.series,
            "Бренд": self.brand,
            "Тип": self.type_,
            "Категория": self.category,
            "Папка": self.folder,
        }


@dataclass
class ExcludedRecord:
    """One dropped row, kept around only for the manual-review CSV.

    Same fields as ProductRecord, but prices are kept as whatever
    ``parse_price`` produced (which may be ``None`` — that is usually
    *why* the row was excluded), plus a human-readable ``reason``.
    """

    code: str
    model: str
    availability: str
    retail_price: Optional[float]
    dealer_price: Optional[float]
    series: str
    brand: str
    type_: str
    reason: str
    category: str = ""

    def as_csv_row(self) -> dict[str, Union[str, float, None]]:
        return {
            "нс-код": self.code,
            "Модель": self.model,
            "Наличие": self.availability,
            "Розница, BYN": self.retail_price,
            "Дилер, BYN": self.dealer_price,
            "Серия": self.series,
            "Бренд": self.brand,
            "Тип": self.type_,
            "Категория": self.category,
            "Причина исключения": self.reason,
        }


@dataclass
class ProcessResult:
    """Everything produced by processing one batch of source rows."""

    kept: list[ProductRecord] = field(default_factory=list)
    excluded: list[ExcludedRecord] = field(default_factory=list)
    updated_map: DuplicateMap = field(default_factory=dict)
    renamed_count: int = 0
    skipped_divider_rows: int = 0


@dataclass
class MergeResult:
    """Outcome of merging cleaned records into an existing current.csv.

    Attributes:
        rows: The full, updated list of current.csv data rows (each a
            dict keyed by the CSV header), ready to be written out.
        header: The current.csv column header, unchanged, kept here
            for convenience when writing.
        added_articles: Codes that did not exist in current.csv and
            were appended as brand-new rows.
        updated_articles: Codes that already existed in current.csv
            and had only their amount/price refreshed.
        renamed_articles: ``(old_article, new_article)`` pairs for
            stale duplicate-mapping codes that were matched to a
            record by model and rewritten in place (amount/price are
            refreshed too).
        untouched_articles: Codes present in current.csv that were
            not matched to anything in this run's cleaned data (e.g.
            the product was discontinued by the supplier). Left as-is.
        removed_articles: ``(article, reason)`` pairs for current.csv
            rows that were deleted outright because that article's row
            was dropped by this run's cleaning pipeline (bad price,
            excluded category, unresolved group, duplicate model...).
        price_changes: ``(article, old_price, new_price)`` for every
            row whose price actually changed (covers both plain
            updates and renames). ``old_price`` is ``None`` when the
            previous cell couldn't be parsed as a number.
        amount_changes: ``(article, old_amount, new_amount)`` for
            every row whose amount actually changed.
        anomalous_price_articles: Articles (a subset of
            ``price_changes``) whose price moved by more than 50% in
            either direction — worth a human double-checking.
    """

    rows: list[dict[str, str]] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    added_articles: list[str] = field(default_factory=list)
    updated_articles: list[str] = field(default_factory=list)
    renamed_articles: list[tuple[str, str]] = field(default_factory=list)
    untouched_articles: list[str] = field(default_factory=list)
    removed_articles: list[tuple[str, str]] = field(default_factory=list)
    price_changes: list[tuple[str, Optional[float], float]] = field(
        default_factory=list
    )
    amount_changes: list[tuple[str, float, float]] = field(default_factory=list)
    anomalous_price_articles: list[str] = field(default_factory=list)
