# Confidence, Provenance & Self-Contained Excel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the confidence system to Green/Orange/Red basis, embed raw cell data in the Excel export so previews and field-to-source links work on any machine, and add a coverage toggle that highlights unused source text.

**Architecture:** `FieldResult` gets a `confidence_basis` enum field; `PatientBlock` gets `unique_id`, `gender`, `mdt_date`, `coverage_map`, `coverage_pct`. The Excel export gains a `RawCells` hidden sheet storing full table cell data with coverage spans. On import, the app regenerates preview PNGs from `RawCells` and restores full provenance — no DOCX or LLM required.

**Tech Stack:** Python 3.11, Flask, openpyxl, Pillow, pytest, Bootstrap 5 / vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-23-confidence-provenance-excel-design.md`

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `models.py` | Add `confidence_basis` to `FieldResult`; `@property confidence`; new `PatientBlock` fields |
| Modify | `parser/docx_parser.py` | Extract `gender` and `mdt_date` into `PatientBlock` at parse time |
| Modify | `extractor/regex_extractor.py` | Set `confidence_basis` from source cell row; assign `unique_id` after Demographics |
| Modify | `extractor/response_parser.py` | Verbatim check (freeform cells only); set `freeform_verbatim` vs `freeform_inferred`; accept `raw_cells` param |
| **Create** | `extractor/coverage.py` | Span-union algorithm; `compute_coverage(patient)` |
| Modify | `extractor/preview_renderer.py` | Use `patient.unique_id` for file naming |
| Modify | `export/excel_writer.py` | RawCells sheet; `unique_id` column (col 1, shift fields to col+1); `confidence_basis` cell colours; cell comments for edited originals |
| Modify | `app.py` | `_import_excel()` (header-name reading, RawCells, preview regen, coverage restore); `edit_field()` (set `confidence_basis="edited"`); `patient_preview` route (use `unique_id`); `_run_extraction()` (call coverage + dedup unique_ids) |
| Modify | `templates/review.html` | Coverage toggle button; percentage badge; "No source" indicator |
| Modify | `static/js/app.js` | Toggle logic; SVG overlay for unused spans |
| Modify | `tests/test_models.py` | Tests for new fields |
| Modify | `tests/test_export.py` | Migrate `FieldResult(confidence=)` constructors; add RawCells assertions |
| Modify | `tests/test_response_parser.py` | Update to pass `raw_cells`; test verbatim check |
| Modify | `tests/test_regex_extractor.py` | Add `confidence_basis` assertions |
| Modify | `tests/test_preview_renderer.py` | Update for `unique_id` naming |
| **Create** | `tests/test_coverage.py` | Tests for span-union and coverage computation |

---

## Task 1: Update data models + migrate all FieldResult constructors

**Files:**
- Modify: `models.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_export.py`
- Modify: `extractor/response_parser.py` (constructor migration only, no new logic yet)
- Modify: `extractor/regex_extractor.py` (constructor migration only, no new logic yet)
- Modify: `app.py:195-203, 302` (constructor migration only)

> This task changes the `FieldResult` constructor signature. ALL callers must be migrated in this same task so the test suite stays green. New behavior (verbatim checks, confidence_basis logic) comes in later tasks.

- [ ] **Step 1: Write failing tests for new FieldResult fields**

Add to `tests/test_models.py`:
```python
def test_field_result_default_confidence_basis_is_absent():
    fr = FieldResult()
    assert fr.confidence_basis == "absent"

def test_field_result_confidence_property_maps_all_bases():
    assert FieldResult(confidence_basis="structured_verbatim").confidence == "high"
    assert FieldResult(confidence_basis="freeform_verbatim").confidence == "medium"
    assert FieldResult(confidence_basis="freeform_inferred").confidence == "low"
    assert FieldResult(confidence_basis="edited").confidence == "medium"
    assert FieldResult(confidence_basis="absent").confidence == "none"

def test_patient_block_has_unique_id_and_coverage_fields():
    p = PatientBlock(id="x")
    assert p.unique_id == ""
    assert p.gender == ""
    assert p.mdt_date == ""
    assert p.coverage_map == {}
    assert p.coverage_pct is None
```

- [ ] **Step 2: Run to confirm these tests fail**

```
cd C:\Users\Endryu\OneDrive\Documents\GitHub\Clinical-AI
python -m pytest tests/test_models.py -v
```
Expected: FAIL — `FieldResult has no attribute confidence_basis`

- [ ] **Step 3: Update `models.py`**

Replace the entire file:
```python
from dataclasses import dataclass, field
from typing import Optional, TypedDict


class CellRef(TypedDict):
    row: int
    col: int
    text: str


_CONFIDENCE_MAP = {
    "structured_verbatim": "high",
    "freeform_verbatim": "medium",
    "freeform_inferred": "low",
    "edited": "medium",
    "absent": "none",
}


@dataclass
class FieldResult:
    value: Optional[str] = None
    confidence_basis: str = "absent"       # structured_verbatim | freeform_verbatim | freeform_inferred | edited | absent
    reason: str = ""
    edited: bool = False
    original_value: Optional[str] = None
    source_cell: Optional[dict] = None    # {"row": int, "col": int}
    source_snippet: Optional[str] = None  # exact matched text (max 200 chars)

    @property
    def confidence(self) -> str:
        """Backward-compatible confidence string for analytics and API responses."""
        return _CONFIDENCE_MAP.get(self.confidence_basis, "none")


@dataclass
class PatientBlock:
    id: str                                         # Legacy MRN-based ID (routing compat)
    unique_id: str = ""                             # {DDMMYYYY}_{initials}_{gender}_{disambiguator}
    initials: str = ""
    nhs_number: str = ""
    gender: str = ""
    mdt_date: str = ""
    raw_text: str = ""
    extractions: dict = field(default_factory=dict)
    raw_cells: list[CellRef] = field(default_factory=list)
    coverage_map: dict = field(default_factory=dict)   # {"{row},{col}": [{"start","end","used"}]}
    coverage_pct: Optional[float] = None


@dataclass
class ExtractionSession:
    file_name: str = ""
    upload_time: str = ""
    patients: list = field(default_factory=list)
    status: str = "idle"
    stop_requested: bool = False
    concurrency: int = 1
    progress: dict = field(default_factory=lambda: {
        "current_patient": 0,
        "total": 0,
        "current_group": "",
        "patient_times": [],
        "current_patient_start": 0,
        "average_seconds": 0,
        "active_patients": {},
        "phase": "idle",
        "regex_complete": 0,
        "llm_queue_size": 0,
        "llm_complete": 0,
        "completed_patients": [],
    })
```

- [ ] **Step 4: Migrate FieldResult constructors — `extractor/response_parser.py`**

Line 48: change to:
```python
return {key: FieldResult(value=None, confidence_basis="absent") for key in expected_keys}
```

Line 88: change to (temporary — verbatim logic comes in Task 4):
```python
# Map old confidence string to temporary basis — refined in Task 4
_basis_tmp = {"high": "freeform_verbatim", "medium": "freeform_verbatim",
              "low": "freeform_inferred", "none": "absent"}.get(confidence, "freeform_inferred")
results[key] = FieldResult(
    value=value, confidence_basis=_basis_tmp, reason=reason, source_snippet=source_section
)
```

- [ ] **Step 5: Migrate FieldResult constructors — `extractor/regex_extractor.py`**

Line 42: change to:
```python
return {f['key']: FieldResult(value=None, confidence_basis='absent') for f in fields}
```

Lines 63–69: change `confidence='high'` to `confidence_basis='structured_verbatim'` (temporary — row-based logic comes in Task 3):
```python
results[key] = FieldResult(
    value=value,
    confidence_basis='structured_verbatim',
    reason='Extracted verbatim from document text',
    source_cell=source_cell,
    source_snippet=source_snippet,
)
```

Line 71: change to:
```python
results[key] = FieldResult(value=None, confidence_basis='absent', reason='')
```

- [ ] **Step 6: Migrate FieldResult constructors — `app.py`**

Line 195–201 (inside `_import_excel`): change `confidence=meta.get('confidence', 'high')` to:
```python
cb = meta.get('confidence_basis') or meta.get('confidence', 'structured_verbatim')
# Map legacy confidence string to basis if needed
if cb in ('high', 'medium', 'low', 'none'):
    cb = {'high': 'structured_verbatim', 'medium': 'freeform_verbatim',
          'low': 'freeform_inferred', 'none': 'absent'}[cb]
group_fields[field['key']] = FieldResult(
    value=value,
    confidence_basis=cb,
    reason=meta.get('reason', ''),
    source_cell=meta.get('source_cell'),
    source_snippet=meta.get('source_snippet')
)
```

Line 203: change to:
```python
group_fields[field['key']] = FieldResult(value=None, confidence_basis='absent')
```

Line 302: change to:
```python
results[key] = FieldResult(value=None, confidence_basis='absent')
```

- [ ] **Step 7: Migrate FieldResult constructors — `tests/test_export.py`**

Replace all `FieldResult(value=..., confidence="high", ...)` with `confidence_basis="structured_verbatim"`, all `confidence="medium"` with `confidence_basis="freeform_verbatim"`, all `confidence="low"` with `confidence_basis="freeform_inferred"`, all `confidence="none"` with `confidence_basis="absent"`.

Full updated test_export.py patient construction blocks:
```python
# In test_excel_exports_metadata_sheet and test_excel_round_trip_restores_confidence_and_reason:
"dob": FieldResult(value="26/05/1970", confidence_basis="structured_verbatim", reason="regex match"),
"initials": FieldResult(value="AO", confidence_basis="structured_verbatim", reason=""),
"mrn": FieldResult(value="9990001", confidence_basis="structured_verbatim", reason=""),
"nhs_number": FieldResult(value="9990000001", confidence_basis="freeform_verbatim", reason="LLM inferred"),
"gender": FieldResult(value="Male", confidence_basis="structured_verbatim", reason=""),
"previous_cancer": FieldResult(value=None, confidence_basis="absent", reason=""),
"previous_cancer_site": FieldResult(value=None, confidence_basis="absent", reason=""),

# In test_excel_round_trip:
"dob": FieldResult(value="26/05/1970", confidence_basis="structured_verbatim"),
"initials": FieldResult(value="AO", confidence_basis="structured_verbatim"),
"mrn": FieldResult(value="9990001", confidence_basis="structured_verbatim"),
"nhs_number": FieldResult(value="9990000001", confidence_basis="structured_verbatim"),
"gender": FieldResult(value="Male", confidence_basis="structured_verbatim"),
"previous_cancer": FieldResult(value="No", confidence_basis="freeform_verbatim"),
"previous_cancer_site": FieldResult(value="N/A", confidence_basis="freeform_inferred"),
```

Note: `test_excel_exports_metadata_sheet` also checks `assert nhs_row[2] == "medium"`. Since the Excel writer still reads `fr.confidence` (the property), this still returns "medium" — assertion stays unchanged until Task 7.

- [ ] **Step 8: Run full test suite — all tests must pass**

```
python -m pytest tests/ -v
```
Expected: All tests PASS. Fix any remaining `TypeError: __init__() got an unexpected keyword argument 'confidence'` before proceeding.

- [ ] **Step 9: Commit**

```bash
git add models.py extractor/response_parser.py extractor/regex_extractor.py app.py tests/test_models.py tests/test_export.py
git commit -m "feat: add confidence_basis to FieldResult; migrate all constructors"
```

---

## Task 2: Update DOCX parser — extract gender and mdt_date

**Files:**
- Modify: `parser/docx_parser.py`
- Modify: `tests/test_parser.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_parser.py`:
```python
from parser.docx_parser import _extract_gender

def test_extract_gender_from_demographics_cell():
    cell = "Hospital Number: 001\nNHS Number: 001\nAlice Test\nFemale (e) DOB: 01/01/1980"
    assert _extract_gender(cell) == "Female"

def test_extract_gender_male():
    cell = "Hospital Number: 001\nNHS Number: 001\nBob Jones\nMale (e) DOB: 05/03/1972"
    assert _extract_gender(cell) == "Male"

def test_extract_gender_missing_returns_empty():
    cell = "Hospital Number: 001\nNHS Number: 001\nBob Jones\nDOB: 05/03/1972"
    assert _extract_gender(cell) == ""
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_parser.py::test_extract_gender_from_demographics_cell -v
```
Expected: FAIL — `cannot import name '_extract_gender'`

- [ ] **Step 3: Add `_extract_gender` and update `parse_docx` in `parser/docx_parser.py`**

Add after the `_HOSPITAL_RE` definition (after line 38):
```python
_GENDER_RE = re.compile(r'\b(Male|Female)\b', re.IGNORECASE)
```

Add a new helper function (after `_extract_nhs`):
```python
def _extract_gender(details_text: str) -> str:
    """Return 'Male', 'Female', or '' if not found."""
    m = _GENDER_RE.search(details_text)
    return m.group(1).capitalize() if m else ""
```

In `parse_docx`, update the `PatientBlock` constructor call (line 219):
```python
patients.append(PatientBlock(
    id=patient_id,
    initials=_initials(name) if name else "",
    nhs_number=nhs,
    gender=_extract_gender(details_cell),
    mdt_date=mdt_date,
    raw_text=raw_text,
    raw_cells=raw_cells,
))
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_parser.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add parser/docx_parser.py tests/test_parser.py
git commit -m "feat: extract gender and mdt_date into PatientBlock at parse time"
```

---

## Task 3: Update regex extractor — confidence_basis from source cell row + unique_id

**Files:**
- Modify: `extractor/regex_extractor.py`
- Modify: `tests/test_regex_extractor.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_regex_extractor.py`:
```python
def test_regex_extract_structured_row_gives_structured_verbatim():
    """DOB is in row 1 (structured) — should be structured_verbatim."""
    results = regex_extract(DEMO_RAW_TEXT, "Demographics", DEMO_FIELDS, DEMO_CELLS)
    assert results['dob'].confidence_basis == "structured_verbatim"

def test_regex_extract_freeform_row_gives_freeform_verbatim():
    """A value found in row 5 (freeform) should be freeform_verbatim."""
    freeform_cells = DEMO_CELLS + [
        {"row": 5, "col": 0, "text": "Clinical details: T3 tumour at 5cm from anal verge"},
    ]
    fields = [{'key': 'dob', 'type': 'date'}]
    # Use raw text that will match in a freeform cell
    raw_text = "Clinical details: T3 tumour at 5cm from anal verge\nDOB: 12/05/1955"
    results = regex_extract(raw_text, "Demographics", fields, freeform_cells)
    # DOB is matched from row 1, not row 5 — so still structured_verbatim
    assert results['dob'].confidence_basis == "structured_verbatim"

def test_build_unique_id_with_mrn():
    from extractor.regex_extractor import build_unique_id
    assert build_unique_id(
        mdt_date="07/03/2025", initials="AO", gender="Male", mrn="9990001", nhs=""
    ) == "07032025_AO_M_9990001"

def test_build_unique_id_uses_nhs_last4_when_no_mrn():
    from extractor.regex_extractor import build_unique_id
    assert build_unique_id(
        mdt_date="07/03/2025", initials="BK", gender="Female", mrn="", nhs="9990001234"
    ) == "07032025_BK_F_1234"

def test_build_unique_id_fallback_row_index():
    from extractor.regex_extractor import build_unique_id
    assert build_unique_id(
        mdt_date="", initials="CJ", gender="", mrn="", nhs="", row_index=3
    ) == "00000000_CJ_U_003"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_regex_extractor.py -v -k "structured_verbatim or unique_id"
```
Expected: FAIL

- [ ] **Step 3: Update `extractor/regex_extractor.py`**

Add at the top (after imports):
```python
# Freeform rows: clinical details (4,5) and MDT outcome (6,7)
_FREEFORM_ROWS = {4, 5, 6, 7}
```

Update `build_unique_id` as a new public function (add before `regex_extract`):
```python
def build_unique_id(mdt_date: str, initials: str, gender: str,
                    mrn: str, nhs: str, row_index: int = 0) -> str:
    """Construct unique patient ID: {DDMMYYYY}_{initials}_{G}_{disambiguator}."""
    date_clean = re.sub(r'[/\-\. ]', '', mdt_date) if mdt_date else "00000000"
    inits = initials or "XX"
    g = "U"
    if gender:
        gl = gender.lower()
        if gl in ("male", "m"):
            g = "M"
        elif gl in ("female", "f"):
            g = "F"
    if mrn:
        disambig = mrn
    elif nhs and len(nhs) >= 4:
        disambig = nhs[-4:]
    else:
        disambig = f"{row_index:03d}"
    return f"{date_clean}_{inits}_{g}_{disambig}"
```

Update the per-field logic inside `regex_extract` (replace lines 54–69):
```python
if raw_span:
    for cell in raw_cells:
        if raw_span in cell["text"]:
            source_cell = {"row": cell["row"], "col": cell["col"]}
            source_snippet = raw_span[:200]  # cap at 200 chars
            break

# Determine confidence_basis from which row the source is in
if source_cell:
    basis = "freeform_verbatim" if source_cell["row"] in _FREEFORM_ROWS else "structured_verbatim"
else:
    basis = "structured_verbatim"  # regex match without traceable cell → assume structured

results[key] = FieldResult(
    value=value,
    confidence_basis=basis,
    reason='Extracted verbatim from document text',
    source_cell=source_cell,
    source_snippet=source_snippet,
)
```

Add a public function at the bottom of `regex_extractor.py` to assign `unique_id` to a patient after Demographics extraction:
```python
def assign_unique_id(patient, demographics_results: dict, row_index: int = 0) -> None:
    """Set patient.unique_id using Demographics extraction results."""
    gender_fr = demographics_results.get("gender")
    mrn_fr = demographics_results.get("mrn")
    nhs_fr = demographics_results.get("nhs_number")
    patient.unique_id = build_unique_id(
        mdt_date=patient.mdt_date,
        initials=patient.initials,
        gender=gender_fr.value if gender_fr and gender_fr.value else "",
        mrn=mrn_fr.value if mrn_fr and mrn_fr.value else "",
        nhs=nhs_fr.value if nhs_fr and nhs_fr.value else "",
        row_index=row_index,
    )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_regex_extractor.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/regex_extractor.py tests/test_regex_extractor.py
git commit -m "feat: set confidence_basis from source cell row; add build_unique_id and assign_unique_id"
```

---

## Task 4: Update response parser — verbatim check + proper confidence_basis

**Files:**
- Modify: `extractor/response_parser.py`
- Modify: `tests/test_response_parser.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_response_parser.py`:
```python
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
    """source_snippet '(h)' is not in freeform text — should still be freeform_inferred
    unless the actual value text is found."""
    group = _make_group(['mmr_status'])
    raw = json.dumps({
        'mmr_status': {'value': 'Proficient', 'confidence': 'medium',
                       'reason': 'stated', 'source_section': '(g)'}
    })
    # '(g)' not in freeform cells text, 'Proficient' not in freeform cells text
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
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_response_parser.py -v -k "verbatim or inferred or absent_basis"
```
Expected: FAIL

- [ ] **Step 3: Rewrite `parse_llm_response` in `extractor/response_parser.py`**

Update function signature and implementation:
```python
def parse_llm_response(raw_response: str, group: dict,
                       raw_cells: list | None = None) -> dict[str, FieldResult]:
    expected_keys = [f['key'] for f in group['fields']]
    field_types = {f['key']: f['type'] for f in group['fields']}
    raw_cells = raw_cells or []
    # Freeform cells only (rows 4-7) for verbatim check
    freeform_cells = [c for c in raw_cells if c.get('row', 0) in {4, 5, 6, 7}]

    data = _extract_json(raw_response)
    if data is None:
        return {key: FieldResult(value=None, confidence_basis="absent") for key in expected_keys}

    results = {}
    for key in expected_keys:
        if key in data and isinstance(data[key], dict):
            value = data[key].get('value')
            reason = data[key].get('reason', '')
            source_section = data[key].get('source_section')
        else:
            value = None
            reason = ''
            source_section = None

        if value is not None:
            value = str(value).strip()
            if value.lower() in ('null', 'none', 'n/a', 'missing', ''):
                value = None

        # Normalise date fields
        if value is not None and field_types.get(key) == 'date':
            if not re.match(r'\d{1,2}/\d{1,2}/\d{4}', value):
                reason = f"[date format unclear] {reason}"

        # Check for misspellings in text values
        if value is not None and field_types.get(key) == 'text':
            typos = _check_spelling(value)
            if typos:
                reason = f"[Possible misspelling: {', '.join(typos[:3])}] {reason}"

        # Determine confidence_basis via verbatim check
        source_cell = None
        source_snippet = source_section  # start with LLM-provided annotation marker

        if value is None:
            confidence_basis = "absent"
            reason = "Field not mentioned in the document"
        else:
            # Verbatim check: use source_snippet first, fall back to normalised value
            check_text = (source_snippet or value).lower().strip()
            found_cell = None
            for cell in freeform_cells:
                if check_text and check_text in cell['text'].lower():
                    found_cell = cell
                    break
            # If source_snippet didn't match, try the actual value
            if found_cell is None and source_snippet:
                val_lower = value.lower().strip()
                for cell in freeform_cells:
                    if val_lower and val_lower in cell['text'].lower():
                        found_cell = cell
                        break

            if found_cell is not None:
                confidence_basis = "freeform_verbatim"
                source_cell = {"row": found_cell['row'], "col": found_cell['col']}
                source_snippet = value[:200]  # use actual value as snippet (not annotation marker)
            else:
                confidence_basis = "freeform_inferred"
                source_cell = None

        results[key] = FieldResult(
            value=value,
            confidence_basis=confidence_basis,
            reason=reason,
            source_snippet=source_snippet,
            source_cell=source_cell,
        )

    return results
```

Also remove `_apply_confidence_overrides` (no longer needed — verbatim check replaces it). Keep `_check_spelling` and `_extract_json` unchanged.

- [ ] **Step 4: Update callers of `parse_llm_response` in `app.py` to pass `raw_cells`**

Find all calls to `parse_llm_response(raw_response, group)` in `app.py` and add `raw_cells=patient.raw_cells`:
```python
llm_results = parse_llm_response(raw_response, group, raw_cells=patient.raw_cells)
```
There are two call sites: `_run_extraction` (around line 308) and `_do_re_extract` (around line 557).

- [ ] **Step 5: Update and retire obsolete tests in `tests/test_response_parser.py`**

Remove `test_llm_high_confidence_capped_to_medium`, `test_llm_low_confidence_kept`, `test_llm_medium_confidence_unchanged` — these tested behaviour (confidence capping) that no longer exists. Replace with:

```python
def test_llm_value_not_in_text_gives_freeform_inferred():
    """With no raw_cells, any LLM value cannot be verified → freeform_inferred."""
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({
        'endoscopy_findings': {'value': 'Mass at 13cm', 'confidence': 'high', 'reason': 'verbatim'}
    })
    results = parse_llm_response(raw, group, raw_cells=[])
    assert results['endoscopy_findings'].confidence_basis == "freeform_inferred"
    assert results['endoscopy_findings'].confidence == "low"

def test_llm_value_in_freeform_cell_gives_freeform_verbatim():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({
        'endoscopy_findings': {'value': 'Mass at 13cm', 'confidence': 'high', 'reason': 'verbatim'}
    })
    cells = [{"row": 5, "col": 0, "text": "Mass at 13cm from anal verge"}]
    results = parse_llm_response(raw, group, raw_cells=cells)
    assert results['endoscopy_findings'].confidence_basis == "freeform_verbatim"
    assert results['endoscopy_findings'].confidence == "medium"
```

Update `test_null_value_gets_none_confidence` to check `confidence_basis`:
```python
def test_null_value_gets_absent_basis():
    group = _make_group(['endoscopy_findings'])
    raw = json.dumps({'endoscopy_findings': {'value': None, 'confidence': 'high', 'reason': ''}})
    results = parse_llm_response(raw, group)
    assert results['endoscopy_findings'].confidence_basis == "absent"
    assert results['endoscopy_findings'].confidence == "none"
    assert results['endoscopy_findings'].value is None
```

`test_source_section_stored_in_source_snippet` stays unchanged — when no freeform match is found, `source_snippet` retains the annotation marker `'(g)'`.

- [ ] **Step 6: Run tests**

```
python -m pytest tests/test_response_parser.py tests/test_regex_extractor.py -v
```
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add extractor/response_parser.py app.py tests/test_response_parser.py
git commit -m "feat: verbatim check in response_parser sets freeform_verbatim vs freeform_inferred"
```

---

## Task 5: Build coverage module

**Files:**
- Create: `extractor/coverage.py`
- Create: `tests/test_coverage.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_coverage.py`:
```python
from models import PatientBlock, FieldResult
from extractor.coverage import compute_coverage, _merge_spans


def test_merge_spans_combines_overlapping():
    spans = [
        {"start": 0, "end": 10, "used": True},
        {"start": 8, "end": 20, "used": True},
        {"start": 25, "end": 35, "used": False},
    ]
    merged = _merge_spans(spans)
    # Two overlapping True spans merge → {0,20,T}; gap {20,25} filled as unused; then {25,35,F}
    assert len(merged) == 3
    assert merged[0] == {"start": 0, "end": 20, "used": True}
    assert merged[1] == {"start": 20, "end": 25, "used": False}  # gap filled
    assert merged[2] == {"start": 25, "end": 35, "used": False}


def test_merge_spans_keeps_non_overlapping_separate():
    spans = [
        {"start": 0, "end": 10, "used": False},
        {"start": 10, "end": 30, "used": True},
        {"start": 30, "end": 50, "used": False},
    ]
    merged = _merge_spans(spans)
    assert len(merged) == 3


def test_compute_coverage_marks_used_spans():
    patient = PatientBlock(
        id="p001",
        raw_cells=[
            {"row": 5, "col": 0, "text": "Patient has T3 tumour and EMVI positive"},
            {"row": 7, "col": 0, "text": "Outcome: CAPOX chemotherapy"},
        ],
        extractions={
            "Baseline MRI": {
                "emvi": FieldResult(
                    value="Positive",
                    confidence_basis="freeform_verbatim",
                    source_cell={"row": 5, "col": 0},
                    source_snippet="EMVI positive",
                )
            }
        }
    )
    compute_coverage(patient)
    assert patient.coverage_map is not None
    key = "5,0"
    assert key in patient.coverage_map
    used_spans = [s for s in patient.coverage_map[key] if s["used"]]
    assert len(used_spans) > 0


def test_compute_coverage_pct_excludes_structured_rows():
    """Only freeform rows (4-7) count toward coverage_pct."""
    patient = PatientBlock(
        id="p001",
        raw_cells=[
            {"row": 1, "col": 0, "text": "Hospital Number: 001"},  # structured
            {"row": 5, "col": 0, "text": "20 chars of text here"},  # freeform, 21 chars
        ],
        extractions={}
    )
    compute_coverage(patient)
    assert patient.coverage_pct == 0.0  # nothing used, but denominator is freeform only


def test_compute_coverage_pct_none_when_no_freeform_text():
    patient = PatientBlock(
        id="p001",
        raw_cells=[{"row": 1, "col": 0, "text": "demographics only"}],
        extractions={}
    )
    compute_coverage(patient)
    assert patient.coverage_pct is None
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_coverage.py -v
```
Expected: FAIL — `No module named 'extractor.coverage'`

- [ ] **Step 3: Create `extractor/coverage.py`**

```python
"""
Coverage computation: tracks which parts of freeform source text were
claimed by extracted fields. Produces a coverage_map (char spans per cell)
and a coverage_pct (percentage of freeform text covered).
"""
from models import PatientBlock

_FREEFORM_ROWS = {4, 5, 6, 7}


def compute_coverage(patient: PatientBlock) -> None:
    """Compute and set patient.coverage_map and patient.coverage_pct in-place."""
    coverage_map: dict = {}

    # Initialise every cell with a single unused span covering full text length
    for cell in patient.raw_cells:
        key = f"{cell['row']},{cell['col']}"
        text = cell.get('text', '') or ''
        if text:
            coverage_map[key] = [{"start": 0, "end": len(text), "used": False}]
        else:
            coverage_map[key] = []

    # Mark used spans for each field that has a source_snippet + source_cell
    for group_fields in patient.extractions.values():
        for fr in group_fields.values():
            if not (fr.source_snippet and fr.source_cell):
                continue
            cell_key = f"{fr.source_cell['row']},{fr.source_cell['col']}"
            if cell_key not in coverage_map:
                continue
            # Find the raw cell text
            raw_cell = next(
                (c for c in patient.raw_cells
                 if c['row'] == fr.source_cell['row'] and c['col'] == fr.source_cell['col']),
                None
            )
            if not raw_cell:
                continue
            text = raw_cell.get('text', '').lower()
            snippet = fr.source_snippet.lower()
            idx = text.find(snippet)
            if idx >= 0:
                _mark_used(coverage_map[cell_key], idx, idx + len(snippet))

    # Merge overlapping spans in each cell
    for key in coverage_map:
        coverage_map[key] = _merge_spans(coverage_map[key])

    patient.coverage_map = coverage_map

    # Compute coverage percentage — freeform cells only (derive keys from actual raw_cells)
    total_chars = 0
    used_chars = 0
    freeform_keys = {
        f"{c['row']},{c['col']}"
        for c in patient.raw_cells
        if c['row'] in _FREEFORM_ROWS
    }
    for key, spans in coverage_map.items():
        if key not in freeform_keys:
            continue
        for span in spans:
            length = span['end'] - span['start']
            total_chars += length
            if span['used']:
                used_chars += length

    patient.coverage_pct = round(used_chars / total_chars * 100, 1) if total_chars > 0 else None


def _mark_used(spans: list, start: int, end: int) -> None:
    """Split existing spans to mark the range [start, end) as used."""
    new_spans = []
    for span in spans:
        s, e, u = span['start'], span['end'], span['used']
        if end <= s or start >= e:
            # No overlap
            new_spans.append(span)
        else:
            # Split
            if s < start:
                new_spans.append({"start": s, "end": start, "used": u})
            new_spans.append({"start": max(s, start), "end": min(e, end), "used": True})
            if e > end:
                new_spans.append({"start": end, "end": e, "used": u})
    spans.clear()
    spans.extend(new_spans)


def _merge_spans(spans: list) -> list:
    """Merge adjacent spans of the same 'used' value; fill gaps as unused."""
    if not spans:
        return []
    spans = sorted(spans, key=lambda s: s['start'])
    # Fill any gap at the start (shouldn't happen normally)
    result = []
    for span in spans:
        if result and result[-1]['used'] == span['used'] and result[-1]['end'] >= span['start']:
            # Extend
            result[-1]['end'] = max(result[-1]['end'], span['end'])
        elif result and result[-1]['end'] < span['start']:
            # Gap — fill as unused
            result.append({"start": result[-1]['end'], "end": span['start'], "used": False})
            result.append(span)
        else:
            result.append(dict(span))
    return result
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_coverage.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/coverage.py tests/test_coverage.py
git commit -m "feat: add coverage module with span-union algorithm"
```

---

## Task 6: Update preview renderer — use `unique_id` for file naming

**Files:**
- Modify: `extractor/preview_renderer.py:135-139`
- Modify: `tests/test_preview_renderer.py`

- [ ] **Step 1: Write failing test**

Read `tests/test_preview_renderer.py` first to understand existing structure. Then add:
```python
def test_preview_uses_unique_id_for_filename(tmp_path):
    patient = PatientBlock(id="9990001", unique_id="07032025_AO_M_9990001")
    patient.raw_cells = [
        {"row": 0, "col": 0, "text": "Patient Details"},
        {"row": 0, "col": 1, "text": ""},
        {"row": 0, "col": 2, "text": ""},
        {"row": 1, "col": 0, "text": "Hospital Number: 001"},
        {"row": 1, "col": 1, "text": ""},
        {"row": 1, "col": 2, "text": ""},
    ]
    render_patient_preview(patient, str(tmp_path))
    assert (tmp_path / "07032025_AO_M_9990001.png").exists()
    assert (tmp_path / "07032025_AO_M_9990001.json").exists()
    assert not (tmp_path / "9990001.png").exists()
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_preview_renderer.py::test_preview_uses_unique_id_for_filename -v
```
Expected: FAIL (file named `9990001.png`, not `07032025_AO_M_9990001.png`)

- [ ] **Step 3: Update `extractor/preview_renderer.py` lines 135–139**

Replace:
```python
png_path = os.path.join(out_dir, f'{patient.id}.png')
json_path = os.path.join(out_dir, f'{patient.id}.json')
```
With:
```python
file_id = patient.unique_id if patient.unique_id else patient.id
png_path = os.path.join(out_dir, f'{file_id}.png')
json_path = os.path.join(out_dir, f'{file_id}.json')
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_preview_renderer.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/preview_renderer.py tests/test_preview_renderer.py
git commit -m "feat: preview renderer uses unique_id for file naming"
```

---

## Task 7: Update Excel writer — RawCells sheet, unique_id column, confidence_basis styling

**Files:**
- Modify: `export/excel_writer.py`
- Modify: `tests/test_export.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_export.py`:
```python
def _make_patient_with_rawcells():
    return PatientBlock(
        id="9990001",
        unique_id="07032025_AO_M_9990001",
        initials="AO",
        nhs_number="9990000001",
        gender="Male",
        mdt_date="07/03/2025",
        raw_cells=[
            {"row": 0, "col": 0, "text": "Patient Details"},
            {"row": 1, "col": 0, "text": "Hospital Number: 9990001"},
            {"row": 5, "col": 0, "text": "T3 tumour at 5cm. EMVI positive."},
        ],
        coverage_map={
            "5,0": [{"start": 0, "end": 15, "used": True},
                    {"start": 15, "end": 33, "used": False}]
        },
        coverage_pct=45.5,
        extractions={
            "Demographics": {
                "mrn": FieldResult(value="9990001", confidence_basis="structured_verbatim"),
                "initials": FieldResult(value="AO", confidence_basis="structured_verbatim"),
                "dob": FieldResult(value="01/01/1970", confidence_basis="structured_verbatim"),
                "nhs_number": FieldResult(value="9990000001", confidence_basis="freeform_verbatim"),
                "gender": FieldResult(value="Male", confidence_basis="structured_verbatim"),
                "previous_cancer": FieldResult(value=None, confidence_basis="absent"),
                "previous_cancer_site": FieldResult(value=None, confidence_basis="absent"),
            }
        }
    )


def test_excel_has_rawcells_sheet():
    patient = _make_patient_with_rawcells()
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        path = f.name
    try:
        write_excel([patient], path)
        wb = load_workbook(path)
        assert "RawCells" in wb.sheetnames
        ws_rc = wb["RawCells"]
        headers = [ws_rc.cell(1, c).value for c in range(1, 6)]
        assert headers == ["unique_id", "row", "col", "text", "coverage_json"]
        wb.close()
    finally:
        os.unlink(path)


def test_excel_rawcells_contains_patient_data():
    patient = _make_patient_with_rawcells()
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        path = f.name
    try:
        write_excel([patient], path)
        wb = load_workbook(path)
        ws_rc = wb["RawCells"]
        rows = list(ws_rc.iter_rows(min_row=2, values_only=True))
        # Row 5,0 should be present
        cell_row = next((r for r in rows if r[1] == 5 and r[2] == 0), None)
        assert cell_row is not None
        assert "T3 tumour" in (cell_row[3] or "")
        # coverage_json should be a valid JSON string
        import json
        spans = json.loads(cell_row[4])
        assert isinstance(spans, list)
        wb.close()
    finally:
        os.unlink(path)


def test_excel_unique_id_is_first_column():
    patient = _make_patient_with_rawcells()
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        path = f.name
    try:
        write_excel([patient], path)
        wb = load_workbook(path)
        ws = wb.active
        assert ws.cell(1, 1).value == "unique_id"
        assert ws.cell(2, 1).value == "07032025_AO_M_9990001"
        wb.close()
    finally:
        os.unlink(path)


def test_excel_metadata_sheet_has_confidence_basis_column():
    patient = _make_patient_with_rawcells()
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        path = f.name
    try:
        write_excel([patient], path)
        wb = load_workbook(path)
        ws_meta = wb["Metadata"]
        headers = [ws_meta.cell(2, c).value for c in range(1, 11)]
        assert "confidence_basis" in headers
        assert "unique_id" in headers
        # Find nhs_number row and check confidence_basis
        rows = list(ws_meta.iter_rows(min_row=3, values_only=True))
        col_idx = headers.index("confidence_basis")
        key_idx = headers.index("field_key")
        nhs_row = next((r for r in rows if r[key_idx] == "nhs_number"), None)
        assert nhs_row is not None
        assert nhs_row[col_idx] == "freeform_verbatim"
        wb.close()
    finally:
        os.unlink(path)
```

Also update the existing `test_excel_exports_metadata_sheet`:
- Remove `assert ws.cell(1, 1).value == "patient_id"` (structure changes)
- Update `assert nhs_row[2] == "medium"` → check by column name instead

- [ ] **Step 2: Run to confirm new tests fail**

```
python -m pytest tests/test_export.py::test_excel_has_rawcells_sheet -v
```
Expected: FAIL

- [ ] **Step 3: Rewrite `export/excel_writer.py`**

Full replacement:
```python
import json
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.comments import Comment
from config import get_all_fields, get_groups


# Confidence basis → (fill hex, font italic, font colour)
_BASIS_STYLES = {
    "structured_verbatim": ("C6EFCE", False, None),      # green
    "freeform_verbatim":   ("FFEB9C", True,  "9C6500"),  # orange + italic
    "freeform_inferred":   ("FFC7CE", False, "9C0006"),  # red
    "edited":              ("D9D9D9", False, None),       # grey
    "absent":              (None,     False, None),       # no fill
}


def _get_group_colors() -> dict:
    colors = {}
    for group in get_groups():
        hex_color = group.get('color', '#D9D9D9').lstrip('#')
        for field in group['fields']:
            colors[field['key']] = hex_color
    return colors


def write_excel(patients: list, output_path: str, source_name: str = ""):
    wb = Workbook()
    ws = wb.active
    ws.title = "Prototype V1"

    all_fields = get_all_fields()
    group_colors = _get_group_colors()
    OFFSET = 1  # unique_id occupies column 1; all schema fields shift right by 1

    # Column 1: unique_id header
    uid_header = ws.cell(row=1, column=1, value="unique_id")
    uid_header.font = Font(bold=True, size=9)

    # Field headers (shifted by OFFSET)
    header_font = Font(bold=True, size=9)
    for field in all_fields:
        col = field['excel_column'] + OFFSET
        cell = ws.cell(row=1, column=col, value=field['excel_header'])
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True, vertical='top')
        hex_color = group_colors.get(field['key'], 'D9D9D9')
        cell.fill = PatternFill(start_color=hex_color, end_color=hex_color, fill_type='solid')

    # Patient data rows
    for row_idx, patient in enumerate(patients, start=2):
        ws.cell(row=row_idx, column=1, value=patient.unique_id or patient.id)

        for group_name, fields in patient.extractions.items():
            for field_key, fr in fields.items():
                col = _get_column(all_fields, field_key)
                if col is None:
                    continue
                col += OFFSET
                if fr.value is not None:
                    cell = ws.cell(row=row_idx, column=col, value=fr.value)
                    field_def = _get_field_def(all_fields, field_key)
                    if field_def and field_def['type'] == 'date':
                        cell.number_format = 'DD/MM/YYYY'

                    fill_hex, italic, font_color = _BASIS_STYLES.get(
                        fr.confidence_basis, (None, False, None)
                    )
                    if fill_hex:
                        cell.fill = PatternFill(
                            start_color=fill_hex, end_color=fill_hex, fill_type='solid'
                        )
                    if italic or font_color:
                        cell.font = Font(
                            italic=italic,
                            color=font_color or "000000"
                        )
                    # Cell comment for edited originals
                    if fr.edited and fr.original_value is not None:
                        cell.comment = Comment(
                            f"Original: {fr.original_value}", "MDT Extractor"
                        )

    # Legend
    legend_row = ws.max_row + 2
    ws.cell(row=legend_row, column=1, value="Legend:").font = Font(bold=True)
    for i, (basis, label) in enumerate([
        ("structured_verbatim", "Green — extracted from structured field (high confidence)"),
        ("freeform_verbatim",   "Orange — found verbatim in freeform text (medium confidence)"),
        ("freeform_inferred",   "Red — inferred by LLM, not verbatim (low confidence)"),
        ("edited",              "Grey — manually edited by clinician"),
    ], start=1):
        fill_hex, italic, font_color = _BASIS_STYLES[basis]
        c = ws.cell(row=legend_row + i, column=1, value=label)
        if fill_hex:
            c.fill = PatternFill(start_color=fill_hex, end_color=fill_hex, fill_type='solid')
        if italic or font_color:
            c.font = Font(italic=italic, color=font_color or "000000")

    # Auto-width (cap at 30)
    for col_idx in range(1, len(all_fields) + OFFSET + 1):
        max_len = 0
        for row in ws.iter_rows(
            min_col=col_idx, max_col=col_idx, min_row=1, max_row=min(ws.max_row, 5)
        ):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[
            ws.cell(row=1, column=col_idx).column_letter
        ].width = min(max_len + 2, 30)

    # ── Metadata sheet ────────────────────────────────────────────────────────
    ws_meta = wb.create_sheet("Metadata")
    ws_meta.sheet_state = 'hidden'
    ws_meta.append(["SOURCE_FILE", source_name])
    META_HEADERS = [
        "unique_id", "field_key", "confidence_basis", "reason",
        "source_cell_row", "source_cell_col", "source_snippet",
        "edited", "original_value", "coverage_pct"
    ]
    ws_meta.append(META_HEADERS)

    for patient in patients:
        pid = patient.unique_id or patient.id
        for group_name, fields in patient.extractions.items():
            for field_key, fr in fields.items():
                sc_row = fr.source_cell['row'] if fr.source_cell else None
                sc_col = fr.source_cell['col'] if fr.source_cell else None
                snippet = (fr.source_snippet or '')[:200]
                ws_meta.append([
                    pid,
                    field_key,
                    fr.confidence_basis,
                    fr.reason or '',
                    sc_row,
                    sc_col,
                    snippet,
                    str(fr.edited).lower(),
                    fr.original_value or '',
                    patient.coverage_pct,
                ])

    # ── RawCells sheet ────────────────────────────────────────────────────────
    ws_rc = wb.create_sheet("RawCells")
    ws_rc.sheet_state = 'hidden'
    ws_rc.append(["unique_id", "row", "col", "text", "coverage_json"])

    for patient in patients:
        pid = patient.unique_id or patient.id
        for cell in patient.raw_cells:
            r, c_idx = cell['row'], cell['col']
            cell_key = f"{r},{c_idx}"
            spans = patient.coverage_map.get(cell_key, [])
            ws_rc.append([
                pid,
                r,
                c_idx,
                cell.get('text', ''),
                json.dumps(spans),
            ])

    wb.save(output_path)


def _get_column(all_fields: list, key: str) -> int | None:
    for f in all_fields:
        if f['key'] == key:
            return f['excel_column']
    return None


def _get_field_def(all_fields: list, key: str) -> dict | None:
    for f in all_fields:
        if f['key'] == key:
            return f
    return None
```

- [ ] **Step 4: Update `tests/test_export.py` for column offset and metadata sheet format**

In `test_excel_round_trip`, update the two hardcoded column assertions:
```python
# initials: schema col 2 + OFFSET 1 = Excel column 3
assert ws.cell(row=2, column=3).value == "AO"
# gender: schema col 5 + OFFSET 1 = Excel column 6
assert ws.cell(row=2, column=6).value == "Male"
```

In `test_excel_exports_metadata_sheet`, the test currently asserts `ws.cell(1, 1).value == "patient_id"`. This was always wrong — row 1 of the Metadata sheet is `"SOURCE_FILE"` and headers are on row 2. After our change, headers include `"unique_id"` not `"patient_id"`. Replace the assertion:
```python
# Remove: assert ws.cell(1, 1).value == "patient_id"
# Add: check that row 2 has the expected header names
ws = wb["Metadata"]
header_row = [ws.cell(2, c).value for c in range(1, 12)]
assert "unique_id" in header_row
assert "confidence_basis" in header_row
assert "field_key" in header_row
# Find nhs_number by column name (robust to column reordering)
fkey_idx = header_row.index("field_key")
cbasis_idx = header_row.index("confidence_basis")
rows = list(ws.iter_rows(min_row=3, values_only=True))
nhs_row = next((r for r in rows if r[fkey_idx] == "nhs_number"), None)
assert nhs_row is not None
assert nhs_row[cbasis_idx] == "freeform_verbatim"
assert "LLM inferred" in (nhs_row[header_row.index("reason")] or "")
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/test_export.py -v
```
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add export/excel_writer.py tests/test_export.py
git commit -m "feat: Excel writer adds RawCells sheet, unique_id column, confidence_basis cell colours"
```

---

## Task 8: Update Excel import — header-name reading, RawCells, preview regeneration

**Files:**
- Modify: `app.py:126-233` (`_import_excel` function)

- [ ] **Step 1: Write a test for the new import**

Add to `tests/test_export.py`:
```python
def test_excel_round_trip_new_format_restores_rawcells_and_confidence_basis(tmp_path):
    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from app import _import_excel
    patient = _make_patient_with_rawcells()
    path = str(tmp_path / "test.xlsx")
    write_excel([patient], path)
    reimported = _import_excel(path)
    assert len(reimported) == 1
    p = reimported[0]
    # unique_id restored
    assert p.unique_id == "07032025_AO_M_9990001"
    # raw_cells restored
    assert len(p.raw_cells) == 3
    # confidence_basis restored
    demo = p.extractions.get("Demographics", {})
    assert demo["nhs_number"].confidence_basis == "freeform_verbatim"
    assert demo["mrn"].confidence_basis == "structured_verbatim"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_export.py::test_excel_round_trip_new_format_restores_rawcells_and_confidence_basis -v
```
Expected: FAIL

- [ ] **Step 3: Rewrite `_import_excel` in `app.py`**

Replace the function `_import_excel` (lines 126–233):
```python
def _import_excel(file_path: str) -> list:
    """Import a previously exported Excel file back into PatientBlock objects.
    Supports both new format (with RawCells sheet + confidence_basis column)
    and legacy format (with old confidence column only).
    """
    import os, time
    from openpyxl import load_workbook

    all_fields = get_all_fields()
    groups = get_groups()

    wb = load_workbook(file_path)

    # ── Detect format ────────────────────────────────────────────────────────
    has_rawcells = "RawCells" in wb.sheetnames
    is_new_format = False

    # ── Read Metadata sheet ──────────────────────────────────────────────────
    meta_lookup = {}   # (unique_id_or_pid, field_key) -> dict
    coverage_lookup = {}  # unique_id -> float (coverage_pct)

    if "Metadata" in wb.sheetnames:
        ws_meta = wb["Metadata"]
        # Row 1 = SOURCE_FILE
        if ws_meta.cell(row=1, column=1).value == "SOURCE_FILE":
            session.file_name = ws_meta.cell(row=1, column=2).value or ""
        # Row 2 = headers — read by name
        header_row = [ws_meta.cell(row=2, column=c).value for c in range(1, ws_meta.max_column + 1)]
        header_row = [h for h in header_row if h]

        def _col(name):
            """Return 0-based column index by header name, or None if not found.
            NOTE: always compare result with `is not None` — index 0 is valid and falsy."""
            try:
                return header_row.index(name)
            except ValueError:
                return None

        def _col_first(*names):
            """Return first found column index from candidates, or default."""
            for n in names:
                c = _col(n)
                if c is not None:
                    return c
            return None

        is_new_format = 'confidence_basis' in header_row

        pid_col    = _col_first('unique_id', 'patient_id') or 0
        fkey_col   = _col_first('field_key') if _col_first('field_key') is not None else 1
        cbasis_col = _col('confidence_basis')
        conf_col   = _col('confidence')
        reason_col = _col('reason')
        scrow_col  = _col('source_cell_row')
        sccol_col  = _col('source_cell_col')
        snip_col   = _col('source_snippet')
        edited_col = _col('edited')
        orig_col   = _col('original_value')
        cpct_col   = _col('coverage_pct')

        _LEGACY_MAP = {'high': 'structured_verbatim', 'medium': 'freeform_verbatim',
                       'low': 'freeform_inferred', 'none': 'absent'}

        for row in ws_meta.iter_rows(min_row=3, values_only=True):
            row = list(row)
            pid = str(row[pid_col]) if pid_col is not None and row[pid_col] else None
            fkey = str(row[fkey_col]) if fkey_col is not None and row[fkey_col] else None
            if not pid or not fkey:
                continue

            if is_new_format and cbasis_col is not None:
                cb = row[cbasis_col] or 'absent'
            elif conf_col is not None:
                cb = _LEGACY_MAP.get(str(row[conf_col] or ''), 'absent')
            else:
                cb = 'structured_verbatim'

            source_cell = None
            if scrow_col is not None and sccol_col is not None:
                sc_r, sc_c = row[scrow_col], row[sccol_col]
                if sc_r is not None and sc_c is not None:
                    source_cell = {"row": int(sc_r), "col": int(sc_c)}

            meta_lookup[(pid, fkey)] = {
                "confidence_basis": cb,
                "reason": str(row[reason_col]) if reason_col is not None and row[reason_col] else '',
                "source_cell": source_cell,
                "source_snippet": str(row[snip_col]) if snip_col is not None and row[snip_col] else None,
                "edited": str(row[edited_col]).lower() == 'true' if edited_col is not None else False,
                "original_value": str(row[orig_col]) if orig_col is not None and row[orig_col] else None,
            }
            if cpct_col is not None and row[cpct_col] is not None and pid not in coverage_lookup:
                try:
                    coverage_lookup[pid] = float(row[cpct_col])
                except (ValueError, TypeError):
                    pass

    # ── Read RawCells sheet ──────────────────────────────────────────────────
    rawcells_lookup = {}  # unique_id -> list of {"row","col","text"}
    coverage_map_lookup = {}  # unique_id -> {cell_key: [spans]}

    if has_rawcells:
        ws_rc = wb["RawCells"]
        rc_headers = [ws_rc.cell(row=1, column=c).value for c in range(1, 6)]
        def _rccol(name):
            try: return rc_headers.index(name)
            except ValueError: return None
        uid_c = _rccol('unique_id') or 0
        row_c = _rccol('row') or 1
        col_c = _rccol('col') or 2
        txt_c = _rccol('text') or 3
        cjson_c = _rccol('coverage_json') or 4

        for row in ws_rc.iter_rows(min_row=2, values_only=True):
            row = list(row)
            pid = str(row[uid_c]) if row[uid_c] else None
            if not pid:
                continue
            rawcells_lookup.setdefault(pid, []).append({
                "row": int(row[row_c] or 0),
                "col": int(row[col_c] or 0),
                "text": str(row[txt_c] or ''),
            })
            if row[cjson_c]:
                try:
                    spans = json.loads(row[cjson_c])
                    cell_key = f"{int(row[row_c] or 0)},{int(row[col_c] or 0)}"
                    coverage_map_lookup.setdefault(pid, {})[cell_key] = spans
                except (json.JSONDecodeError, TypeError):
                    pass

    # ── Read Prototype V1 ────────────────────────────────────────────────────
    ws = wb.active
    OFFSET = 1  # column 1 = unique_id; schema columns start at 2

    # Detect if this Excel has unique_id as column 1
    has_uid_col = ws.cell(row=1, column=1).value == "unique_id"
    field_offset = OFFSET if has_uid_col else 0

    patients = []
    for row_idx in range(2, ws.max_row + 1):
        # Skip rows with neither MRN nor NHS
        mrn_schema_col = next((f['excel_column'] for f in all_fields if f['key'] == 'mrn'), 3)
        nhs_schema_col = next((f['excel_column'] for f in all_fields if f['key'] == 'nhs_number'), 4)
        mrn_val = ws.cell(row=row_idx, column=mrn_schema_col + field_offset).value
        nhs_val = ws.cell(row=row_idx, column=nhs_schema_col + field_offset).value
        if not mrn_val and not nhs_val:
            continue

        # Read unique_id from column 1 if present
        unique_id = str(ws.cell(row=row_idx, column=1).value or '').strip() if has_uid_col else ''

        # Determine the lookup key (prefer unique_id, fall back to MRN)
        patient_id = str(mrn_val).strip() if mrn_val else f"patient_{row_idx - 1:03d}"
        lookup_key = unique_id or patient_id

        # Build extractions
        extractions = {}
        for group in groups:
            group_fields = {}
            for field in group['fields']:
                col = field['excel_column'] + field_offset
                cell_value = ws.cell(row=row_idx, column=col).value
                if cell_value is not None:
                    value = str(cell_value).strip()
                    meta = meta_lookup.get((lookup_key, field['key']),
                           meta_lookup.get((patient_id, field['key']), {}))
                    group_fields[field['key']] = FieldResult(
                        value=value,
                        confidence_basis=meta.get('confidence_basis', 'structured_verbatim'),
                        reason=meta.get('reason', ''),
                        source_cell=meta.get('source_cell'),
                        source_snippet=meta.get('source_snippet'),
                        edited=meta.get('edited', False),
                        original_value=meta.get('original_value'),
                    )
                else:
                    group_fields[field['key']] = FieldResult(value=None, confidence_basis='absent')
            extractions[group['name']] = group_fields

        # Extract identifiers from Demographics
        demo = extractions.get("Demographics", {})
        initials = demo.get("initials", FieldResult()).value or ''
        nhs_number = demo.get("nhs_number", FieldResult()).value or ''
        mrn = demo.get("mrn", FieldResult()).value or patient_id

        # Restore raw_cells + coverage_map
        raw_cells = rawcells_lookup.get(lookup_key, [])
        c_map = coverage_map_lookup.get(lookup_key, {})
        c_pct = coverage_lookup.get(lookup_key)

        patients.append(PatientBlock(
            id=mrn,
            unique_id=unique_id,
            initials=initials,
            nhs_number=nhs_number,
            raw_text="(imported from Excel)",
            extractions=extractions,
            raw_cells=raw_cells,
            coverage_map=c_map,
            coverage_pct=c_pct,
        ))

    wb.close()

    # ── Regenerate preview PNGs from raw_cells ──────────────────────────────
    if has_rawcells and patients:
        try:
            ts = str(int(time.time()))
            preview_dir = os.path.join(app.static_folder, 'previews', ts)
            os.makedirs(preview_dir, exist_ok=True)
            for p in patients:
                if p.raw_cells:
                    render_patient_preview(p, preview_dir)
            session.file_name = f"{ts}_imported.xlsx"
        except Exception as preview_err:
            log_event('preview_render_error', error=str(preview_err))

    return patients
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_export.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_export.py
git commit -m "feat: Excel import reads by header name, restores RawCells, regenerates previews"
```

---

## Task 9: Wire app.py — edit endpoint, preview route, coverage call, unique_id dedup

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Update `edit_field` endpoint to set `confidence_basis="edited"`**

In `app.py` around line 522, after `fr.edited = True`, add:
```python
fr.confidence_basis = "edited"
```

- [ ] **Step 2: Update `patient_preview` route to use `unique_id`**

Replace `patient_preview` function (lines 485–502):
```python
@app.route('/patient/<patient_id>/preview')
def patient_preview(patient_id):
    """Return rendered image URL and cell coordinate map for the patient."""
    # Support lookup by unique_id or legacy id
    patient = next(
        (p for p in session.patients
         if p.unique_id == patient_id or p.id == patient_id),
        None
    )
    if not patient:
        return jsonify({"error": "not found"}), 404
    if not session.file_name:
        return jsonify({"error": "no file"}), 404
    ts = session.file_name.split('_')[0]
    file_id = patient.unique_id if patient.unique_id else patient.id
    json_path = os.path.join(app.static_folder, 'previews', ts, f'{file_id}.json')
    if not os.path.exists(json_path):
        return jsonify({"error": "preview not available"}), 404
    with open(json_path) as f:
        coords = json.load(f)
    return jsonify({
        "image_url": f"/static/previews/{ts}/{file_id}.png",
        "coords": coords,
        "coverage_map": patient.coverage_map,
        "coverage_pct": patient.coverage_pct,
    })
```

- [ ] **Step 3: Add `_deduplicate_unique_ids` helper and call it after extraction**

Add after `_find_patient`:
```python
def _deduplicate_unique_ids(patients: list) -> None:
    """Ensure unique_id is unique within the batch. Append _b, _c... for collisions."""
    seen = {}
    suffix_chars = 'bcdefghijklmnopqrstuvwxyz'
    for patient in patients:
        uid = patient.unique_id
        if uid in seen:
            for ch in suffix_chars:
                candidate = f"{uid}_{ch}"
                if candidate not in seen:
                    patient.unique_id = candidate
                    seen[candidate] = True
                    break
        else:
            seen[uid] = True
```

First, add two top-level imports at the top of `app.py` alongside the existing extractor imports (around line 24):
```python
from extractor.regex_extractor import regex_extract, assign_unique_id
from extractor.coverage import compute_coverage
```
(Remove `assign_unique_id` from the existing `regex_extractor` import line if it was not already there.)

Then in `_run_extraction`, after all patients complete (just before `session.status = 'complete'`), add:
```python
# Assign unique_ids and compute coverage for all patients
for i, patient in enumerate(session.patients):
    if not patient.unique_id:
        assign_unique_id(patient, patient.extractions.get("Demographics", {}), row_index=i)
    compute_coverage(patient)
_deduplicate_unique_ids(session.patients)
```

- [ ] **Step 4: Fix `_resolve_source_cell` to search freeform cells only**

Update `_resolve_source_cell` (around line 829):
```python
def _resolve_source_cell(patient, fr):
    """Search freeform raw_cells (rows 4-7) for a cell containing fr.value."""
    if not fr.value or not patient.raw_cells:
        return
    freeform = [c for c in patient.raw_cells if c.get('row', 0) in {4, 5, 6, 7}]
    for cell in freeform:
        if fr.value in cell["text"]:
            fr.source_cell = {"row": cell["row"], "col": cell["col"]}
            if fr.source_snippet is None:
                fr.source_snippet = fr.value[:200]
            return
```

- [ ] **Step 5: Update the `/patients` list API to include `unique_id` and `coverage_pct`**

Find the route that returns the patient list (around line 400–440) and add `unique_id` and `coverage_pct` to the response dict for each patient.

- [ ] **Step 6: Run full test suite**

```
python -m pytest tests/ -v
```
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: wire coverage, unique_id dedup, edit confidence_basis, preview route uses unique_id"
```

---

## Task 10: Update review UI — coverage toggle + percentage badge + No source indicator

**Files:**
- Modify: `templates/review.html`
- Modify: `static/js/app.js`

> Before editing, read both files in full to understand existing structure and avoid breaking existing preview highlighting.

- [ ] **Step 1: Read current UI files**

Read `templates/review.html` and `static/js/app.js` fully to understand:
- Where the preview image is rendered
- How field source highlighting currently works (SVG/canvas overlay or CSS)
- Where to insert the toggle button and badge

- [ ] **Step 2: Add toggle button and badge to `templates/review.html`**

Near the preview panel, add a button and badge (Bootstrap 5):
```html
<!-- Coverage toggle — shown only when coverage data available -->
<div id="coverage-toggle-container" class="mb-2 d-none">
  <button id="coverage-toggle-btn" class="btn btn-sm btn-outline-warning" type="button">
    Show unused text
  </button>
  <span id="coverage-badge" class="badge bg-secondary ms-2">—% covered</span>
</div>
```

- [ ] **Step 3: Add "No source" indicator for fields with `source_cell = null`**

In the field rendering template section, add a small indicator when `source_cell` is absent:
```html
<!-- In field display loop -->
{% if field.source_cell %}
  <span class="source-link badge bg-light text-secondary border ms-1"
        data-row="{{ field.source_cell.row }}" data-col="{{ field.source_cell.col }}"
        title="Click to highlight source cell" style="cursor:pointer">src</span>
{% else %}
  <span class="badge bg-light text-muted border ms-1" title="Source cell not available">no src</span>
{% endif %}
```

- [ ] **Step 4: Add toggle logic in `static/js/app.js`**

After the existing preview highlight logic, add:
```javascript
// ── Coverage toggle ──────────────────────────────────────────────────────
let _coverageVisible = false;
let _coverageMap = null;
let _coveragePct = null;

function initCoverageToggle(coverageMap, coveragePct, coords) {
  _coverageMap = coverageMap;
  _coveragePct = coveragePct;

  const container = document.getElementById('coverage-toggle-container');
  const btn = document.getElementById('coverage-toggle-btn');
  const badge = document.getElementById('coverage-badge');

  if (!coverageMap || Object.keys(coverageMap).length === 0) {
    // Legacy import — no coverage data
    container.classList.remove('d-none');
    btn.disabled = true;
    btn.title = 'Coverage data not available (legacy file)';
    badge.classList.add('d-none');
    return;
  }

  container.classList.remove('d-none');
  if (coveragePct !== null && coveragePct !== undefined) {
    badge.textContent = `${coveragePct}% covered`;
  } else {
    badge.classList.add('d-none');
  }

  btn.addEventListener('click', () => {
    _coverageVisible = !_coverageVisible;
    btn.textContent = _coverageVisible ? 'Hide unused text' : 'Show unused text';
    btn.classList.toggle('btn-warning', _coverageVisible);
    btn.classList.toggle('btn-outline-warning', !_coverageVisible);
    renderCoverageOverlay(_coverageVisible, coords);
  });
}

function renderCoverageOverlay(show, coords) {
  // Remove existing overlay
  const existing = document.getElementById('coverage-svg-overlay');
  if (existing) existing.remove();
  if (!show || !_coverageMap || !coords) return;

  const previewImg = document.getElementById('preview-image');
  if (!previewImg) return;

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'coverage-svg-overlay';
  svg.style.cssText = `
    position:absolute; top:0; left:0;
    width:${previewImg.offsetWidth}px;
    height:${previewImg.offsetHeight}px;
    pointer-events:none; z-index:10;
  `;

  // For each cell in coverage_map, draw amber rect over unused spans
  // (approximation: highlight full cell if > 50% unused, else skip)
  for (const [cellKey, spans] of Object.entries(_coverageMap)) {
    if (!spans || spans.length === 0) continue;
    const cellCoord = coords[cellKey];
    if (!cellCoord) continue;
    const unusedLen = spans.filter(s => !s.used).reduce((a, s) => a + (s.end - s.start), 0);
    const totalLen = spans.reduce((a, s) => a + (s.end - s.start), 0);
    if (totalLen === 0 || unusedLen === 0) continue;

    const ratio = unusedLen / totalLen;
    const opacity = Math.min(0.6, ratio * 0.8);

    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', cellCoord.x);
    rect.setAttribute('y', cellCoord.y);
    rect.setAttribute('width', cellCoord.w);
    rect.setAttribute('height', cellCoord.h);
    rect.setAttribute('fill', `rgba(255,165,0,${opacity})`);
    rect.setAttribute('stroke', 'rgba(255,140,0,0.6)');
    rect.setAttribute('stroke-width', '1');
    svg.appendChild(rect);
  }

  const previewContainer = previewImg.parentElement;
  previewContainer.style.position = 'relative';
  previewContainer.appendChild(svg);
}
```

- [ ] **Step 5: Call `initCoverageToggle` when a patient's preview loads**

In the existing preview-load callback (where `coords` is received from `/patient/<id>/preview`), add:
```javascript
// After setting up the preview coords:
initCoverageToggle(data.coverage_map, data.coverage_pct, data.coords);
```

- [ ] **Step 6: Smoke test manually**

```
python app.py
```
1. Upload a `.docx` file → extraction completes → review a patient
2. Verify: confidence colours show green/orange/red correctly
3. Verify: clicking a field highlights the source cell in preview
4. Verify: "Show unused text" toggle button appears
5. Verify: clicking toggle shows amber overlay on freeform cells with unused text
6. Verify: badge shows a coverage percentage

Export the Excel, copy it to a different location, re-import it:
7. Verify: previews regenerate from RawCells
8. Verify: confidence colours preserved
9. Verify: coverage toggle works on re-imported file

- [ ] **Step 7: Commit**

```bash
git add templates/review.html static/js/app.js
git commit -m "feat: add coverage toggle, percentage badge, and No source indicator to review UI"
```

---

## Final verification

- [ ] Run full test suite one last time:

```
python -m pytest tests/ -v --tb=short
```
Expected: All tests pass.

- [ ] Check no regressions in existing tests (`test_schema`, `test_parser`, `test_clinical_context`, `test_llm_client`, `test_prompt_builder`).
