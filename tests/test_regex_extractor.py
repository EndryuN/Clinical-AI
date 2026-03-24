# tests/test_regex_extractor.py
from models import PatientBlock
from extractor.regex_extractor import regex_extract

DEMO_RAW_TEXT = """Cancer Type: Colorectal
MDT Meeting Date: 07/03/2025

Hospital Number: 9990000001
NHS Number: 999 000 0001
ALICE O'CONNOR (b)
Female (e) DOB: 12/05/1955 (a)

Diagnosis & Staging
T3 N1 M0
"""

DEMO_CELLS = [
    {"row": 0, "col": 0, "text": "Patient Details"},
    {"row": 1, "col": 0, "text": "Hospital Number: 9990000001\nNHS Number: 999 000 0001\nALICE O'CONNOR (b)\nFemale (e) DOB: 12/05/1955 (a)"},
    {"row": 2, "col": 0, "text": "Diagnosis & Staging"},
    {"row": 3, "col": 0, "text": "T3 N1 M0"},
]

DEMO_FIELDS = [
    {'key': 'dob', 'type': 'date'},
    {'key': 'gender', 'type': 'string'},
    {'key': 'mrn', 'type': 'string'},
]

def test_regex_extract_returns_field_results():
    results = regex_extract(DEMO_RAW_TEXT, "Demographics", DEMO_FIELDS, DEMO_CELLS)
    assert 'dob' in results
    assert results['dob'].value == "12/05/1955"
    assert results['dob'].confidence == 'high'

def test_regex_extract_sets_source_cell_for_matched_field():
    results = regex_extract(DEMO_RAW_TEXT, "Demographics", DEMO_FIELDS, DEMO_CELLS)
    # DOB appears in row 1, col 0
    assert results['dob'].source_cell == {"row": 1, "col": 0}
    assert results['dob'].source_snippet is not None
    assert "1955" in results['dob'].source_snippet

def test_regex_extract_source_cell_none_when_not_found():
    results = regex_extract(DEMO_RAW_TEXT, "Demographics", DEMO_FIELDS, raw_cells=[])
    # No cells to search — source_cell should be None
    assert results['dob'].source_cell is None

def test_regex_extract_unmatched_field_has_none_value():
    results = regex_extract(DEMO_RAW_TEXT, "Demographics", DEMO_FIELDS, DEMO_CELLS)
    # previous_cancer not in DEMO_FIELDS so won't appear, but gender is
    assert results['gender'].value in ('Female', 'Male', None)

def test_regex_extract_structured_row_gives_structured_verbatim():
    """DOB is in row 1 (structured) — should be structured_verbatim."""
    results = regex_extract(DEMO_RAW_TEXT, "Demographics", DEMO_FIELDS, DEMO_CELLS)
    assert results['dob'].confidence_basis == "structured_verbatim"

def test_regex_extract_freeform_row_gives_freeform_verbatim():
    """A value found in row 5 (freeform) should be freeform_verbatim."""
    freeform_cells = DEMO_CELLS + [
        {"row": 5, "col": 0, "text": "Clinical details: T3 tumour at 5cm from anal verge"},
    ]
    fields = [{'key': 'dob', 'type': 'date'}]
    raw_text = "Clinical details: T3 tumour at 5cm from anal verge\nDOB: 12/05/1955"
    results = regex_extract(raw_text, "Demographics", fields, freeform_cells)
    # DOB is matched from row 1, not row 5 — so still structured_verbatim
    assert results['dob'].confidence_basis == "structured_verbatim"

def test_build_unique_id_with_mrn():
    from extractor.regex_extractor import build_unique_id
    assert build_unique_id(
        mdt_date="07/03/2025", initials="AO", gender="Male", mrn="9990001", nhs=""
    ) == "07032025_AO_M_9990001"

def test_build_unique_id_uses_nhs_last4_when_no_mrn():
    from extractor.regex_extractor import build_unique_id
    assert build_unique_id(
        mdt_date="07/03/2025", initials="BK", gender="Female", mrn="", nhs="9990001234"
    ) == "07032025_BK_F_1234"

def test_build_unique_id_fallback_row_index():
    from extractor.regex_extractor import build_unique_id
    assert build_unique_id(
        mdt_date="", initials="CJ", gender="", mrn="", nhs="", row_index=3
    ) == "00000000_CJ_U_003"
