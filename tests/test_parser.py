from unittest.mock import MagicMock
from parser.docx_parser import _table_to_cells, _extract_gender

def _make_fake_table(rows_data):
    """rows_data: list of list of str — row × col cell text."""
    table = MagicMock()
    fake_rows = []
    for row_texts in rows_data:
        row = MagicMock()
        row.cells = [MagicMock(text=t) for t in row_texts]
        fake_rows.append(row)
    table.rows = fake_rows
    return table

def test_table_to_cells_deduplicates_adjacent_same_text():
    """Adjacent cells with identical text (Word merged cells) are deduplicated."""
    table = _make_fake_table([
        ["Patient Details", "Patient Details", "Cancer Target Dates"],
        ["NHS: 001", "NHS: 001", "31-day: 01/01/2025"],
    ])
    cells = _table_to_cells(table)
    assert len(cells) == 4  # 2 unique per row after dedup
    assert cells[0] == {"row": 0, "col": 0, "text": "Patient Details"}
    assert cells[1] == {"row": 0, "col": 1, "text": "Cancer Target Dates"}
    assert cells[2] == {"row": 1, "col": 0, "text": "NHS: 001"}
    assert cells[3] == {"row": 1, "col": 1, "text": "31-day: 01/01/2025"}


def test_table_to_cells_keeps_unique_cells():
    """Cells with different text in the same row are all kept."""
    table = _make_fake_table([
        ["Diagnosis: Adeno", "Staging: T3N1", "Dukes: C"],
    ])
    cells = _table_to_cells(table)
    assert len(cells) == 3


def test_table_to_cells_includes_empty_cells():
    table = _make_fake_table([["Hello", "", "World"]])
    cells = _table_to_cells(table)
    # Empty cell differs from "Hello" so it's kept; "World" differs from "" so kept
    assert len(cells) == 3
    assert cells[1] == {"row": 0, "col": 1, "text": ""}

def test_table_to_cells_strips_whitespace():
    table = _make_fake_table([["  spaced  ", "\ttabbed\n"]])
    cells = _table_to_cells(table)
    assert cells[0]["text"] == "spaced"
    assert cells[1]["text"] == "tabbed"


def test_extract_gender_from_demographics_cell():
    cell = "Hospital Number: 001\nNHS Number: 001\nAlice Test\nFemale (e) DOB: 01/01/1980"
    assert _extract_gender(cell) == "Female"

def test_extract_gender_male():
    cell = "Hospital Number: 001\nNHS Number: 001\nBob Jones\nMale (e) DOB: 05/03/1972"
    assert _extract_gender(cell) == "Male"

def test_extract_gender_missing_returns_empty():
    cell = "Hospital Number: 001\nNHS Number: 001\nBob Jones\nDOB: 05/03/1972"
    assert _extract_gender(cell) == ""
