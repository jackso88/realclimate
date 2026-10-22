"""Validated models shared across the cleaning and merging pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)

DuplicateKey = tuple[str, str, int]
DuplicateMap = dict[DuplicateKey, str]


class ProductRecord(BaseModel):
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
            because rows with a missing price are excluded before
            this model is built. It can be ``0``: that is a
            legitimate "not for sale" state, kept in the catalogue
            and hidden in current.csv (``hidden = 1``) rather than
            excluded.
        dealer_price: Dealer price in BYN ("Дилер"), same guarantees
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

    The fields map to source catalogue columns. ``code``, ``model``,
    ``availability``, ``series``, ``brand``, ``type_``, ``category`` and
    ``folder`` are text. ``retail_price`` and ``dealer_price`` are
    non-negative BYN amounts. Empty ``category`` and ``folder`` values
    are supported for rows constructed before category mapping.
    """

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    code: str
    model: str
    availability: str
    retail_price: float = Field(ge=0)
    dealer_price: float = Field(ge=0)
    series: str
    brand: str
    type_: str
    category: str = ""
    folder: str = ""

    def as_csv_row(self) -> dict[str, Union[str, float]]:
        """Map the record fields to the source catalogue's CSV columns.

        Returns:
            A dictionary keyed by the original Russian column headings,
            ready to pass to :class:`csv.DictWriter`.
        """
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


class ExcludedRecord(BaseModel):
    """One dropped row, kept around only for the manual-review CSV.

    Same fields as ProductRecord, but prices are kept as whatever
    ``parse_price`` produced (which may be ``None`` — that is usually
    *why* the row was excluded), plus a human-readable ``reason``.

    Fields ``code``, ``model``, ``availability``, ``series``, ``brand``,
    ``type_``, ``reason`` and ``category`` contain source text. The two
    optional price fields contain non-negative BYN amounts or ``None``.
    """

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

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
        """Map the excluded record and its reason to CSV column names.

        Returns:
            A dictionary ready to pass to :class:`csv.DictWriter`.
        """
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


class ProcessResult(BaseModel):
    """Validated intermediate results from cleaning source catalogue rows.

    Args:
        kept: Rows that passed validation and category filtering.
        excluded: Rows saved for manual review.
        updated_map: Updated persistent duplicate-code mapping.
        renamed_count: Number of rows assigned a new duplicate code.
        skipped_divider_rows: Number of source section-divider rows skipped.
    """

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    kept: list[ProductRecord] = Field(default_factory=list)
    excluded: list[ExcludedRecord] = Field(default_factory=list)
    updated_map: DuplicateMap = Field(default_factory=dict)
    renamed_count: int = Field(default=0, ge=0)
    skipped_divider_rows: int = Field(default=0, ge=0)


class MergeResult(BaseModel):
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
        hidden_changes: ``(article, old_hidden, new_hidden)`` for
            every row whose "hidden" flag was flipped because its
            price crossed to/from zero (``"1"`` when the new price is
            0, back to ``"0"`` the first time it leaves 0). Rows
            whose price change doesn't touch zero in either direction
            keep whatever "hidden" value they already had.
    """

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    rows: list[dict[str, str]] = Field(default_factory=list)
    header: list[str] = Field(default_factory=list)
    added_articles: list[str] = Field(default_factory=list)
    updated_articles: list[str] = Field(default_factory=list)
    renamed_articles: list[tuple[str, str]] = Field(default_factory=list)
    untouched_articles: list[str] = Field(default_factory=list)
    removed_articles: list[tuple[str, str]] = Field(default_factory=list)
    price_changes: list[tuple[str, Optional[float], float]] = Field(
        default_factory=list
    )
    amount_changes: list[tuple[str, float, float]] = Field(default_factory=list)
    anomalous_price_articles: list[str] = Field(default_factory=list)
    hidden_changes: list[tuple[str, str, str]] = Field(default_factory=list)


class CorePipelineOutput(BaseModel):
    """Validated in-memory outputs produced by one complete catalogue run.

    Args:
        processed_csv: Complete CMS import CSV bytes.
        excluded_csv: Manual-review CSV bytes persisted by the core worker.
        detailed_changes: Human-readable descriptions of catalogue changes.
        updated_duplicate_map: Duplicate mapping state for the next run.
    """

    model_config = ConfigDict(extra="forbid")

    processed_csv: bytes
    excluded_csv: bytes
    detailed_changes: list[str]
    updated_duplicate_map: DuplicateMap


class CoreSettings(BaseModel):
    """Validated storage and Kafka settings for the core service.

    Args:
        bootstrap_servers: Kafka broker addresses.
        excluded_csv_path: Path where the manual-review CSV is persisted.
        pending_redis_url: Redis connection URL for incomplete CSV pairs.
        pending_input_ttl_seconds: Expiration for pairs missing one downloader.
        processing_claim_ttl_seconds: Recovery lease for an interrupted core run.
    """

    model_config = ConfigDict(
        extra="ignore", str_strip_whitespace=True, populate_by_name=True
    )

    bootstrap_servers: str = Field(
        default="localhost:9092",
        validation_alias="KAFKA_BOOTSTRAP_SERVERS",
        min_length=1,
    )
    excluded_csv_path: Path = Field(
        default=Path("/app/storage/outputs/for_zalivka_excluded.csv"),
        validation_alias="EXCLUDED_CSV_PATH",
    )
    pending_redis_url: str = Field(
        default="redis://redis:6379/0",
        validation_alias="CORE_PENDING_REDIS_URL",
        min_length=1,
    )
    pending_input_ttl_seconds: int = Field(
        default=86_400,
        validation_alias="CORE_PENDING_INPUT_TTL_SECONDS",
        ge=1,
    )
    processing_claim_ttl_seconds: int = Field(
        default=7_200,
        validation_alias="CORE_PROCESSING_CLAIM_TTL_SECONDS",
        ge=1,
    )
