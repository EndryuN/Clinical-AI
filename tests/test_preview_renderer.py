# tests/test_preview_renderer.py
import json
from PIL import Image

from extractor.preview_renderer import render_patient_preview
from models import PatientBlock


def _patient_with_full_cells():
    """8×3 table with realistic content."""
    texts = {
        (0, 0): 'Patient Details(a)(b)(c)(d)(e)',
        (0, 1): 'Patient Details(a)(b)(c)(d)(e)',
        (0, 2): 'Cancer Target Dates',
        (1, 0): 'Hospital Number: H001\nNHS Number: 9990000001\nJohn Smith\nMale\nDOB: 01/01/1960',
        (1, 1): 'Hospital Number: H001\nNHS Number: 9990000001\nJohn Smith\nMale\nDOB: 01/01/1960',
        (1, 2): '',
        (2, 0): 'Staging & Diagnosis(g)',
        (2, 1): '',
        (2, 2): '',
        (3, 0): 'Diagnosis: Rectal adenocarcinoma\nT3N1M0',
        (3, 1): 'Diagnosis: Rectal adenocarcinoma\nT3N1M0',
        (3, 2): '',
        (4, 0): 'Clinical Details(f)',
        (4, 1): '',
        (4, 2): '',
        (5, 0): 'Colonoscopy: Polyp at 10cm. Biopsy taken.',
        (5, 1): 'Colonoscopy: Polyp at 10cm. Biopsy taken.',
        (5, 2): '',
        (6, 0): 'MDT Outcome(h)',
        (6, 1): '',
        (6, 2): '',
        (7, 0): 'Outcome: Anterior resection. MMR proficient.',
        (7, 1): 'Outcome: Anterior resection. MMR proficient.',
        (7, 2): '',
    }
    cells = [{'row': r, 'col': c, 'text': texts.get((r, c), '')} for r in range(8) for c in range(3)]
    return PatientBlock(id='H001', initials='JS', nhs_number='9990000001', raw_cells=cells)


def test_render_creates_png(tmp_path):
    render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    assert (tmp_path / 'H001.png').exists()


def test_render_creates_json(tmp_path):
    render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    assert (tmp_path / 'H001.json').exists()


def test_coord_map_covers_all_cells(tmp_path):
    coords = render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    for r in range(8):
        for c in range(3):
            assert f'{r},{c}' in coords, f'Missing coord for row={r} col={c}'


def test_coord_map_json_matches_return_value(tmp_path):
    coords = render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    with open(tmp_path / 'H001.json') as f:
        saved = json.load(f)
    assert coords == saved


def test_image_width_is_800(tmp_path):
    render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    img = Image.open(tmp_path / 'H001.png')
    assert img.width == 800


def test_render_empty_cells_doesnt_crash(tmp_path):
    cells = [{'row': r, 'col': c, 'text': ''} for r in range(8) for c in range(3)]
    patient = PatientBlock(id='EMPTY', raw_cells=cells)
    render_patient_preview(patient, str(tmp_path))
    assert (tmp_path / 'EMPTY.png').exists()


def test_render_returns_empty_dict_for_no_cells(tmp_path):
    patient = PatientBlock(id='NOCELLS', raw_cells=[])
    result = render_patient_preview(patient, str(tmp_path))
    assert result == {}
