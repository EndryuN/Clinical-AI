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

def parse_llm_response(raw_response: str, group: dict,
                       raw_cells: list | None = None) -> dict[str, FieldResult]:
    expected_keys = [f['key'] for f in group['fields']]
    field_types = {f['key']: f['type'] for f in group['fields']}

    raw_cells = raw_cells or []
    freeform_cells = [c for c in raw_cells if c.get('row', 0) in {4, 5, 6, 7}]

    data = _extract_json(raw_response)
    if data is None:
        return {key: FieldResult(value=None, confidence_basis="absent") for key in expected_keys}

    results = {}
    for key in expected_keys:
        reason = ""
        if key in data and isinstance(data[key], dict):
            value = data[key].get('value')
            reason = data[key].get('reason', '')
            source_section = data[key].get('source_section')
        else:
            value = None
            source_section = None

        if value is not None:
            value = str(value).strip()
            if value.lower() in ('null', 'none', 'n/a', 'missing', ''):
                value = None

        if value is None:
            reason = reason or "Field not mentioned in the document"

        # Check for misspellings in text values
        if value is not None and field_types.get(key) == 'text':
            typos = _check_spelling(value)
            if typos:
                reason = f"[Possible misspelling: {', '.join(typos[:3])}] {reason}"

        # Determine confidence_basis via verbatim check
        if value is None:
            basis = "absent"
            source_cell = None
            source_snippet = None
        else:
            source_snippet = source_section  # from LLM response
            source_cell = None
            basis = "freeform_inferred"  # default until proven verbatim

            # Step 1: check source_snippet in freeform cells
            if source_snippet:
                for cell in freeform_cells:
                    if source_snippet.lower() in cell['text'].lower():
                        basis = "freeform_verbatim"
                        source_cell = {"row": cell["row"], "col": cell["col"]}
                        break

            # Step 2: if source_snippet didn't match, check normalised value
            if basis == "freeform_inferred" and value:
                val_lower = value.strip().lower()
                for cell in freeform_cells:
                    if val_lower in cell['text'].lower():
                        basis = "freeform_verbatim"
                        source_cell = {"row": cell["row"], "col": cell["col"]}
                        source_snippet = value.strip()
                        break

            # Cap source_snippet at 200 chars
            if source_snippet and len(source_snippet) > 200:
                source_snippet = source_snippet[:200] + "\u2026"

        results[key] = FieldResult(
            value=value,
            confidence_basis=basis,
            reason=reason,
            source_cell=source_cell,
            source_snippet=source_snippet,
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
