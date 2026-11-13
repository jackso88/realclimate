"""In-memory core catalogue processing pipeline."""

from app.core.clean_reference import process_rows
from app.core.duplicate_mapping import DUPLICATE_CODE_MAP
from app.core.merge_current import (
    format_merge_report,
    merge_records_into_current,
    parse_current_csv,
    serialize_current_csv,
)
from app.core.models import CorePipelineOutput, DuplicateMap
from app.core.source_io import parse_source_csv, serialize_excluded_csv


def encode_duplicate_map(duplicate_map: DuplicateMap) -> dict[str, list[list[object]]]:
    """Convert tuple-keyed duplicate state to a JSON-safe Kafka payload.

    Args:
        duplicate_map: Mapping from ``(original code, model, occurrence)``
            tuples to assigned article codes.

    Returns:
        A dictionary whose ``entries`` value contains JSON-compatible lists.
    """
    return {
        "entries": [
            [code, model, occurrence, assigned]
            for (code, model, occurrence), assigned in duplicate_map.items()
        ]
    }


def decode_duplicate_map(payload: dict) -> DuplicateMap:
    """Restore a duplicate-code mapping from a Kafka payload.

    Args:
        payload: Dictionary produced by :func:`encode_duplicate_map`.

    Returns:
        The mapping keyed by ``(original code, model, occurrence)`` tuples.
    """
    return {
        (str(code), str(model), int(occurrence)): str(assigned)
        for code, model, occurrence, assigned in payload.get("entries", [])
    }


def encode_absent_articles(articles: set[str]) -> dict[str, list[str]]:
    """Convert the set of absent articles to a JSON-safe Kafka payload.

    Args:
        articles: Articles hidden because the supplier catalogue no longer
            lists them.

    Returns:
        A dictionary whose ``articles`` value is a sorted list, so the
        published state is deterministic.
    """
    return {"articles": sorted(articles)}


def decode_absent_articles(payload: dict) -> set[str]:
    """Restore the set of absent articles from a Kafka payload.

    Args:
        payload: Dictionary produced by :func:`encode_absent_articles`.

    Returns:
        The set of tracked article codes; empty when the payload has none.
    """
    return {str(article) for article in payload.get("articles", [])}


def process_catalogue(
    reference_csv: bytes,
    current_csv: bytes,
    duplicate_map: DuplicateMap | None = None,
    absent_articles: set[str] | None = None,
) -> CorePipelineOutput:
    """Clean supplier rows, merge them into the current CMS export, and serialize.

    Args:
        reference_csv: Source spreadsheet rows serialized as CSV bytes.
        current_csv: Current CMS catalogue serialized as CSV bytes.
        duplicate_map: Previous duplicate-code state; when ``None``, the
            bundled initial mapping is used.
        absent_articles: Articles hidden by earlier runs because the
            supplier catalogue no longer listed them; ``None`` means none.

    Returns:
        Processed catalogue bytes, excluded-row CSV bytes, change summaries,
        and updated duplicate-code and absent-article state.

    Raises:
        SourceDataError: If the supplier CSV cannot be decoded or parsed.
        CurrentCatalogError: If the current CMS CSV cannot be parsed.
    """
    rows = parse_source_csv(reference_csv)
    process_result = process_rows(
        rows,
        dict(DUPLICATE_CODE_MAP if duplicate_map is None else duplicate_map),
    )
    header, current_rows = parse_current_csv(current_csv)
    merge_result = merge_records_into_current(
        process_result.kept,
        header,
        current_rows,
        process_result.updated_map,
        excluded=process_result.excluded,
        absent_articles=absent_articles,
    )
    return CorePipelineOutput(
        processed_csv=serialize_current_csv(merge_result.header, merge_result.rows),
        excluded_csv=serialize_excluded_csv(process_result.excluded),
        detailed_changes=format_merge_report(merge_result),
        updated_duplicate_map=process_result.updated_map,
        updated_absent_articles=merge_result.absent_articles,
    )
