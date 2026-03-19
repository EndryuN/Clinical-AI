import json
import re
from models import FieldResult

def parse_llm_response(raw_response: str, group: dict) -> dict[str, FieldResult]:
    expected_keys = [f['key'] for f in group['fields']]
    field_types = {f['key']: f['type'] for f in group['fields']}

    data = _extract_json(raw_response)
    if data is None:
        return {key: FieldResult(value=None, confidence="low") for key in expected_keys}

    results = {}
    for key in expected_keys:
        if key in data and isinstance(data[key], dict):
            value = data[key].get('value')
            confidence = data[key].get('confidence', 'low')
            confidence = confidence.lower() if isinstance(confidence, str) else 'low'
            if confidence not in ('high', 'medium', 'low'):
                confidence = 'low'
        else:
            value = None
            confidence = 'low'

        if value is not None:
            value = str(value).strip()
            if value.lower() in ('null', 'none', 'n/a', ''):
                value = None

        confidence = _apply_confidence_overrides(value, confidence, field_types.get(key, 'string'))
        results[key] = FieldResult(value=value, confidence=confidence)

    return results

def _extract_json(raw: str) -> dict | None:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None

def _apply_confidence_overrides(value, confidence: str, field_type: str) -> str:
    if value is None:
        return 'low'
    if field_type == 'date':
        if not re.match(r'\d{1,2}/\d{1,2}/\d{4}', value):
            return 'low'
    return confidence
