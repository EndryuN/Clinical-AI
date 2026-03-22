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
