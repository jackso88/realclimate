"""Tests for articles listed in ``MANUAL_INCLUDED``: they are kept whatever the reason."""

from __future__ import annotations

import pytest

from app.core import clean_reference
from app.core.clean_reference import process_rows
from app.core.merge_current import merge_records_into_current
from app.core.tests.test_core_clean_reference import (
    divider_row,
    rows_under,
    sheet_row,
)
from app.core.tests.test_core_merge_current import HEADER
from app.core.utils import REASON_DUPLICATE_MODEL, REASON_UNRESOLVED_GROUP

FORCED = "NC-FORCED"
MOBILE_CATEGORY = "Мобильные кондиционеры Ballu"
MOBILE_FOLDER = "Каталог кондиционеров,Мобильные кондиционеры"
HIDDEN = "hidden : Скрыто"


@pytest.fixture(autouse=True)
def manual_included(monkeypatch):
    monkeypatch.setattr(clean_reference, "MANUAL_INCLUDED", (FORCED,))


class TestManualInclusionBypassesEveryReason:
    def test_regular_row_keeps_its_own_prices_and_folder(self) -> None:
        rows = rows_under(
            MOBILE_CATEGORY,
            sheet_row(code=FORCED, model="A", retail=120.0, dealer=80.0),
        )

        result = process_rows(rows, {})

        record = result.kept[0]
        assert record.code == FORCED
        assert (record.retail_price, record.dealer_price) == (120.0, 80.0)
        assert record.folder == MOBILE_FOLDER
        assert result.excluded == []

    def test_excluded_type_is_overridden(self) -> None:
        rows = rows_under(
            MOBILE_CATEGORY, sheet_row(code=FORCED, model="A", type_="Кабель")
        )

        result = process_rows(rows, {})

        assert [record.code for record in result.kept] == [FORCED]
        assert result.kept[0].folder == MOBILE_FOLDER
        assert result.excluded == []

    def test_unresolved_group_is_overridden_and_leaves_the_folder_empty(
        self,
    ) -> None:
        rows = [
            divider_row("тошиба"),
            sheet_row(code=FORCED, model="A"),
            sheet_row(code="NC-2", model="B"),
        ]

        result = process_rows(rows, {})

        assert [record.code for record in result.kept] == [FORCED]
        assert result.kept[0].folder == ""
        assert [item.code for item in result.excluded] == ["NC-2"]
        assert result.excluded[0].reason == REASON_UNRESOLVED_GROUP

    def test_missing_retail_price_becomes_zero(self) -> None:
        rows = rows_under(
            MOBILE_CATEGORY,
            sheet_row(code=FORCED, model="A", retail="#N/A", dealer=50.0),
        )

        result = process_rows(rows, {})

        record = result.kept[0]
        assert record.retail_price == 0.0
        assert record.dealer_price == 50.0
        assert result.excluded == []

    def test_missing_dealer_price_becomes_zero(self) -> None:
        rows = rows_under(
            MOBILE_CATEGORY,
            sheet_row(code=FORCED, model="A", retail=100.0, dealer="#N/A"),
        )

        result = process_rows(rows, {})

        record = result.kept[0]
        assert record.retail_price == 100.0
        assert record.dealer_price == 0.0

    def test_negative_price_becomes_zero(self) -> None:
        rows = rows_under(
            MOBILE_CATEGORY, sheet_row(code=FORCED, model="A", retail=-5.0)
        )

        result = process_rows(rows, {})

        assert result.kept[0].retail_price == 0.0

    def test_duplicate_model_does_not_drop_the_included_article(self) -> None:
        rows = rows_under(
            MOBILE_CATEGORY,
            sheet_row(code=FORCED, model="Same Model"),
            sheet_row(code="NC-2", model="same model"),
        )

        result = process_rows(rows, {})

        assert [record.code for record in result.kept] == [FORCED]
        assert [item.code for item in result.excluded] == ["NC-2"]
        assert result.excluded[0].reason == REASON_DUPLICATE_MODEL

    def test_several_reasons_at_once_are_all_overridden(self) -> None:
        rows = [
            divider_row("тошиба"),
            sheet_row(
                code=FORCED,
                model="A",
                type_="Кабель",
                retail="#N/A",
                dealer="#N/A",
            ),
        ]

        result = process_rows(rows, {})

        record = result.kept[0]
        assert record.code == FORCED
        assert (record.retail_price, record.dealer_price) == (0.0, 0.0)
        assert record.folder == ""
        assert result.excluded == []

    def test_other_articles_are_still_excluded(self) -> None:
        rows = rows_under(
            MOBILE_CATEGORY,
            sheet_row(code=FORCED, model="A", type_="Кабель"),
            sheet_row(code="NC-2", model="B", type_="Кабель"),
        )

        result = process_rows(rows, {})

        assert [record.code for record in result.kept] == [FORCED]
        assert [item.code for item in result.excluded] == ["NC-2"]
        assert "кабель" in result.excluded[0].reason.lower()

    def test_included_article_with_unusable_price_is_hidden_in_current(self) -> None:
        rows = rows_under(
            MOBILE_CATEGORY, sheet_row(code=FORCED, model="A", retail="#N/A")
        )
        result = process_rows(rows, {})

        merged = merge_records_into_current(result.kept, HEADER, [], {})

        assert merged.added_articles == [FORCED]
        assert merged.rows[0][HIDDEN] == "1"
