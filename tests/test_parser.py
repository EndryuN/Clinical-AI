from unittest.mock import MagicMock
from parser.docx_parser import _table_to_cells

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

def test_table_to_cells_returns_all_cells_with_coordinates():
    table = _make_fake_table([
        ["Patient Details", "Patient Details", "Cancer Target Dates"],
        ["NHS: 001", "NHS: 001", "31-day: 01/01/2025"],
    ])
    cells = _table_to_cells(table)
    assert len(cells) == 6  # 2 rows × 3 cols
    assert cells[0] == {"row": 0, "col": 0, "text": "Patient Details"}
    assert cells[5] == {"row": 1, "col": 2, "text": "31-day: 01/01/2025"}

def test_table_to_cells_includes_empty_cells():
    table = _make_fake_table([["Hello", "", "World"]])
    cells = _table_to_cells(table)
    assert len(cells) == 3
    assert cells[1] == {"row": 0, "col": 1, "text": ""}

def test_table_to_cells_strips_whitespace():
    table = _make_fake_table([["  spaced  ", "\ttabbed\n"]])
    cells = _table_to_cells(table)
    assert cells[0]["text"] == "spaced"
    assert cells[1]["text"] == "tabbed"
