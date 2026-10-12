"""Persistent mapping of duplicate нс-коды to their assigned
unique codes. Auto-generated and updated by clean_reference.py
on every run — safe to edit by hand, entries you add are kept.
"""

# key: (original_code, model, occurrence_of_this_code_model_pair)
# value: assigned unique code (bare code for the first
#        occurrence, '-D01' / '-D02' / ... for the rest)
DUPLICATE_CODE_MAP: dict[tuple[str, str, int], str] = {
    ("НС-1442717", "RAS-B05CKVG-EE", 1): "НС-1442717",
    ("НС-1442717", "RAS-B05СKVG-EЕ", 1): "НС-1442717-D01",
    ("НС-1442720", "RAS-B07CKVG-EE", 1): "НС-1442720",
    ("НС-1442720", "RAS-B07СKVG-EЕ", 1): "НС-1442720-D01",
    ("НС-1580634", "RAS-13J2AVSG-E1", 1): "НС-1580634",
    ("НС-1580634", "RAS-13СAVG-EE", 1): "НС-1580634-D01",
    ("НС-1580634", "RAS-B13G3KVSG-E", 1): "НС-1580634-D02",
    ("НС-1580788", "RAS-B10CKVG-E NEW", 1): "НС-1580788",
    ("НС-1580788", "RAS-B10СKVG-EЕ", 1): "НС-1580788-D01",
    ("НС-1580791", "RAS-B13CKVG-E NEW", 1): "НС-1580791",
    ("НС-1580791", "RAS-B13СKVG-EЕ", 1): "НС-1580791-D01",
}
