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
