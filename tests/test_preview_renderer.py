# tests/test_preview_renderer.py
import json
from PIL import Image

from extractor.preview_renderer import render_patient_preview
from models import PatientBlock


def _patient_with_full_cells():
    """Realistic patient with 8-row table cells (some duplicated from Word merges)."""
    cells = [
        {'row': 0, 'col': 0, 'text': 'Patient Details'},
        {'row': 0, 'col': 1, 'text': 'Cancer Target Dates'},
        {'row': 1, 'col': 0, 'text': 'Hospital Number: H001\nNHS Number: 9990000001\nJohn Smith\nMale\nDOB: 01/01/1960'},
        {'row': 1, 'col': 1, 'text': '62 DAY TARGET: 01/03/2025'},
        {'row': 2, 'col': 0, 'text': 'Staging & Diagnosis(g)'},
        {'row': 3, 'col': 0, 'text': 'Diagnosis: Rectal adenocarcinoma\nT3N1M0'},
        {'row': 3, 'col': 1, 'text': 'Staging:\nIntegrated TNM Stage: III'},
        {'row': 4, 'col': 0, 'text': 'Clinical Details(f)'},
        {'row': 5, 'col': 0, 'text': 'Colonoscopy: Polyp at 10cm. Biopsy taken.'},
        {'row': 6, 'col': 0, 'text': 'MDT Outcome(h)'},
        {'row': 7, 'col': 0, 'text': 'Outcome: Anterior resection. MMR proficient.'},
    ]
    return PatientBlock(
        id='H001', initials='JS', nhs_number='9990000001',
        mdt_date='07/03/2025', raw_cells=cells,
    )


def test_render_creates_png(tmp_path):
    render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    assert (tmp_path / 'H001.png').exists()


def test_render_creates_json(tmp_path):
    render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    assert (tmp_path / 'H001.json').exists()


def test_coord_map_has_key_content_cells(tmp_path):
    """Coords must cover the cells that source_cell references point to."""
    coords = render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    # Patient details and cancer dates
    assert '1,0' in coords
    assert '1,1' in coords
    # Staging content
    assert '3,0' in coords
    assert '3,1' in coords
    # Clinical freeform
    assert '5,0' in coords
    # MDT freeform
    assert '7,0' in coords
    # Section headers
    assert '0,0' in coords
    assert '2,0' in coords
    assert '4,0' in coords
    assert '6,0' in coords


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
    patient = PatientBlock(id='EMPTY', raw_cells=[
        {'row': 0, 'col': 0, 'text': 'Patient Details'},
        {'row': 1, 'col': 0, 'text': ''},
        {'row': 5, 'col': 0, 'text': ''},
        {'row': 7, 'col': 0, 'text': ''},
    ])
    coords = render_patient_preview(patient, str(tmp_path))
    assert (tmp_path / 'EMPTY.png').exists()


def test_render_returns_empty_dict_for_no_cells(tmp_path):
    patient = PatientBlock(id='NOCELLS', raw_cells=[])
    coords = render_patient_preview(patient, str(tmp_path))
    assert coords == {}


def test_preview_uses_unique_id_for_filename(tmp_path):
    patient = PatientBlock(id='H001', unique_id='07032025_JS_M_H001', raw_cells=[
        {'row': 0, 'col': 0, 'text': 'Patient Details'},
        {'row': 1, 'col': 0, 'text': 'Hospital Number: H001'},
    ])
    render_patient_preview(patient, str(tmp_path))
    assert (tmp_path / '07032025_JS_M_H001.png').exists()
    assert not (tmp_path / 'H001.png').exists()
