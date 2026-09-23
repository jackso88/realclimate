# -*- coding: utf-8 -*-
"""Pytest suite for clean_reference.py.

Run with::

    pytest test_clean_reference.py -v
"""

from __future__ import annotations

from pathlib import Path

import openpyxl

from app.core.clean_reference import load_source_rows, main, process_rows
from app.core.utils import FOLDER_SPLIT, REASON_DUPLICATE_MODEL, REASON_UNRESOLVED_GROUP
from app.core.merge_current import load_current_csv, write_current_csv

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


# --------------------------------------------------------------------------
# load_source_rows — real xlsx I/O on a tiny generated workbook, and
# dispatch to the CSV reader
# --------------------------------------------------------------------------


class TestLoadSourceRows:
    def test_reads_xlsx_data_rows_excluding_header(self, tmp_path: Path) -> None:
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "1. Для заливки"
        sheet.append(
            [
                "код",
                "модель",
                "наличие",
                "розница",
                "дилер",
                "",
                "серия",
                "бренд",
                "тип",
            ]
        )
        sheet.append(["NC-1", "Model A", "5", 100, 50, "", "Series", "Brand", "Type"])
        path = tmp_path / "reference.xlsx"
        workbook.save(path)

        rows = load_source_rows(path, "1. Для заливки")

        assert len(rows) == 1
        assert rows[0][0] == "NC-1"

    def test_csv_extension_dispatches_to_the_csv_reader(self, tmp_path: Path) -> None:
        path = tmp_path / "reference_auto.csv"
        path.write_text(
            "нс-код,Модель,Наличие,Розница,Дилер,,Серия,Бренд,Тип\n"
            "NC-1,Model A,5,100,50,,Series,Brand,Type\n",
            encoding="utf-8",
        )

        rows = load_source_rows(path)

        assert len(rows) == 1
        assert rows[0][0] == "NC-1"
        assert rows[0][1] == "Model A"

    def test_csv_reader_pads_short_rows_and_turns_blanks_into_none(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "reference_auto.csv"
        # A divider row typically only has the group name in column B.
        path.write_text(
            "нс-код,Модель,Наличие,Розница,Дилер,,Серия,Бренд,Тип\n" ",Some Group\n",
            encoding="utf-8",
        )

        rows = load_source_rows(path)

        assert len(rows) == 1
        assert rows[0][0] is None
        assert rows[0][1] == "Some Group"
        assert len(rows[0]) >= 9

    def test_csv_reader_matches_process_rows_expectations(self, tmp_path: Path) -> None:
        # End-to-end: a CSV-sourced row should clean exactly like the
        # equivalent xlsx row would.
        path = tmp_path / "reference_auto.csv"
        path.write_text(
            "нс-код,Модель,Наличие,Розница,Дилер,,Серия,Бренд,Тип\n"
            ",СПЛИТ-СИСТЕМЫ Test\n"
            "NC-1,Model A,5,100,50,,Series,Brand,Кондиционеры Test\n",
            encoding="utf-8",
        )

        rows = load_source_rows(path)
        result = process_rows(rows, {})

        assert len(result.kept) == 1
        assert result.kept[0].code == "NC-1"
        assert result.kept[0].retail_price == 100.0


# --------------------------------------------------------------------------
# main() — full end-to-end orchestration on tiny generated files
# --------------------------------------------------------------------------


class TestMainEndToEnd:
    def _build_workbook(self, path: Path) -> None:
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "1. Для заливки"
        sheet.append(
            [
                "код",
                "модель",
                "наличие",
                "розница",
                "дилер",
                "",
                "серия",
                "бренд",
                "тип",
            ]
        )
        sheet.append(
            [None, RESOLVABLE_CATEGORY, None, None, None, None, None, None, None]
        )
        sheet.append(
            [
                "NC-EXISTING",
                "Existing model",
                "5",
                111.0,
                55.0,
                None,
                "Ser",
                "Br",
                "Type",
            ]
        )
        sheet.append(
            ["NC-NEW", "New model", "3", 222.0, 111.0, None, "Ser", "Br", "Type"]
        )
        sheet.append(
            [
                "NC-BAD",
                "Excluded model",
                "1",
                50.0,
                25.0,
                None,
                "",
                "Br",
                "Расходные материалы",
            ]
        )
        workbook.save(path)

    def _build_current_csv(self, path: Path) -> None:
        header = [
            "name : Название",
            "article : Артикул",
            "amount : Количество",
            "price : Цена",
            "folder : Категория",
            "currency : Валюта",
            "sef_url : ЧПУ",
        ]
        rows = [
            {
                "name : Название": "Old name, should stay untouched",
                "article : Артикул": "NC-EXISTING",
                "amount : Количество": "1",
                "price : Цена": "1.00",
                "folder : Категория": "Old folder",
                "currency : Валюта": "RUB",
                "sef_url : ЧПУ": "glavnaya-magazina/product/old",
            }
        ]
        write_current_csv(header, rows, path)

    def test_full_pipeline_merges_into_current_csv(self, tmp_path: Path) -> None:
        src_path = tmp_path / "reference.xlsx"
        current_csv_path = tmp_path / "current.csv"
        current_csv_out_path = tmp_path / "current_out.csv"
        excluded_csv_path = tmp_path / "excluded.csv"
        mapping_path = tmp_path / "duplicate_mapping.py"

        self._build_workbook(src_path)
        self._build_current_csv(current_csv_path)

        result = main(
            src_path=src_path,
            sheet_name="1. Для заливки",
            current_csv_path=current_csv_path,
            current_csv_out_path=current_csv_out_path,
            excluded_csv_path=excluded_csv_path,
            mapping_path=mapping_path,
        )

        # in-memory cleaned catalogue is available for further use
        assert {item.code for item in result.kept} == {"NC-EXISTING", "NC-NEW"}
        assert len(result.excluded) == 1
        assert all(item.folder == FOLDER_SPLIT for item in result.kept)

        header, merged_rows = load_current_csv(current_csv_out_path)
        rows_by_article = {row["article : Артикул"]: row for row in merged_rows}

        # existing article: only amount/price change, everything else stays
        existing = rows_by_article["NC-EXISTING"]
        assert existing["price : Цена"] == "111.00"
        assert existing["amount : Количество"] == "5.0"
        assert existing["name : Название"] == "Old name, should stay untouched"
        assert existing["currency : Валюта"] == "RUB"

        # brand-new article: built from the field mapping, name has no "Тип"
        new_row = rows_by_article["NC-NEW"]
        assert new_row["price : Цена"] == "222.00"
        assert new_row["currency : Валюта"] == "BYN"
        assert new_row["folder : Категория"] == FOLDER_SPLIT
        assert new_row["name : Название"] == "Br Ser New model"

        assert excluded_csv_path.exists()
        assert mapping_path.exists()

    def test_rerun_is_stable_and_does_not_duplicate_rows(self, tmp_path: Path) -> None:
        src_path = tmp_path / "reference.xlsx"
        current_csv_path = tmp_path / "current.csv"
        current_csv_out_path = tmp_path / "current_out.csv"
        excluded_csv_path = tmp_path / "excluded.csv"
        mapping_path = tmp_path / "duplicate_mapping.py"

        self._build_workbook(src_path)
        self._build_current_csv(current_csv_path)

        main(
            src_path=src_path,
            sheet_name="1. Для заливки",
            current_csv_path=current_csv_path,
            current_csv_out_path=current_csv_out_path,
            excluded_csv_path=excluded_csv_path,
            mapping_path=mapping_path,
        )
        # Second run merges the freshly-produced current.csv into itself.
        main(
            src_path=src_path,
            sheet_name="1. Для заливки",
            current_csv_path=current_csv_out_path,
            current_csv_out_path=current_csv_out_path,
            excluded_csv_path=excluded_csv_path,
            mapping_path=mapping_path,
        )

        _, merged_rows = load_current_csv(current_csv_out_path)
        assert len(merged_rows) == 2  # NC-EXISTING + NC-NEW, not duplicated
