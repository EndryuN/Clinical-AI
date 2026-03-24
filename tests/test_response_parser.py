import json
from extractor.response_parser import parse_llm_response

def _make_group(keys):
    return {'fields': [{'key': k, 'type': 'string'} for k in keys]}

FREEFORM_CELLS = [
    {"row": 4, "col": 0, "text": "Clinical details header"},
    {"row": 5, "col": 0, "text": "Patient has T3 tumour. Mass at 13cm from anal verge. EMVI positive."},
    {"row": 6, "col": 0, "text": "MDT outcome header"},
    {"row": 7, "col": 0, "text": "Outcome: CAPOX chemotherapy planned. Consider surgery after response."},
]

def test_llm_value_in_freeform_text_gives_freeform_verbatim():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({
        'endoscopy_findings': {'value': 'Mass at 13cm', 'confidence': 'high', 'reason': 'verbatim'}
    })
    results = parse_llm_response(raw, group, raw_cells=FREEFORM_CELLS)
    assert results['endoscopy_findings'].confidence_basis == "freeform_verbatim"

def test_llm_invented_value_gives_freeform_inferred():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({
        'endoscopy_findings': {'value': 'polyp at 8cm', 'confidence': 'medium', 'reason': 'inferred'}
    })
    results = parse_llm_response(raw, group, raw_cells=FREEFORM_CELLS)
    assert results['endoscopy_findings'].confidence_basis == "freeform_inferred"

def test_llm_verbatim_check_uses_source_snippet_first():
    group = _make_group(['mmr_status'])
    raw = json.dumps({
        'mmr_status': {'value': 'Proficient', 'confidence': 'medium',
                       'reason': 'stated', 'source_section': '(g)'}
    })
    results = parse_llm_response(raw, group, raw_cells=FREEFORM_CELLS)
    assert results['mmr_status'].confidence_basis == "freeform_inferred"

def test_null_value_gives_absent_basis():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({'endoscopy_findings': {'value': None, 'confidence': 'high', 'reason': ''}})
    results = parse_llm_response(raw, group, raw_cells=FREEFORM_CELLS)
    assert results['endoscopy_findings'].confidence_basis == "absent"
    assert results['endoscopy_findings'].value is None

def test_llm_source_cell_set_when_verbatim_match():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({
        'endoscopy_findings': {'value': 'Mass at 13cm', 'confidence': 'medium', 'reason': ''}
    })
    results = parse_llm_response(raw, group, raw_cells=FREEFORM_CELLS)
    assert results['endoscopy_findings'].source_cell == {"row": 5, "col": 0}

def test_null_value_gets_none_confidence():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({
        'endoscopy_findings': {'value': None, 'confidence': 'high', 'reason': ''}
    })
    results = parse_llm_response(raw, group, raw_cells=FREEFORM_CELLS)
    assert results['endoscopy_findings'].confidence == 'none'
    assert results['endoscopy_findings'].value is None

def test_source_section_stored_in_source_snippet():
    group = {'fields': [{'key': 'mmr_status', 'type': 'string'}]}
    raw = json.dumps({
        'mmr_status': {
            'value': 'Proficient',
            'confidence': 'medium',
            'reason': 'stated in text',
            'source_section': '(g)'
        }
    })
    results = parse_llm_response(raw, group, raw_cells=FREEFORM_CELLS)
    assert results['mmr_status'].source_snippet == '(g)'


def test_missing_source_section_gives_none():
    group = {'fields': [{'key': 'dob', 'type': 'date'}]}
    raw = json.dumps({
        'dob': {'value': '01/01/1970', 'confidence': 'medium', 'reason': 'stated'}
    })
    results = parse_llm_response(raw, group, raw_cells=FREEFORM_CELLS)
    assert results['dob'].source_snippet is None
