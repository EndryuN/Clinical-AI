import json
from extractor.response_parser import parse_llm_response

def _make_group(keys):
    return {'fields': [{'key': k, 'type': 'string'} for k in keys]}

def test_llm_high_confidence_capped_to_medium():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({
        'endoscopy_findings': {'value': 'Mass at 13cm', 'confidence': 'high', 'reason': 'verbatim'}
    })
    results = parse_llm_response(raw, group)
    assert results['endoscopy_findings'].confidence == 'medium'

def test_llm_low_confidence_kept():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({
        'endoscopy_findings': {'value': 'Something', 'confidence': 'low', 'reason': 'uncertain'}
    })
    results = parse_llm_response(raw, group)
    assert results['endoscopy_findings'].confidence == 'low'

def test_llm_medium_confidence_unchanged():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({
        'endoscopy_findings': {'value': 'Something', 'confidence': 'medium', 'reason': ''}
    })
    results = parse_llm_response(raw, group)
    assert results['endoscopy_findings'].confidence == 'medium'

def test_null_value_gets_none_confidence():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({
        'endoscopy_findings': {'value': None, 'confidence': 'high', 'reason': ''}
    })
    results = parse_llm_response(raw, group)
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
    results = parse_llm_response(raw, group)
    assert results['mmr_status'].source_snippet == '(g)'


def test_missing_source_section_gives_none():
    group = {'fields': [{'key': 'dob', 'type': 'date'}]}
    raw = json.dumps({
        'dob': {'value': '01/01/1970', 'confidence': 'medium', 'reason': 'stated'}
    })
    results = parse_llm_response(raw, group)
    assert results['dob'].source_snippet is None
