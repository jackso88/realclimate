# -*- coding: utf-8 -*-
"""Pytest suite for clean_reference.py.

Run with::

    pytest test_core_clean_reference.py -v
"""

from __future__ import annotations

from app.core.clean_reference import process_rows
from app.core.utils import REASON_DUPLICATE_MODEL, REASON_UNRESOLVED_GROUP

# A category text that resolves to a real folder (plain split systems),
# used everywhere a test just needs "some valid group" and doesn't care
# which bucket it lands in.
RESOLVABLE_CATEGORY = "СПЛИТ-СИСТЕМЫ Test"


def sheet_row(
    code: object = None,
    model: object = "",
    availability: object = "0",
    retail: object = 100.0,
    dealer: object = 50.0,
    series: object = "",
    brand: object = "",
    type_: object = "Кондиционеры Test",
) -> tuple:
    """Build a 9-column row tuple matching the real sheet's layout."""
    return (code, model, availability, retail, dealer, None, series, brand, type_)


def divider_row(text: str) -> tuple:
    """Build a section-divider row: empty code, group name in the
    "Модель"-position cell."""
    return (None, text, None, None, None, None, None, None, None)


def rows_under(category: str, *product_rows: tuple) -> list[tuple]:
    """Prefix a resolvable divider row before the given product rows."""
    return [divider_row(category), *product_rows]


# --------------------------------------------------------------------------
# process_rows — category tracking
# --------------------------------------------------------------------------


class TestProcessRowsCategoryTracking:
    def test_kept_rows_inherit_the_preceding_divider_text(self) -> None:
        rows = rows_under(
            "СПЛИТ-СИСТЕМЫ Electrolux Inverter",
            sheet_row(code="NC-1", model="A"),
            sheet_row(code="NC-2", model="B"),
        )
        result = process_rows(rows, {})
        assert [item.category for item in result.kept] == [
            "СПЛИТ-СИСТЕМЫ Electrolux Inverter",
            "СПЛИТ-СИСТЕМЫ Electrolux Inverter",
        ]

    def test_category_switches_at_the_next_divider(self) -> None:
        rows = [
            divider_row("Мобильные кондиционеры Ballu"),
            sheet_row(code="NC-1", model="A"),
            divider_row("Оконные кондиционеры"),
            sheet_row(code="NC-2", model="B"),
        ]
        result = process_rows(rows, {})
        categories = {item.code: item.category for item in result.kept}
        assert categories == {
            "NC-1": "Мобильные кондиционеры Ballu",
            "NC-2": "Оконные кондиционеры",
        }

    def test_excluded_rows_also_carry_the_category(self) -> None:
        rows = rows_under(
            RESOLVABLE_CATEGORY, sheet_row(code="NC-1", model="A", type_="Кабель")
        )
        result = process_rows(rows, {})
        assert result.excluded[0].category == RESOLVABLE_CATEGORY

    def test_row_with_no_preceding_divider_has_no_resolvable_group(self) -> None:
        # No divider at all -> category is "" -> map_category_to_folder("")
        # is None -> the row is excluded, not silently kept with an
        # empty category.
        rows = [sheet_row(code="NC-1", model="A")]
        result = process_rows(rows, {})
        assert result.kept == []
        assert result.excluded[0].reason == REASON_UNRESOLVED_GROUP

    def test_blank_divider_row_does_not_reset_category(self) -> None:
        rows = [
            divider_row(RESOLVABLE_CATEGORY),
            (
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ),  # fully blank spacer
            sheet_row(code="NC-1", model="A"),
        ]
        result = process_rows(rows, {})
        assert result.kept[0].category == RESOLVABLE_CATEGORY
        assert result.skipped_divider_rows == 2


# --------------------------------------------------------------------------
# process_rows — folder resolution
# --------------------------------------------------------------------------


class TestProcessRowsFolderResolution:
    def test_kept_record_gets_the_mapped_folder(self) -> None:
        rows = rows_under(
            "Мобильные кондиционеры Ballu", sheet_row(code="NC-1", model="A")
        )
        result = process_rows(rows, {})
        assert result.kept[0].folder == "Каталог кондиционеров,Мобильные кондиционеры"

    def test_unresolvable_group_excludes_every_row_under_it(self) -> None:
        rows = [
            divider_row("тошиба"),
            sheet_row(code="NC-1", model="A"),
            sheet_row(code="NC-2", model="B"),
        ]
        result = process_rows(rows, {})
        assert result.kept == []
        assert len(result.excluded) == 2
        assert all(item.reason == REASON_UNRESOLVED_GROUP for item in result.excluded)

    def test_unresolvable_group_does_not_shadow_a_real_category_exclusion(self) -> None:
        # A row that's ALSO excluded for its own "Тип" should keep that
        # more specific reason rather than being reported as an
        # unresolved group.
        rows = [
            divider_row("тошиба"),
            sheet_row(code="NC-1", model="A", type_="Кабель"),
        ]
        result = process_rows(rows, {})
        assert "кабель" in result.excluded[0].reason.lower()


# --------------------------------------------------------------------------
# process_rows — duplicate-model exclusion
# --------------------------------------------------------------------------


class TestProcessRowsDuplicateModels:
    def test_rows_sharing_a_model_are_all_excluded(self) -> None:
        rows = rows_under(
            RESOLVABLE_CATEGORY,
            sheet_row(code="NC-1", model="Same Model"),
            sheet_row(code="NC-2", model="Same Model"),
        )
        result = process_rows(rows, {})
        assert result.kept == []
        assert len(result.excluded) == 2
        assert all(item.reason == REASON_DUPLICATE_MODEL for item in result.excluded)

    def test_model_comparison_is_case_insensitive(self) -> None:
        rows = rows_under(
            RESOLVABLE_CATEGORY,
            sheet_row(code="NC-1", model="model x"),
            sheet_row(code="NC-2", model="MODEL X"),
        )
        result = process_rows(rows, {})
        assert result.kept == []
        assert len(result.excluded) == 2

    def test_unique_models_are_unaffected(self) -> None:
        rows = rows_under(
            RESOLVABLE_CATEGORY,
            sheet_row(code="NC-1", model="Model A"),
            sheet_row(code="NC-2", model="Model B"),
        )
        result = process_rows(rows, {})
        assert {item.code for item in result.kept} == {"NC-1", "NC-2"}

    def test_duplicate_models_do_not_interfere_with_unrelated_duplicate_codes(
        self,
    ) -> None:
        # A duplicated нс-код with genuinely different models must
        # still go through the normal -D01 suffixing, unaffected by
        # the (unrelated) duplicate-model exclusion.
        rows = rows_under(
            RESOLVABLE_CATEGORY,
            sheet_row(code="NC-1", model="Model A"),
            sheet_row(code="NC-1", model="Model B"),
        )
        result = process_rows(rows, {})
        codes = sorted(item.code for item in result.kept)
        assert codes == ["NC-1", "NC-1-D01"]


# --------------------------------------------------------------------------
# process_rows — sanity checks carried over from the pre-refactor suite
# --------------------------------------------------------------------------


class TestProcessRowsBasics:
    def test_divider_rows_are_skipped(self) -> None:
        rows = [divider_row(""), sheet_row(code="NC-1", model="A")]
        result = process_rows(rows, {})
        assert result.skipped_divider_rows == 1
        # No resolvable category was ever set -> excluded, not kept.
        assert result.kept == []
        assert result.excluded[0].reason == REASON_UNRESOLVED_GROUP

    def test_excluded_category_goes_to_excluded_list(self) -> None:
        rows = rows_under(
            RESOLVABLE_CATEGORY,
            sheet_row(code="NC-1", model="A", type_="Расходные материалы"),
        )
        result = process_rows(rows, {})
        assert len(result.kept) == 0
        assert "расходные материалы" in result.excluded[0].reason.lower()

    def test_duplicates_are_suffixed_in_the_final_output(self) -> None:
        rows = rows_under(
            RESOLVABLE_CATEGORY,
            sheet_row(code="NC-1", model="RAS-B"),
            sheet_row(code="NC-1", model="RAS-A"),
        )
        result = process_rows(rows, {})
        codes = sorted(item.code for item in result.kept)
        assert codes == ["NC-1", "NC-1-D01"]

    def test_zero_retail_price_is_kept_not_excluded(self) -> None:
        # Changed behaviour: a price of exactly 0 used to drop the
        # row; now it's kept (hidden downstream in current.csv).
        rows = rows_under(
            RESOLVABLE_CATEGORY, sheet_row(code="NC-1", model="A", retail=0)
        )
        result = process_rows(rows, {})
        assert len(result.kept) == 1
        assert result.kept[0].retail_price == 0.0
        assert result.excluded == []

    def test_zero_dealer_price_is_kept_not_excluded(self) -> None:
        rows = rows_under(
            RESOLVABLE_CATEGORY, sheet_row(code="NC-1", model="A", dealer=0)
        )
        result = process_rows(rows, {})
        assert len(result.kept) == 1
        assert result.excluded == []

    def test_missing_retail_price_is_still_excluded(self) -> None:
        rows = rows_under(
            RESOLVABLE_CATEGORY, sheet_row(code="NC-1", model="A", retail="#N/A")
        )
        result = process_rows(rows, {})
        assert result.kept == []
        assert "Розница" in result.excluded[0].reason
        assert "Цена не определена" in result.excluded[0].reason
