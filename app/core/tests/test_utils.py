# -*- coding: utf-8 -*-
"""Pytest suite for utils.py.

Run with::

    pytest test_utils.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.utils import (
    assign_duplicate_codes,
    build_unique_sef_url,
    category_exclusion_reason,
    load_duplicate_map,
    map_category_to_folder,
    normalize_ws,
    parse_amount,
    parse_price,
    price_exclusion_reason,
    slugify,
    transliterate_ru,
    write_duplicate_map,
)
from app.core.models import ProductRecord

# --------------------------------------------------------------------------
# normalize_ws
# --------------------------------------------------------------------------


class TestNormalizeWs:
    def test_none_becomes_empty_string(self) -> None:
        assert normalize_ws(None) == ""

    def test_collapses_tabs_and_newlines_to_single_space(self) -> None:
        assert normalize_ws("  Foo\t\t Bar\n") == "Foo Bar"

    def test_numbers_are_stringified(self) -> None:
        assert normalize_ws(42) == "42"
        assert normalize_ws(3.5) == "3.5"

    def test_already_clean_string_is_unchanged(self) -> None:
        assert normalize_ws("Clean") == "Clean"


# --------------------------------------------------------------------------
# parse_price
# --------------------------------------------------------------------------


class TestParsePrice:
    def test_none_is_invalid(self) -> None:
        assert parse_price(None) is None

    def test_plain_numbers_pass_through(self) -> None:
        assert parse_price(100) == 100.0
        assert parse_price(99.5) == 99.5

    def test_nbsp_thousands_separator(self) -> None:
        assert parse_price("1\xa0221") == 1221.0

    def test_plain_space_thousands_separator(self) -> None:
        assert parse_price("2 152") == 2152.0

    def test_trailing_currency_marker_is_stripped(self) -> None:
        assert parse_price("32 р.") == 32.0
        assert parse_price("22р") == 22.0

    def test_comma_decimal_separator(self) -> None:
        assert parse_price("982,15") == 982.15

    def test_error_marker_is_invalid(self) -> None:
        assert parse_price("#N/A") is None
        assert parse_price("#n/a") is None

    def test_empty_string_is_invalid(self) -> None:
        assert parse_price("") is None
        assert parse_price("   ") is None

    def test_unparseable_garbage_is_invalid(self) -> None:
        assert parse_price("наличие уточняйте") is None


class TestParseAmount:
    def test_plain_number_passes_through(self) -> None:
        assert parse_amount(12) == 12.0
        assert parse_amount("12") == 12.0

    def test_comma_decimal_is_handled(self) -> None:
        assert parse_amount("3,5") == 3.5

    def test_non_numeric_status_becomes_zero(self) -> None:
        assert parse_amount("наличие уточняйте") == 0.0

    def test_empty_becomes_zero(self) -> None:
        assert parse_amount("") == 0.0
        assert parse_amount(None) == 0.0


# --------------------------------------------------------------------------
# category_exclusion_reason
# --------------------------------------------------------------------------


class TestCategoryExclusionReason:
    def test_empty_type_is_excluded(self) -> None:
        assert category_exclusion_reason(None, None) is not None
        assert category_exclusion_reason("", "") is not None

    def test_known_good_type_is_kept(self) -> None:
        assert (
            category_exclusion_reason("Кондиционеры Electrolux Inverter", "Fusion")
            is None
        )

    @pytest.mark.parametrize(
        "type_value",
        [
            "Расходные материалы",
            "Расходные материалы ВЕНТ",
            "Аксессуары",
            "Аксесуары",  # typo present in the source data
            "Очистители воздуха",
            "Тепловые насосы для бассейнов",
            "Кабель ",
        ],
    )
    def test_excluded_type_keywords(self, type_value: str) -> None:
        assert category_exclusion_reason(type_value, "") is not None

    def test_excluded_keyword_in_series_only(self) -> None:
        reason = category_exclusion_reason(
            "Кондиционеры Electrolux Inverter", "Тепловые насосы VIKING 2.0"
        )
        assert reason is not None
        assert "Серия" in reason

    def test_tabs_and_extra_whitespace_do_not_prevent_matching(self) -> None:
        assert category_exclusion_reason("Расходные материалы\t\t\t", "") is not None


# --------------------------------------------------------------------------
# price_exclusion_reason
# --------------------------------------------------------------------------


class TestPriceExclusionReason:
    def test_two_valid_prices_are_kept(self) -> None:
        assert price_exclusion_reason(100.0, 50.0) is None

    def test_zero_retail_price_is_excluded(self) -> None:
        reason = price_exclusion_reason(0.0, 50.0)
        assert reason is not None
        assert "Розница" in reason

    def test_missing_dealer_price_is_excluded(self) -> None:
        reason = price_exclusion_reason(100.0, None)
        assert reason is not None
        assert "Дилер" in reason

    def test_both_prices_bad_are_reported_together(self) -> None:
        reason = price_exclusion_reason(0.0, None)
        assert reason is not None
        assert "Розница" in reason and "Дилер" in reason


# --------------------------------------------------------------------------
# map_category_to_folder
# --------------------------------------------------------------------------


class TestMapCategoryToFolder:
    @pytest.mark.parametrize(
        "category",
        [
            "Мобильные кондиционеры Ballu",
            "Промышленные мобильные кондиционеры",
            "мобильные КОНДИЦИОНЕРЫ shuft",  # case-insensitive
        ],
    )
    def test_mobile(self, category: str) -> None:
        assert (
            map_category_to_folder(category)
            == "Каталог кондиционеров,Мобильные кондиционеры"
        )

    @pytest.mark.parametrize(
        "category",
        [
            "Оконный кондиционер",
            "Оконные кондиционеры",  # actual spelling used in the source sheet
        ],
    )
    def test_window(self, category: str) -> None:
        assert (
            map_category_to_folder(category)
            == "Каталог кондиционеров,Оконные кондиционеры"
        )

    @pytest.mark.parametrize(
        "category",
        [
            "МУЛЬТИСПЛИТ-СИСТЕМЫ Electrolux R410a",
            "Мульти сплит-ситемы Shuft",  # vendor's typo, as given by the client
            "Мульти-сплит ситемы Royal Thermo",  # a third variant found in the real data
            "Мультисплит-системы Toshiba",
        ],
    )
    def test_multi_split(self, category: str) -> None:
        assert (
            map_category_to_folder(category)
            == "Каталог кондиционеров,Мульти-сплит-системы"
        )

    @pytest.mark.parametrize(
        "category",
        [
            "Полупромышленные системы Electrolux On/Off",
            "ПОЛУПРОМ Shuft",  # client's abbreviation anomaly
            "Колонные кондиционеры Ballu On/Off",
            "Канальный высоконапорный кондиционер",  # client's exact wording
            "Высоконапорные канальники Ballu инвертор",  # actual wording in the source sheet
        ],
    )
    def test_semi_industrial(self, category: str) -> None:
        assert (
            map_category_to_folder(category)
            == "Каталог кондиционеров,Полупромышленные кондиционеры"
        )

    @pytest.mark.parametrize(
        "category",
        [
            "СПЛИТ-СИСТЕМЫ Electrolux Inverter",
            "Кондиционеры прочие",
        ],
    )
    def test_plain_split_systems_fallback(self, category: str) -> None:
        assert map_category_to_folder(category) == "Каталог кондиционеров,Сплит-системы"

    def test_unresolvable_group_returns_none(self) -> None:
        assert map_category_to_folder("тошиба") is None

    def test_empty_category_returns_none(self) -> None:
        assert map_category_to_folder("") is None
        assert map_category_to_folder(None) is None

    def test_semi_industrial_takes_priority_over_plain_split(self) -> None:
        # Contains both "полупром" and "сплит-систем" — semi-industrial
        # must win per the client's stated rule order.
        category = "Полупромышленные сплит-системы"
        assert (
            map_category_to_folder(category)
            == "Каталог кондиционеров,Полупромышленные кондиционеры"
        )


# --------------------------------------------------------------------------
# assign_duplicate_codes — stability across reruns
# --------------------------------------------------------------------------


def make_record(code: str, model: str) -> ProductRecord:
    """Build a minimal ProductRecord for duplicate-mapping tests."""
    return ProductRecord(
        code=code,
        model=model,
        availability="1",
        retail_price=100.0,
        dealer_price=50.0,
        series="S",
        brand="B",
        type_="T",
    )


class TestAssignDuplicateCodes:
    def test_unique_code_is_left_untouched(self) -> None:
        items = [make_record("NC-1", "Model A")]
        items, updated_map, renamed = assign_duplicate_codes(items, {})
        assert items[0].code == "NC-1"
        assert renamed == 0
        assert updated_map == {}  # non-duplicates are never persisted

    def test_first_bootstrap_sorts_by_model_and_keeps_first_bare(self) -> None:
        items = [make_record("NC-1", "RAS-B"), make_record("NC-1", "RAS-A")]
        items, updated_map, renamed = assign_duplicate_codes(items, {})
        codes_by_model = {item.model: item.code for item in items}
        assert codes_by_model["RAS-A"] == "NC-1"
        assert codes_by_model["RAS-B"] == "NC-1-D01"
        assert renamed == 1
        assert len(updated_map) == 2

    def test_stable_across_row_order_changes(self) -> None:
        first_run_items = [make_record("NC-1", "RAS-B"), make_record("NC-1", "RAS-A")]
        _, mapping_after_run1, _ = assign_duplicate_codes(first_run_items, {})

        reordered_items = [make_record("NC-1", "RAS-A"), make_record("NC-1", "RAS-B")]
        reordered_items, mapping_after_run2, _ = assign_duplicate_codes(
            reordered_items, mapping_after_run1
        )

        codes_by_model = {item.model: item.code for item in reordered_items}
        assert codes_by_model["RAS-A"] == "NC-1"
        assert codes_by_model["RAS-B"] == "NC-1-D01"
        assert mapping_after_run2 == mapping_after_run1

    def test_new_duplicate_gets_next_free_suffix_without_disturbing_old_ones(
        self,
    ) -> None:
        first_run_items = [make_record("NC-1", "RAS-B"), make_record("NC-1", "RAS-A")]
        _, mapping, _ = assign_duplicate_codes(first_run_items, {})

        items = [
            make_record("NC-1", "RAS-B"),
            make_record("NC-1", "RAS-A"),
            make_record("NC-1", "RAS-C"),
        ]
        items, updated_map, renamed = assign_duplicate_codes(items, mapping)

        codes_by_model = {item.model: item.code for item in items}
        assert codes_by_model["RAS-A"] == "NC-1"
        assert codes_by_model["RAS-B"] == "NC-1-D01"
        assert codes_by_model["RAS-C"] == "NC-1-D02"

    def test_identical_code_and_model_duplicated_are_disambiguated(self) -> None:
        items = [make_record("NC-9", "SAME"), make_record("NC-9", "SAME")]
        items, updated_map, renamed = assign_duplicate_codes(items, {})
        codes = sorted(item.code for item in items)
        assert codes == ["NC-9", "NC-9-D01"]
        assert len(updated_map) == 2

    def test_resolved_duplicate_reverts_to_bare_code(self) -> None:
        first_run_items = [make_record("NC-1", "RAS-B"), make_record("NC-1", "RAS-A")]
        _, mapping, _ = assign_duplicate_codes(first_run_items, {})

        items = [make_record("NC-1", "RAS-A")]
        items, _, renamed = assign_duplicate_codes(items, mapping)
        assert items[0].code == "NC-1"
        assert renamed == 0


# --------------------------------------------------------------------------
# duplicate_mapping.py module round-trip
# --------------------------------------------------------------------------


class TestDuplicateMapPersistence:
    def test_write_then_load_round_trip(self, tmp_path: Path) -> None:
        mapping = {
            ("NC-1", "RAS-A", 1): "NC-1",
            ("NC-1", "RAS-B", 1): "NC-1-D01",
        }
        module_path = tmp_path / "duplicate_mapping.py"

        write_duplicate_map(mapping, module_path)
        loaded = load_duplicate_map(module_path)

        assert loaded == mapping

    def test_missing_file_loads_as_empty_mapping(self, tmp_path: Path) -> None:
        missing_path = tmp_path / "does_not_exist.py"
        assert load_duplicate_map(missing_path) == {}

    def test_generated_module_is_sorted_and_editable(self, tmp_path: Path) -> None:
        mapping = {
            ("NC-2", "M", 1): "NC-2",
            ("NC-1", "M", 1): "NC-1",
        }
        module_path = tmp_path / "duplicate_mapping.py"
        write_duplicate_map(mapping, module_path)

        text = module_path.read_text(encoding="utf-8")
        assert text.index("'NC-1'") < text.index("'NC-2'")


# --------------------------------------------------------------------------
# transliterate_ru / slugify / build_unique_sef_url
# --------------------------------------------------------------------------


class TestTransliterateRu:
    def test_lowercase_letters(self) -> None:
        assert transliterate_ru("кондиционер") == "kondicioner"

    def test_uppercase_letters_keep_case(self) -> None:
        assert transliterate_ru("Электролюкс") == "Elektrolyuks"

    def test_latin_text_passes_through(self) -> None:
        assert transliterate_ru("EACS/I-12HAV/N8") == "EACS/I-12HAV/N8"

    def test_soft_and_hard_signs_are_dropped(self) -> None:
        result = transliterate_ru("подъезд")
        assert "ъ" not in result and "ь" not in result
        assert result == "podezd"


class TestSlugify:
    def test_latin_name_matches_legacy_url_style(self) -> None:
        # Sanity check against the one real example the client gave us.
        assert slugify("Electrolux Inverter EACS/I-12HAV/N8_V2/WF").startswith(
            "electrolux-inverter-eacs-i-12hav-n8"
        )

    def test_cyrillic_name_is_transliterated(self) -> None:
        assert slugify("Кондиционер Electrolux") == "kondicioner-electrolux"

    def test_punctuation_collapses_to_single_hyphens(self) -> None:
        assert slugify("A,,,B   C") == "a-b-c"

    def test_leading_trailing_junk_is_trimmed(self) -> None:
        assert slugify("  /Foo/  ") == "foo"


class TestBuildUniqueSefUrl:
    def test_first_use_gets_the_plain_slug(self) -> None:
        url = build_unique_sef_url("Foo Bar", existing_urls=set())
        assert url == "glavnaya-magazina/product/foo-bar"

    def test_collision_gets_a_numeric_suffix(self) -> None:
        existing = {"glavnaya-magazina/product/foo-bar"}
        url = build_unique_sef_url("Foo Bar", existing_urls=existing)
        assert url == "glavnaya-magazina/product/foo-bar-2"

    def test_multiple_collisions_increment(self) -> None:
        existing = {
            "glavnaya-magazina/product/foo-bar",
            "glavnaya-magazina/product/foo-bar-2",
            "glavnaya-magazina/product/foo-bar-3",
        }
        url = build_unique_sef_url("Foo Bar", existing_urls=existing)
        assert url == "glavnaya-magazina/product/foo-bar-4"
