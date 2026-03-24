import json
import re
from models import FieldResult
from spellchecker import SpellChecker

_spell = SpellChecker()
# Add medical/clinical terms so they don't get flagged as misspellings
_spell.word_frequency.load_words([
    'adenocarcinoma', 'carcinoma', 'colonoscopy', 'sigmoidoscopy', 'flexisigmoidoscopy',
    'flexi', 'sig', 'ileocecal', 'rectosigmoid', 'mesorectal', 'circumferential',
    'neoadjuvant', 'chemoradiotherapy', 'capecitabine', 'oxaliplatin', 'folfox', 'capox',
    'pembrolizumab', 'nivolumab', 'immunotherapy', 'radiotherapy', 'chemotherapy',
    'deficient', 'proficient', 'emvi', 'crm', 'psw', 'trg', 'tnm', 'mri', 'mdt',
    'nhs', 'mrn', 'dob', 'icd', 'cea', 'dre', 'hpb', 'tnt',
    'rectal', 'rectum', 'sigmoid', 'caecum', 'colon', 'hepatic', 'splenic',
    'transverse', 'ascending', 'descending', 'peritoneal', 'retroperitoneal',
    'ampulla', 'neoplasm', 'malignant', 'differentiated', 'moderately', 'poorly',
    'ulceration', 'mucinous', 'polypoid', 'sessile', 'pedunculated',
    'metastasis', 'metastatic', 'palliative', 'curative', 'adjuvant',
    'stoma', 'defunctioned', 'hemicolectomy', 'colectomy', 'resection',
    'gy', 'ebrt', 'papillon', 'concomitant', 'concomittant',
    'gleason', 'prostate', 'polyneuropathy', 'demyelinating', 'stenosis',
    'ct', 'pet', 'ivc', 'seg',
])


def _check_spelling(text: str) -> list[str]:
    """Return list of potentially misspelled words in the text."""
    if not text or len(text) < 3:
        return []
    # Extract words (skip numbers, single chars, abbreviations in all-caps)
    words = re.findall(r'[a-zA-Z]{3,}', text)
    misspelled = []
    for word in words:
        # Skip all-uppercase abbreviations (e.g., EMVI, TNM, MRI)
        if word.isupper() and len(word) <= 5:
            continue
        if word.lower() not in _spell and _spell.unknown([word.lower()]):
            misspelled.append(word)
    return misspelled

def parse_llm_response(raw_response: str, group: dict) -> dict[str, FieldResult]:
    expected_keys = [f['key'] for f in group['fields']]
    field_types = {f['key']: f['type'] for f in group['fields']}

    data = _extract_json(raw_response)
    if data is None:
        return {key: FieldResult(value=None, confidence_basis="absent") for key in expected_keys}

    results = {}
    for key in expected_keys:
        reason = ""
        if key in data and isinstance(data[key], dict):
            value = data[key].get('value')
            confidence = data[key].get('confidence', 'low')
            reason = data[key].get('reason', '')
            source_section = data[key].get('source_section') if key in data and isinstance(data[key], dict) else None
            confidence = confidence.lower() if isinstance(confidence, str) else 'low'
            if confidence not in ('high', 'medium', 'low'):
                confidence = 'low'
            # Cap: LLM may not claim HIGH — only regex earns HIGH
            if confidence == 'high':
                confidence = 'medium'
        else:
            value = None
            confidence = 'low'
            source_section = None

        if value is not None:
            value = str(value).strip()
            if value.lower() in ('null', 'none', 'n/a', 'missing', ''):
                value = None

        if value is None:
            confidence = 'none'
            reason = "Field not mentioned in the document"

        # Check for misspellings in text values
        if value is not None and field_types.get(key) == 'text':
            typos = _check_spelling(value)
            if typos:
                reason = f"[Possible misspelling: {', '.join(typos[:3])}] {reason}"

        # Map old confidence string to temporary basis — refined in Task 4
        _basis_tmp = {"high": "freeform_verbatim", "medium": "freeform_verbatim",
                      "low": "freeform_inferred", "none": "absent"}.get(confidence, "freeform_inferred")
        results[key] = FieldResult(
            value=value, confidence_basis=_basis_tmp, reason=reason, source_snippet=source_section
        )

    return results

def _extract_json(raw: str) -> dict | None:
    # Strip qwen3 <think>...</think> blocks before parsing
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
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
    # Null values are not "low confidence" — they're just absent from the document
    if value is None:
        return 'none'  # "none" = not mentioned, distinct from "low" = uncertain
    if field_type == 'date':
        if not re.match(r'\d{1,2}/\d{1,2}/\d{4}', value):
            return 'low'
    return confidence
