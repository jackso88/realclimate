# -*- coding: utf-8 -*-
"""Free-standing helper functions used by the cleaning / merging pipeline.

Grouped into three areas:
    - cell-level parsing (``normalize_ws``, ``parse_price``, …);
    - exclusion rules (``category_exclusion_reason``,
      ``price_exclusion_reason``);
    - duplicate-нс-код handling (``assign_duplicate_codes`` and the
      module read/write helpers for the persisted mapping);
    - slug / URL generation for new current.csv rows
      (``transliterate_ru``, ``slugify``, ``build_unique_sef_url``).
"""

from __future__ import annotations

import importlib.util
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from app.core.models import DuplicateKey, DuplicateMap, ProductRecord

# --------------------------------------------------------------------------
# Cell-level cleaning helpers
# --------------------------------------------------------------------------


def normalize_ws(value: object) -> str:
    """Collapse any run of whitespace (spaces/tabs/newlines) to a single
    space and strip the result. ``None`` becomes an empty string.

    This is the single place that turns a raw Excel cell value into a
    clean string — it is used for codes, models, series, brand and
    type alike.

    Args:
        value: Raw cell value as returned by openpyxl (``str``,
            ``int``, ``float`` or ``None``).

    Returns:
        A whitespace-normalized string.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_price(value: object) -> Optional[float]:
    """Parse a price cell into a float, or ``None`` if it can't be read
    as a valid price.

    Handles the messy formats found in the source file:
        - plain numbers (``int``/``float``) -> returned as-is;
        - thousands separated with a non-breaking space or a normal
          space (``"1\\xa0221"``, ``"2 152"``);
        - a trailing currency marker (``"32 р."``, ``"22р"``);
        - a comma used as the decimal separator (``"982,15"``);
        - the literal error marker ``"#N/A"``;
        - empty cells.

    Args:
        value: Raw price cell value.

    Returns:
        The parsed price, or ``None`` when the cell is empty,
        ``"#N/A"``, or not parseable as a number.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = normalize_ws(value)
    if text == "" or text.upper() == "#N/A":
        return None

    cleaned = text.replace("\xa0", "").replace(" ", "")
    cleaned = re.sub(r"(?i)р\.?$", "", cleaned)  # drop trailing "р."/"р"
    cleaned = cleaned.replace(",", ".")

    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_amount(value: object) -> float:
    """Parse an availability value into a numeric stock quantity for
    current.csv's "amount" column.

    The source mixes real numbers with free-text statuses (e.g.
    ``"наличие уточняйте"``), which have no numeric meaning. Those —
    and anything else that doesn't parse as a number — become ``0.0``
    rather than raising or silently propagating text into a numeric
    CSV column.

    Args:
        value: Raw or already whitespace-normalized availability
            value (``str``, ``int``, ``float``).

    Returns:
        The parsed quantity, defaulting to ``0.0`` when the value is
        not numeric.
    """
    if isinstance(value, (int, float)):
        return float(value)
    text = normalize_ws(value).replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------
# Exclusion rules
# --------------------------------------------------------------------------

# Substrings (already lower-cased) that mark a "Тип" or "Серия" value as
# belonging to an excluded product category. Matching is done as
# "substring is contained in the normalized, lower-cased cell value", so
# it also catches trailing tabs/spaces and near-duplicate wordings such
# as "Расходные материалы ВЕНТ".
CATEGORY_EXCLUDE_KEYWORDS: tuple[str, ...] = (
    "расходные материалы",
    "очистители воздуха",
    "тепловые насосы",  # covers "для бассейнов" and other lines (e.g. VIKING)
    "аксессуары",
    "аксесуары",  # typo present in the source data
    "кабель",
)


def category_exclusion_reason(
    type_value: object, series_value: object
) -> Optional[str]:
    """Decide whether a row should be dropped based on its category.

    Checks, in order:
        1. Whether "Тип" is empty (the "undefined type" anomaly, e.g.
           НС-1761568 in the client's original example).
        2. Whether "Тип" contains one of ``CATEGORY_EXCLUDE_KEYWORDS``.
        3. Whether "Серия" contains one of ``CATEGORY_EXCLUDE_KEYWORDS``
           — some heat pumps are filed under a normal air-conditioner
           "Тип" but reveal themselves through "Серия" (e.g.
           "Тепловые насосы VIKING 2.0").

    Args:
        type_value: Raw "Тип" cell value.
        series_value: Raw "Серия" cell value.

    Returns:
        A human-readable reason string if the row should be excluded,
        otherwise ``None``.
    """
    norm_type = normalize_ws(type_value).lower()
    if norm_type == "":
        return "Тип не определён (пусто)"

    for keyword in CATEGORY_EXCLUDE_KEYWORDS:
        if keyword in norm_type:
            return f'Тип содержит "{keyword}"'

    norm_series = normalize_ws(series_value).lower()
    if norm_series:
        for keyword in CATEGORY_EXCLUDE_KEYWORDS:
            if keyword in norm_series:
                return f'Серия содержит "{keyword}"'

    return None


def price_exclusion_reason(
    retail_price: Optional[float], dealer_price: Optional[float]
) -> Optional[str]:
    """Decide whether a row should be dropped because of its price.

    A row is excluded if EITHER the retail price or the dealer price
    is missing (``None``) or equal to zero.

    Args:
        retail_price: Parsed retail price ("Розница"), or ``None``.
        dealer_price: Parsed dealer price ("Дилер"), or ``None``.

    Returns:
        A human-readable reason string if the row should be excluded,
        otherwise ``None``.
    """
    bad_fields = []
    if retail_price is None or retail_price == 0:
        bad_fields.append("Розница")
    if dealer_price is None or dealer_price == 0:
        bad_fields.append("Дилер")

    if not bad_fields:
        return None
    return f"Цена не определена или равна нулю ({', '.join(bad_fields)})"


# --------------------------------------------------------------------------
# Group ("category") -> current.csv "folder" mapping
# --------------------------------------------------------------------------

# Reasons used by the two new row-level anomalies below, exposed as
# constants so tests (and any caller) don't have to hard-code the
# Russian text a second time.
REASON_UNRESOLVED_GROUP = "Невозможно определить группу"
REASON_DUPLICATE_MODEL = "Дублирование модели"

FOLDER_MOBILE = "Каталог кондиционеров,Мобильные кондиционеры"
FOLDER_WINDOW = "Каталог кондиционеров,Оконные кондиционеры"
FOLDER_MULTI_SPLIT = "Каталог кондиционеров,Мульти-сплит-системы"
FOLDER_SEMI_INDUSTRIAL = "Каталог кондиционеров,Полупромышленные кондиционеры"
FOLDER_SPLIT = "Каталог кондиционеров,Сплит-системы"


def map_category_to_folder(category: str) -> Optional[str]:
    """Map a source-sheet group/section name to a current.csv "folder".

    Matching is case-insensitive and keyword/stem-based rather than
    exact-phrase, because the source data spells the same group
    several different ways (see the examples in each branch below —
    all taken directly from the real "1. Для заливки" sheet). Rules
    are checked in order and the first match wins, since some group
    names would otherwise match more than one rule (e.g. "Полупром­
    ышленные сплит-системы" contains both "полупром" and
    "сплит-систем").

    Rules:
        1. Contains "мобильные кондиционеры" (also catches
           "Промышленные мобильные кондиционеры") -> mobile.
        2. Contains both "оконн" and "кондиционер" (covers "Оконный
           кондиционер" and the source's actual "Оконные
           кондиционеры") -> window units.
        3. Contains "мульти", "сплит" and either "систем" or "ситем"
           (covers "Мультисплит-системы", "Мульти сплит-ситемы" and
           the source's third variant "Мульти-сплит ситемы") ->
           multi-split.
        4. Contains "полупром" (covers full "полупромышленные" AND
           the client's "ПОЛУПРОМ" abbreviation anomaly, since it's a
           prefix of the full word), OR contains "колонные
           кондиционер", OR contains both "канальн" and
           "высоконапорн" (covers the client's "Канальный
           высоконапорный кондиционер" and the source's actual
           "Высоконапорные канальники") -> semi-industrial.
        5. Otherwise, contains "кондиционер" or "сплит-систем" ->
           plain split systems (the catch-all bucket).
        6. Nothing matched (e.g. the source's "тошиба" anomaly, which
           names no recognisable category at all) -> ``None``.

    Args:
        category: Raw group/section text, as captured from the
            nearest preceding divider row.

    Returns:
        The mapped ``folder`` value, or ``None`` if no rule matched
        — the caller should treat that row as excluded (reason
        ``REASON_UNRESOLVED_GROUP``).
    """
    text = normalize_ws(category).lower()
    if not text:
        return None

    if "мобильные кондиционеры" in text:
        return FOLDER_MOBILE

    if "оконн" in text and "кондиционер" in text:
        return FOLDER_WINDOW

    if "мульти" in text and "сплит" in text and ("систем" in text or "ситем" in text):
        return FOLDER_MULTI_SPLIT

    if (
        "полупром" in text
        or "колонные кондиционер" in text
        or ("канальн" in text and "высоконапорн" in text)
    ):
        return FOLDER_SEMI_INDUSTRIAL

    if "кондиционер" in text or "сплит-систем" in text:
        return FOLDER_SPLIT

    return None


# --------------------------------------------------------------------------
# Duplicate нс-код handling
# --------------------------------------------------------------------------


def assign_duplicate_codes(
    items: list[ProductRecord], existing_map: DuplicateMap
) -> tuple[list[ProductRecord], DuplicateMap, int]:
    """Assign stable, unique codes to rows that share a нс-код.

    Stability contract
    -------------------
    Every physical duplicate row is identified by
    ``(original_code, model, occurrence)``, where ``occurrence`` is the
    1-based index of that exact (code, model) pair among rows sharing
    the same code, counted in the order the rows appear in ``items``
    (i.e. the source file's row order). This disambiguates the rare
    case of two rows with an identical code AND an identical model.

    The FIRST time a given нс-код is seen as a duplicate, its rows are
    sorted by model (a stable sort, so ties keep their original file
    order) and assigned in that order: the first row keeps the bare
    code, the rest get ``-D01``, ``-D02``, … This initial assignment is
    written to ``existing_map`` (all of it, including the bare one) so
    it never needs to be recomputed.

    On every later run, any identity already present in
    ``existing_map`` simply reuses its stored code — regardless of the
    current row order in the source file, and regardless of whether
    other duplicates were added or removed for that same code. Any
    identity that is genuinely new (never recorded before) gets the
    next free ``-D0N`` suffix for that code, appended after whatever
    was already used.

    If a нс-код that used to be duplicated becomes unique again (the
    supplier fixed it), it is simply left as-is; old entries for it in
    ``existing_map`` become unused but are harmless and are kept as
    history rather than deleted.

    Args:
        items: Kept records, in source row order.
        existing_map: Previously persisted duplicate mapping, loaded
            from ``duplicate_mapping.py``. Not mutated in place — a
            new dict is returned.

    Returns:
        A tuple of:
            - the same records, with ``.code`` rewritten where needed;
            - the updated mapping (``existing_map`` plus any new
              entries, ready to be written back to disk);
            - how many rows actually received a ``-D0N`` suffix.
    """
    updated_map: DuplicateMap = dict(existing_map)
    renamed_count = 0

    # Group row indices by their (still bare) нс-код, preserving the
    # original source order within each group.
    indices_by_code: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        indices_by_code[item.code].append(index)

    for code, indices in indices_by_code.items():
        if len(indices) <= 1:
            continue  # not a duplicate, nothing to do

        # Compute the stable (code, model, occurrence) identity for
        # every row in this group, in source order.
        model_occurrence_counter: dict[str, int] = defaultdict(int)
        identities: list[DuplicateKey] = []
        for index in indices:
            model = items[index].model
            model_occurrence_counter[model] += 1
            identities.append((code, model, model_occurrence_counter[model]))

        # Bootstrap the canonical assignment for this code the first
        # time we see it (i.e. none of its identities are mapped yet).
        if not any(identity in updated_map for identity in identities):
            # Deterministic order: sort by model, stable sort keeps
            # original file order for exact ties.
            order = sorted(range(len(indices)), key=lambda i: items[indices[i]].model)
            for position, item_pos in enumerate(order):
                identity = identities[item_pos]
                if position == 0:
                    updated_map[identity] = code  # first item keeps the bare code
                else:
                    updated_map[identity] = f"{code}-D{position:02d}"

        # Any identity still missing (a brand-new duplicate for a code
        # we already have partial history for) gets the next free
        # suffix number for this code.
        used_suffixes = {
            int(match.group(1))
            for value in updated_map.values()
            if value.startswith(f"{code}-D")
            for match in [re.match(rf"^{re.escape(code)}-D(\d+)$", value)]
            if match
        }
        next_suffix = (max(used_suffixes) + 1) if used_suffixes else 1
        for identity in identities:
            if identity not in updated_map:
                updated_map[identity] = f"{code}-D{next_suffix:02d}"
                next_suffix += 1

        # Apply the (now complete) mapping to the actual records.
        for index, identity in zip(indices, identities):
            assigned = updated_map[identity]
            if assigned != items[index].code:
                items[index].code = assigned
                renamed_count += 1

    return items, updated_map, renamed_count


def load_duplicate_map(path: Path) -> DuplicateMap:
    """Load ``DUPLICATE_CODE_MAP`` from a duplicate-mapping module.

    Uses ``importlib`` (rather than a plain ``import``) so the module
    can live anywhere on disk, and returns an empty mapping if the
    file does not exist yet (first run).

    Args:
        path: Path to the ``duplicate_mapping.py`` module.

    Returns:
        The loaded mapping, or an empty dict if the file is missing.
    """
    if not path.exists():
        return {}

    spec = importlib.util.spec_from_file_location("duplicate_mapping", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return {}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(getattr(module, "DUPLICATE_CODE_MAP", {}))


def write_duplicate_map(mapping: DuplicateMap, path: Path) -> None:
    """Write ``mapping`` out as a self-contained, human-editable Python
    module, sorted by key for a stable, diff-friendly file.

    Args:
        mapping: The duplicate mapping to persist.
        path: Destination path for the generated module.
    """
    lines = [
        '"""Persistent mapping of duplicate нс-коды to their assigned',
        "unique codes. Auto-generated and updated by clean_reference.py",
        "on every run — safe to edit by hand, entries you add are kept.",
        '"""',
        "",
        "# key: (original_code, model, occurrence_of_this_code_model_pair)",
        "# value: assigned unique code (bare code for the first",
        "#        occurrence, '-D01' / '-D02' / ... for the rest)",
        "DUPLICATE_CODE_MAP: dict[tuple[str, str, int], str] = {",
    ]
    for key in sorted(mapping.keys()):
        code, model, occurrence = key
        value = mapping[key]
        lines.append(f"    {(code, model, occurrence)!r}: {value!r},")
    lines.append("}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# Slug / URL generation (for brand-new current.csv rows)
# --------------------------------------------------------------------------

# Standard Russian -> Latin transliteration table used for building
# readable URL slugs. ъ and ь have no Latin sound and are dropped.
_TRANSLIT_MAP: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def transliterate_ru(text: str) -> str:
    """Transliterate Russian (Cyrillic) letters in ``text`` to Latin.

    Case-preserving at the input level (matching is done against a
    lower-cased copy, letters not found in the map pass through
    unchanged) — but callers building a URL slug should lower-case the
    result afterwards via ``slugify``.

    Args:
        text: Text possibly containing Cyrillic letters.

    Returns:
        The same text with every Cyrillic letter replaced by its
        Latin transliteration; non-Cyrillic characters are untouched.
    """
    result = []
    for char in text:
        lower = char.lower()
        if lower in _TRANSLIT_MAP:
            replacement = _TRANSLIT_MAP[lower]
            result.append(
                replacement.upper() if char.isupper() and replacement else replacement
            )
        else:
            result.append(char)
    return "".join(result)


def slugify(text: str) -> str:
    """Turn arbitrary text into a lower-case, hyphen-separated URL slug.

    Steps: transliterate Cyrillic to Latin, lower-case, replace every
    run of characters that isn't a letter/digit with a single hyphen,
    then trim leading/trailing hyphens.

    Args:
        text: Arbitrary text (e.g. a product name).

    Returns:
        A URL-safe slug, e.g. ``"electrolux-fusion-ultra-eacs-i-18hf-n8"``.
    """
    text = transliterate_ru(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def build_unique_sef_url(
    name: str, existing_urls: set[str], prefix: str = "glavnaya-magazina/product"
) -> str:
    """Build a ``sef_url`` value for a new product, unique among
    ``existing_urls``.

    Args:
        name: The product's "name" field to slugify.
        existing_urls: Every ``sef_url`` already in use (current.csv's
            existing values plus any already assigned earlier in this
            same run). NOT mutated — the caller is expected to add the
            returned URL to this set before the next call.
        prefix: Path prefix matching the store's URL scheme.

    Returns:
        A ``"{prefix}/{slug}"`` URL, with a ``-2``, ``-3``, … suffix
        appended to the slug if the base URL is already taken.
    """
    base_slug = slugify(name)
    candidate = f"{prefix}/{base_slug}"
    if candidate not in existing_urls:
        return candidate

    suffix = 2
    while f"{prefix}/{base_slug}-{suffix}" in existing_urls:
        suffix += 1
    return f"{prefix}/{base_slug}-{suffix}"
