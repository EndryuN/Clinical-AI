# Source Panel, Confidence Overhaul & Pipeline Optimisation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a confidence-coloured source document panel to the review page, make confidence method-based (regex=HIGH, LLM=MEDIUM/red), enable live review during extraction, preserve confidence+reasoning in Excel round-trips, and replace the extraction pipeline with a two-phase regex-then-LLM architecture.

**Architecture:** Data model changes are foundational (Tasks 1–2); parser and regex extractor build on them; backend pipeline and API routes come next; Excel and frontend are last and consume the new APIs. Each task is independently testable before the next begins.

**Tech Stack:** Python 3.11, Flask 3.0, python-docx, openpyxl, requests, vanilla JS, Bootstrap 5. Tests use pytest. No new dependencies required.

**Spec:** `docs/superpowers/specs/2026-03-22-source-panel-pipeline-design.md`

---

## File Map

| File | What changes |
|---|---|
| `models.py` | Add `raw_cells` to `PatientBlock`; `source_cell`, `source_snippet` to `FieldResult`; new progress keys to `ExtractionSession` |
| `config/field_schema.yaml` | Add `llm_required: true` to 4 groups |
| `extractor/response_parser.py` | One-line cap: LLM `high` → `medium` |
| `parser/docx_parser.py` | Add `_table_to_cells()`; call in `parse_docx()` |
| `extractor/regex_extractor.py` | All 16 private extractors return `(value, raw_span)` tuples; `regex_extract()` accepts `raw_cells` param and resolves `source_cell` |
| `extractor/llm_client.py` | Module-level `requests.Session()` for connection pooling |
| `app.py` | Two-phase `_run_extraction()`; `/status` route; `_resolve_source_cell()` helper; `/patients/<id>` includes `raw_cells`+provenance; export fix; re-extract fix; Metadata import |
| `export/excel_writer.py` | Add hidden `Metadata` sheet |
| `templates/review.html` | Replace `<pre>` with `<div id="source-table">`; resize panel; add `#source-warning` |
| `static/js/app.js` | `highlightSource()`; `renderSourceTable()`; live SSE on review page; PENDING row state |
| `static/css/style.css` | MEDIUM/INFERRED → red; source panel sizing; PENDING row style |
| `tests/test_models.py` | New — data model defaults |
| `tests/test_parser.py` | New — `_table_to_cells()` |
| `tests/test_response_parser.py` | New — confidence cap |
| `tests/test_regex_extractor.py` | New — tuple return + source_cell resolution |
| `tests/test_export.py` | Extend — Metadata sheet round-trip |

---

## Task 1: Data Model Foundation

**Files:**
- Modify: `models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_models.py
from models import PatientBlock, FieldResult, ExtractionSession

def test_patient_block_has_raw_cells():
    p = PatientBlock(id="x")
    assert p.raw_cells == []

def test_field_result_has_provenance_fields():
    fr = FieldResult()
    assert fr.source_cell is None
    assert fr.source_snippet is None

def test_extraction_session_progress_has_phase_fields():
    s = ExtractionSession()
    assert s.progress['phase'] == 'idle'
    assert s.progress['regex_complete'] == 0
    assert s.progress['llm_queue_size'] == 0
    assert s.progress['llm_complete'] == 0
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd "C:/Users/Endryu/OneDrive/Documents/GitHub/Clinical-AI"
python -m pytest tests/test_models.py -v
```

Expected: `AttributeError` or `KeyError` — fields don't exist yet.

- [ ] **Step 3: Update `models.py`**

In `FieldResult` add after `original_value`:
```python
source_cell: Optional[dict] = None    # {"row": int, "col": int} or None
source_snippet: Optional[str] = None  # raw match span as it appears in doc
```

In `PatientBlock` add after `raw_text`:
```python
raw_cells: list = field(default_factory=list)
# [{"row": int, "col": int, "text": str}, ...] — all cells, including empty
```

In `ExtractionSession.progress` default dict, add these keys:
```python
"phase": "idle",        # "regex" | "llm" | "complete"
"regex_complete": 0,
"llm_queue_size": 0,
"llm_complete": 0,
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/test_models.py -v
```

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: add raw_cells and provenance fields to data model"
```

---

## Task 2: Schema — `llm_required` Flag

**Files:**
- Modify: `config/field_schema.yaml`
- Run existing: `tests/test_schema.py`

- [ ] **Step 1: Add `llm_required: true` to 4 groups**

In `config/field_schema.yaml`, find the groups named `Endoscopy`, `Baseline CT`, `Surgery`, and `Watch and Wait`. Add `llm_required: true` directly under the `name:` line of each:

```yaml
  - name: Endoscopy
    llm_required: true
    color: "#6AB0E3"
    ...
```

All other groups omit the key (callers use `.get('llm_required', False)`).

- [ ] **Step 2: Verify existing schema tests still pass**

```bash
python -m pytest tests/test_schema.py -v
```

Expected: all PASS (new optional key doesn't break existing assertions).

- [ ] **Step 3: Commit**

```bash
git add config/field_schema.yaml
git commit -m "feat: add llm_required flag to schema for LLM-dependent groups"
```

---

## Task 3: Confidence Cap — LLM Cannot Claim HIGH

**Files:**
- Modify: `extractor/response_parser.py`
- Modify: `static/css/style.css`
- Create: `tests/test_response_parser.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_response_parser.py
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
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/test_response_parser.py::test_llm_high_confidence_capped_to_medium -v
```

Expected: FAIL — currently `high` passes through.

- [ ] **Step 3: Add cap in `response_parser.py`**

In `parse_llm_response()`, find this block (around line 57):
```python
confidence = confidence.lower() if isinstance(confidence, str) else 'low'
if confidence not in ('high', 'medium', 'low'):
    confidence = 'low'
```

Add immediately after:
```python
# Cap: LLM may not claim HIGH — only regex earns HIGH
if confidence == 'high':
    confidence = 'medium'
```

- [ ] **Step 4: Run all response_parser tests — expect PASS**

```bash
python -m pytest tests/test_response_parser.py -v
```

- [ ] **Step 5: Update CSS for MEDIUM → red**

In `static/css/style.css`, find any rules referencing `.border-info`, `bg-warning`, or the teal/cyan inferred colour (`#0dcaf0`). Add or update:

```css
/* MEDIUM/INFERRED fields use red — same visual urgency as LOW */
.inferred-row {
    background-color: rgba(220, 53, 69, 0.05) !important;
}
.inferred-input {
    border-color: #dc3545 !important;
}
/* PENDING rows (not yet extracted in two-phase pipeline) */
.pending-row td {
    color: #555 !important;
    font-style: italic;
}
/* Source panel sizing */
#source-panel {
    min-height: 250px;
    resize: vertical;
    overflow-y: auto;
}
```

- [ ] **Step 6: Commit**

```bash
git add extractor/response_parser.py tests/test_response_parser.py static/css/style.css
git commit -m "feat: cap LLM confidence at medium, update INFERRED colour to red"
```

---

## Task 4: Parser — `_table_to_cells()`

**Files:**
- Modify: `parser/docx_parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Write failing test**

Use `unittest.mock` to create a minimal fake `python-docx` table:

```python
# tests/test_parser.py
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
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/test_parser.py -v
```

Expected: `ImportError` — `_table_to_cells` doesn't exist yet.

- [ ] **Step 3: Add `_table_to_cells()` to `docx_parser.py`**

Add after `_table_to_text()`:
```python
def _table_to_cells(table) -> list[dict]:
    """Return all cells in the table as a flat list with stable row/col coordinates.

    Empty cells are included so row/col indices are stable for source highlighting.
    """
    cells = []
    for i, row in enumerate(table.rows):
        for j, cell in enumerate(row.cells):
            cells.append({"row": i, "col": j, "text": cell.text.strip()})
    return cells
```

- [ ] **Step 4: Call `_table_to_cells()` in `parse_docx()`**

In `parse_docx()`, find where `raw_text = _table_to_text(table)` is called. Add immediately after:
```python
raw_cells = _table_to_cells(table)
```

Then in the `PatientBlock(...)` constructor call, add:
```python
raw_cells=raw_cells,
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
python -m pytest tests/test_parser.py -v
```

- [ ] **Step 6: Commit**

```bash
git add parser/docx_parser.py tests/test_parser.py
git commit -m "feat: add _table_to_cells() and populate PatientBlock.raw_cells"
```

---

## Task 5: Regex Extractor Refactor — Return `(value, raw_span)` Tuples

**Files:**
- Modify: `extractor/regex_extractor.py`
- Create: `tests/test_regex_extractor.py`

This is the most invasive change. All 16 private `_extract_*` functions currently return `dict[str, Optional[str]]`. They must return `dict[str, Optional[tuple[str, str]]]` where each value is `(normalised_value, raw_match_span)`. The `regex_extract()` public function is the only place that unpacks them.

**The pattern for each extractor:** wherever you have `result['key'] = value`, change to `result['key'] = (value, raw_match_span)`. The `raw_match_span` is `m.group(0)` (the full regex match) or the raw string before normalisation.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_regex_extractor.py
from models import PatientBlock
from extractor.regex_extractor import regex_extract

DEMO_RAW_TEXT = """Cancer Type: Colorectal
MDT Meeting Date: 07/03/2025

Hospital Number: 9990000001
NHS Number: 999 000 0001
ALICE O'CONNOR (b)
Female (e) DOB: 12/05/1955 (a)

Diagnosis & Staging
T3 N1 M0
"""

DEMO_CELLS = [
    {"row": 0, "col": 0, "text": "Patient Details"},
    {"row": 1, "col": 0, "text": "Hospital Number: 9990000001\nNHS Number: 999 000 0001\nALICE O'CONNOR (b)\nFemale (e) DOB: 12/05/1955 (a)"},
    {"row": 2, "col": 0, "text": "Diagnosis & Staging"},
    {"row": 3, "col": 0, "text": "T3 N1 M0"},
]

DEMO_FIELDS = [
    {'key': 'dob', 'type': 'date'},
    {'key': 'gender', 'type': 'string'},
    {'key': 'mrn', 'type': 'string'},
]

def test_regex_extract_returns_field_results():
    results = regex_extract(DEMO_RAW_TEXT, "Demographics", DEMO_FIELDS, DEMO_CELLS)
    assert 'dob' in results
    assert results['dob'].value == "12/05/1955"
    assert results['dob'].confidence == 'high'

def test_regex_extract_sets_source_cell_for_matched_field():
    results = regex_extract(DEMO_RAW_TEXT, "Demographics", DEMO_FIELDS, DEMO_CELLS)
    # DOB appears in row 1, col 0
    assert results['dob'].source_cell == {"row": 1, "col": 0}
    assert results['dob'].source_snippet is not None
    assert "1955" in results['dob'].source_snippet

def test_regex_extract_source_cell_none_when_not_found():
    results = regex_extract(DEMO_RAW_TEXT, "Demographics", DEMO_FIELDS, raw_cells=[])
    # No cells to search — source_cell should be None
    assert results['dob'].source_cell is None

def test_regex_extract_unmatched_field_has_none_value():
    results = regex_extract(DEMO_RAW_TEXT, "Demographics", DEMO_FIELDS, DEMO_CELLS)
    # previous_cancer not in DEMO_FIELDS so won't appear, but gender is
    assert results['gender'].value in ('Female', 'Male', None)
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/test_regex_extractor.py -v
```

Expected: `TypeError` — `regex_extract()` doesn't accept `raw_cells` yet.

- [ ] **Step 3: Update `regex_extract()` signature and unpacking logic**

Change the function signature:
```python
def regex_extract(raw_text: str, group_name: str, fields: list[dict], raw_cells: list[dict] = None) -> dict[str, FieldResult]:
```

Replace the result-building loop (currently lines 42–56) with:
```python
extracted = extractor(raw_text)
raw_cells = raw_cells or []

results = {}
for f in fields:
    key = f['key']
    raw_result = extracted.get(key)
    if raw_result is not None:
        # Unpack (normalised_value, raw_match_span) tuple
        value, raw_span = raw_result
        # Find source cell by searching raw_cells for the match span
        source_cell = None
        source_snippet = None
        if raw_span:
            for cell in raw_cells:
                if raw_span in cell["text"]:
                    source_cell = {"row": cell["row"], "col": cell["col"]}
                    source_snippet = raw_span
                    break
        results[key] = FieldResult(
            value=value,
            confidence='high',
            reason='Extracted verbatim from document text',
            source_cell=source_cell,
            source_snippet=source_snippet,
        )
    else:
        results[key] = FieldResult(value=None, confidence='none', reason='')
return results
```

- [ ] **Step 4: Update all 16 private `_extract_*` functions**

For each `result['key'] = some_value` assignment, change to `result['key'] = (some_value, raw_match_span)`.

**Pattern A — direct match group:**
```python
# Before:
m = re.search(r'...', text)
if m:
    result['dob'] = m.group(1)
# After:
m = re.search(r'...', text)
if m:
    result['dob'] = (m.group(1), m.group(0))  # (normalised, full match)
```

**Pattern B — normalised value (e.g. EMVI → "Positive"):**
```python
# Before:
result['emvi'] = 'Positive'
# After:
result['emvi'] = ('Positive', m.group(0))  # raw match preserved
```

**Pattern C — computed value (e.g. initials derived from name):**
```python
# Before:
result['initials'] = ''.join(p[0].upper() for p in parts if p)
# After:
result['initials'] = (''.join(p[0].upper() for p in parts if p), name_match.group(0) if hasattr(name_match, 'group') else name)
```

Apply this pattern to all 16 functions: `_extract_demographics`, `_extract_endoscopy`, `_extract_histology`, `_extract_baseline_mri`, `_extract_baseline_ct`, `_extract_mdt`, `_extract_chemotherapy`, `_extract_immunotherapy`, `_extract_radiotherapy`, `_extract_cea`, `_extract_surgery`, `_extract_second_mri`, `_extract_12week_mri`, `_extract_flexsig`, `_extract_watch_wait`, `_extract_ww_dates`.

- [ ] **Step 5: Run all tests — expect PASS**

```bash
python -m pytest tests/test_regex_extractor.py tests/test_models.py tests/test_parser.py -v
```

- [ ] **Step 6: Commit**

```bash
git add extractor/regex_extractor.py tests/test_regex_extractor.py
git commit -m "feat: regex extractor returns (value, raw_span) tuples for source provenance"
```

---

## Task 6: Connection Pooling

**Files:**
- Modify: `extractor/llm_client.py`

- [ ] **Step 1: Add module-level Session**

At the top of `extractor/llm_client.py`, after the existing imports, add:
```python
_session = requests.Session()
```

- [ ] **Step 2: Replace all `requests.post()` and `requests.get()` calls**

In `_generate_claude()`, change:
```python
resp = requests.post(CLAUDE_URL, headers=headers, json=payload, timeout=TIMEOUT)
```
to:
```python
resp = _session.post(CLAUDE_URL, headers=headers, json=payload, timeout=TIMEOUT)
```

In `_generate_ollama()`, change:
```python
resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=TIMEOUT)
```
to:
```python
resp = _session.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=TIMEOUT)
```

In `list_ollama_models()` and `check_ollama_available()`, change `requests.get(...)` to `_session.get(...)`.

- [ ] **Step 3: Verify existing tests still pass**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add extractor/llm_client.py
git commit -m "perf: use requests.Session for connection pooling in LLM client"
```

---

## Task 7: Backend — Routes, Helper, Bug Fixes

**Files:**
- Modify: `app.py`

This task covers: `_resolve_source_cell()` helper, updated `/patients/<id>` response, new `/status` route, export-on-stop fix, re-extract hybrid fix. The pipeline rewrite is Task 8.

- [ ] **Step 1: Add `_resolve_source_cell()` helper**

Add to `app.py` helper functions section (near the bottom, before `_find_patient`):
```python
def _resolve_source_cell(patient, fr):
    """Search patient.raw_cells for fr.value and populate fr.source_cell/source_snippet."""
    if not fr.value or not patient.raw_cells:
        return
    for cell in patient.raw_cells:
        if fr.value in cell["text"]:
            fr.source_cell = {"row": cell["row"], "col": cell["col"]}
            fr.source_snippet = fr.value
            return
```

- [ ] **Step 2: Update `/patients/<id>` serialisation**

In `get_patient()`, replace the extractions serialisation:
```python
extractions[group_name] = {
    key: {
        "value": fr.value,
        "confidence": fr.confidence,
        "reason": fr.reason,
        "edited": fr.edited,
        "source_cell": fr.source_cell,
        "source_snippet": fr.source_snippet,
    }
    for key, fr in fields.items()
}
```

Add `raw_cells` to the response dict:
```python
return jsonify({
    "id": patient.id,
    "initials": patient.initials,
    "nhs_number": patient.nhs_number,
    "raw_text": patient.raw_text,
    "raw_cells": patient.raw_cells,
    "extractions": extractions
})
```

- [ ] **Step 3: Add `/status` route**

```python
@app.route('/status')
def status():
    return jsonify({
        "status": session.status,
        "current": session.progress['current_patient'],
        "total": session.progress['total'],
        "phase": session.progress.get('phase', 'idle'),
    })
```

- [ ] **Step 4: Fix export-on-stop**

In the `export()` route, change:
```python
if session.status != 'complete' or not session.patients:
```
to:
```python
if session.status not in ('complete', 'stopped') or not session.patients:
```

- [ ] **Step 5: Fix `_do_re_extract()` to use hybrid pipeline**

Replace the current `_do_re_extract()` inner function:
```python
def _do_re_extract():
    groups = get_groups()
    for group in groups:
        if group['name'] in target_groups:
            try:
                # Phase 1: regex
                results = regex_extract(patient.raw_text, group['name'], group['fields'], patient.raw_cells)
                # Phase 2: LLM for gaps in LLM groups
                if group.get('llm_required', False):
                    gaps = sum(1 for fr in results.values() if fr.value is None)
                    if gaps > 0:
                        prompt = build_prompt(patient.raw_text, group)
                        raw_response = generate(prompt)
                        llm_results = parse_llm_response(raw_response, group)
                        for key, llm_fr in llm_results.items():
                            if results[key].value is None and llm_fr.value is not None:
                                _resolve_source_cell(patient, llm_fr)
                                llm_fr.reason = f"[LLM] {llm_fr.reason}"
                                results[key] = llm_fr
                patient.extractions[group['name']] = results
            except Exception:
                pass
```

- [ ] **Step 6: Update `regex_extract()` call sites**

`app.py` calls `regex_extract(patient.raw_text, group['name'], group['fields'])` in the old `_run_extraction`. After Task 8 rewrites that function, all calls will use the new signature. For now, grep for any other calls:

```bash
grep -n "regex_extract(" app.py
```

Update each found call to pass `patient.raw_cells` as the 4th argument.

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: add source provenance to API, /status route, export-on-stop fix, re-extract hybrid"
```

---

## Task 8: Two-Phase Extraction Pipeline

**Files:**
- Modify: `app.py`

This replaces `_run_extraction()` entirely. Read the spec section 5 for the full pseudocode — this task implements it exactly.

- [ ] **Step 1: Replace `_run_extraction()`**

Remove the existing `_run_extraction()` function and replace with:

```python
def _run_extraction(patient_limit=None, concurrency=1):
    import time
    import threading
    from concurrent.futures import ThreadPoolExecutor

    groups = get_groups()
    llm_groups = [g for g in groups if g.get('llm_required', False)]
    patients_to_process = session.patients[:patient_limit] if patient_limit else session.patients

    session.progress['total'] = len(patients_to_process)
    session.progress['phase'] = 'regex'
    session.progress['regex_complete'] = 0
    session.progress['llm_complete'] = 0
    session.progress['current_patient'] = 0
    session.progress['patient_times'] = []
    session.progress['active_patients'] = {}
    session.progress.setdefault('completed_patients', [])

    _counter_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Phase 1 — Regex sweep (fully parallel across all patients)          #
    # ------------------------------------------------------------------ #
    def regex_phase(patient):
        if session.stop_requested:
            return
        session.progress['active_patients'][patient.id] = {
            "initials": patient.initials, "group": "Regex", "start": time.time()
        }
        for group in groups:
            results = regex_extract(patient.raw_text, group['name'], group['fields'], patient.raw_cells)
            # Pre-populate LLM groups with none-stubs for complete dict structure
            if group.get('llm_required', False):
                for key, fr in results.items():
                    if fr.value is None:
                        results[key] = FieldResult(value=None, confidence='none')
            patient.extractions[group['name']] = results
        del session.progress['active_patients'][patient.id]
        with _counter_lock:
            session.progress['regex_complete'] += 1

    with ThreadPoolExecutor(max_workers=min(len(patients_to_process), 16)) as ex:
        list(ex.map(regex_phase, patients_to_process))

    if session.stop_requested:
        session.status = 'stopped'
        return

    # ------------------------------------------------------------------ #
    # Phase 2 — LLM queue (semaphore-controlled, Ollama is serial)        #
    # ------------------------------------------------------------------ #
    session.progress['phase'] = 'llm'
    llm_semaphore = threading.Semaphore(1)

    llm_tasks = [
        (patient, group)
        for patient in patients_to_process
        for group in llm_groups
        if any(fr.value is None for fr in patient.extractions.get(group['name'], {}).values())
    ]
    session.progress['llm_queue_size'] = len(llm_tasks)

    def llm_phase(task):
        patient, group = task
        if session.stop_requested:
            return
        task_key = f"{patient.id}:{group['name']}"
        session.progress['active_patients'][task_key] = {
            "initials": patient.initials, "group": group['name'], "start": time.time()
        }
        with llm_semaphore:
            try:
                prompt = build_prompt(patient.raw_text, group)
                raw_response = generate(prompt)
                llm_results = parse_llm_response(raw_response, group)
                for key, llm_fr in llm_results.items():
                    current = patient.extractions[group['name']].get(key)
                    if current and current.value is None and llm_fr.value is not None:
                        _resolve_source_cell(patient, llm_fr)
                        llm_fr.reason = f"[LLM] {llm_fr.reason}"
                        patient.extractions[group['name']][key] = llm_fr
            except Exception:
                pass
        del session.progress['active_patients'][task_key]
        with _counter_lock:
            session.progress['llm_complete'] += 1
            session.progress['current_patient'] = session.progress['llm_complete']

        # Record completed patient when all its LLM groups are done
        patient_llm_done = all(
            session.progress['active_patients'].get(f"{patient.id}:{g['name']}") is None
            for g in llm_groups
        )
        if patient_llm_done:
            conf = _confidence_summary(patient)
            session.progress['completed_patients'].append({
                "id": patient.id,
                "initials": patient.initials,
                "confidence_summary": conf,
                "seconds": 0,
            })

    # Track per-patient group completion to avoid premature "done" signals.
    # Use a counter dict: {patient_id: number_of_llm_groups_completed}
    _patient_group_counts = {p.id: 0 for p in patients_to_process}

    def llm_phase(task):
        patient, group = task
        # ... (same body as above, but replace the patient_llm_done block) ...
        with _counter_lock:
            session.progress['llm_complete'] += 1
            session.progress['current_patient'] = session.progress['llm_complete']
            _patient_group_counts[patient.id] += 1
            # Patient is fully done only when ALL its LLM groups have completed
            if _patient_group_counts[patient.id] == len(llm_groups):
                conf = _confidence_summary(patient)
                session.progress['completed_patients'].append({
                    "id": patient.id,
                    "initials": patient.initials,
                    "confidence_summary": conf,
                    "seconds": 0,
                })

    # max_workers=2: one runs (semaphore), one queues ready. Prevents gap between tasks.
    with ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(llm_phase, llm_tasks))

    session.status = 'complete' if not session.stop_requested else 'stopped'
    session.progress['phase'] = 'complete'
```

- [ ] **Step 2: Smoke test — start the app and run a small extraction**

```bash
python app.py
# In browser: upload a .docx, set patient limit to 3, start extraction
# Verify: progress bar moves, review page shows patients during extraction
```

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: two-phase extraction pipeline (regex sweep + LLM queue with semaphore)"
```

---

## Task 9: Excel — Metadata Sheet Round-Trip

**Files:**
- Modify: `export/excel_writer.py`
- Modify: `app.py` (`_import_excel`)
- Modify: `tests/test_export.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_export.py`:
```python
from models import PatientBlock, FieldResult
from export.excel_writer import write_excel
from openpyxl import load_workbook
import tempfile, os

def test_excel_exports_metadata_sheet():
    patient = PatientBlock(
        id="p001", initials="AO", nhs_number="9990000001", raw_text="test",
        extractions={
            "Demographics": {
                "dob": FieldResult(value="26/05/1970", confidence="high", reason="regex match"),
                "initials": FieldResult(value="AO", confidence="high", reason=""),
                "mrn": FieldResult(value="9990001", confidence="high", reason=""),
                "nhs_number": FieldResult(value="9990000001", confidence="medium", reason="LLM inferred"),
                "gender": FieldResult(value="Male", confidence="high", reason=""),
                "previous_cancer": FieldResult(value=None, confidence="none", reason=""),
                "previous_cancer_site": FieldResult(value=None, confidence="none", reason=""),
            }
        }
    )
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        path = f.name
    try:
        write_excel([patient], path)
        wb = load_workbook(path)
        assert "Metadata" in wb.sheetnames
        ws = wb["Metadata"]
        # Header row
        assert ws.cell(1, 1).value == "patient_id"
        # Find nhs_number row and check confidence
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        nhs_row = next((r for r in rows if r[0] == "p001" and r[1] == "nhs_number"), None)
        assert nhs_row is not None
        assert nhs_row[2] == "medium"
        assert "LLM inferred" in (nhs_row[3] or "")
        wb.close()
    finally:
        os.unlink(path)

def test_excel_round_trip_restores_confidence_and_reason():
    """Export then re-import — confidence and reason must survive."""
    from app import _import_excel  # noqa: import after path setup
    patient = PatientBlock(
        id="p001", initials="AO", nhs_number="9990000001", raw_text="test",
        extractions={
            "Demographics": {
                "dob": FieldResult(value="26/05/1970", confidence="high", reason="regex"),
                "initials": FieldResult(value="AO", confidence="high", reason=""),
                "mrn": FieldResult(value="9990001", confidence="high", reason=""),
                "nhs_number": FieldResult(value="9990000001", confidence="medium", reason="LLM"),
                "gender": FieldResult(value="Male", confidence="high", reason=""),
                "previous_cancer": FieldResult(value=None, confidence="none", reason=""),
                "previous_cancer_site": FieldResult(value=None, confidence="none", reason=""),
            }
        }
    )
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        path = f.name
    try:
        write_excel([patient], path)
        reimported = _import_excel(path)
        demo = reimported[0].extractions.get("Demographics", {})
        assert demo["nhs_number"].confidence == "medium"
        assert "LLM" in (demo["nhs_number"].reason or "")
        assert demo["dob"].confidence == "high"
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/test_export.py::test_excel_exports_metadata_sheet -v
```

- [ ] **Step 3: Add Metadata sheet to `write_excel()`**

In `export/excel_writer.py`, after `wb.save(output_path)` is about to be called (end of the function, after auto-width loop), add before `wb.save`:

```python
# Hidden Metadata sheet — stores confidence + reasoning for round-trip fidelity
ws_meta = wb.create_sheet("Metadata")
ws_meta.sheet_state = 'hidden'
ws_meta.append(["patient_id", "field_key", "confidence", "reason"])
for patient in patients:
    for group_name, fields in patient.extractions.items():
        for field_key, fr in fields.items():
            ws_meta.append([
                patient.id,
                field_key,
                fr.confidence or 'none',
                fr.reason or ''
            ])
```

- [ ] **Step 4: Update `_import_excel()` to read Metadata sheet**

In `app.py`, in `_import_excel()`, after `wb = load_workbook(file_path)` and `ws = wb.active`, add:

```python
# Load Metadata sheet if present (written by new exporter)
meta_lookup = {}
if "Metadata" in wb.sheetnames:
    ws_meta = wb["Metadata"]
    for row in ws_meta.iter_rows(min_row=2, values_only=True):
        pid, fkey, conf, reason = row
        if pid and fkey:
            meta_lookup[(str(pid), str(fkey))] = {
                "confidence": conf or 'high',
                "reason": reason or ''
            }
```

Then in the field-building loop, replace:
```python
group_fields[field['key']] = FieldResult(value=value, confidence='high')
```
with:
```python
meta = meta_lookup.get((patient_id, field['key']), {})
group_fields[field['key']] = FieldResult(
    value=value,
    confidence=meta.get('confidence', 'high'),
    reason=meta.get('reason', '')
)
```

- [ ] **Step 5: Run all export tests — expect PASS**

```bash
python -m pytest tests/test_export.py -v
```

- [ ] **Step 6: Commit**

```bash
git add export/excel_writer.py app.py tests/test_export.py
git commit -m "feat: Excel Metadata sheet preserves confidence and reasoning for round-trip import"
```

---

## Task 10: Frontend — Source Panel and Live Review

**Files:**
- Modify: `templates/review.html`
- Modify: `static/js/app.js`

- [ ] **Step 1: Update `review.html`**

Replace the source text panel block:
```html
<!-- OLD: -->
<div class="border-top border-secondary p-3" style="max-height: 150px; overflow-y: auto;">
    <div class="text-muted small text-uppercase mb-1">Source Text</div>
    <pre id="source-text" class="text-muted small mb-0" style="white-space: pre-wrap;">Select a patient to view source text</pre>
</div>
```
with:
```html
<div id="source-panel" class="border-top border-secondary p-3" style="min-height: 250px; resize: vertical; overflow-y: auto;">
    <div class="text-muted small text-uppercase mb-1">Source Document</div>
    <div id="source-warning" class="d-none alert alert-danger py-1 small mt-1 mb-2">
        Value not found in source document — possible hallucination
    </div>
    <div id="source-table">
        <span class="text-muted small">Select a patient to view source document</span>
    </div>
</div>
```

- [ ] **Step 2: Add `renderSourceTable()` to `app.js`**

Add this function after `selectPatient()`:
```javascript
function renderSourceTable(rawCells) {
    const container = document.getElementById('source-table');
    if (!container) return;
    if (!rawCells || rawCells.length === 0) {
        container.innerHTML = '<span class="text-muted small">No source document available (imported from Excel)</span>';
        return;
    }

    // Group cells by row index
    const rowMap = {};
    rawCells.forEach(cell => {
        if (!rowMap[cell.row]) rowMap[cell.row] = {};
        rowMap[cell.row][cell.col] = cell.text;
    });

    const numCols = Math.max(...rawCells.map(c => c.col)) + 1;
    const headerRows = new Set([0, 2, 4, 6]); // known Word table header rows

    let html = '<table class="table table-dark table-sm table-bordered mb-0" style="font-size:10px; font-family:monospace;">';
    Object.keys(rowMap).sort((a, b) => +a - +b).forEach(rowIdx => {
        const isHeader = headerRows.has(+rowIdx);
        html += `<tr style="${isHeader ? 'background:#21262d;' : ''}">`;
        for (let c = 0; c < numCols; c++) {
            const text = rowMap[rowIdx][c] || '';
            // Always render all cols (including col 1) so data-row/col attrs are stable for
            // highlightSource(). Visually dim col 1 if it duplicates col 0 — but never skip it,
            // as source_cell may legitimately point to col 1.
            const isDupe = c === 1 && text === (rowMap[rowIdx][0] || '');
            const cellStyle = `color:${isHeader ? '#58a6ff' : '#8b949e'}; vertical-align:top; max-width:300px; word-break:break-word; ${isDupe ? 'opacity:0.3;' : ''}`;
            html += `<td data-row="${rowIdx}" data-col="${c}" style="${cellStyle}">${text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</td>`;
        }
        html += '</tr>';
    });
    html += '</table>';
    container.innerHTML = html;
}
```

- [ ] **Step 3: Update `selectPatient()` to call `renderSourceTable()`**

In `selectPatient()`, replace:
```javascript
const sourceText = document.getElementById('source-text');
if (sourceText) sourceText.textContent = data.raw_text || '';
```
with:
```javascript
renderSourceTable(data.raw_cells || []);
```

Store `raw_cells` alongside extractions:
```javascript
window._currentRawCells = data.raw_cells || [];
```

- [ ] **Step 4: Add `highlightSource()` to `app.js`**

```javascript
function highlightSource(fr) {
    // Clear all previous highlights
    document.querySelectorAll('#source-table td').forEach(td => {
        td.style.border = '';
        td.style.background = '';
        // Restore plain text (remove any <mark> wrappers)
        if (td.querySelector('mark')) {
            td.textContent = td.textContent;
        }
    });
    const warning = document.getElementById('source-warning');
    if (warning) warning.classList.add('d-none');

    if (!fr || fr.value === null || fr.value === undefined) return;

    const conf = fr.confidence || 'none';
    const colours = {
        high:   { border: '#198754', mark: 'rgba(25,135,84,0.3)',  text: '#6ee7a0' },
        medium: { border: '#dc3545', mark: 'rgba(220,53,69,0.25)', text: '#ff8c94' },
        low:    { border: '#dc3545', mark: 'rgba(220,53,69,0.35)', text: '#ff6b6b' },
    };
    const colour = colours[conf];

    if (fr.source_cell && colour) {
        const { row, col } = fr.source_cell;
        const td = document.querySelector(`#source-table td[data-row="${row}"][data-col="${col}"]`);
        if (td) {
            td.style.border = `2px solid ${colour.border}`;
            td.style.background = colour.mark;
            // Highlight snippet using textContent split (XSS-safe)
            if (fr.source_snippet) {
                const fullText = td.textContent;
                const idx = fullText.indexOf(fr.source_snippet);
                if (idx !== -1) {
                    td.textContent = '';
                    const before = document.createTextNode(fullText.slice(0, idx));
                    const mark = document.createElement('mark');
                    mark.style.cssText = `background:${colour.mark}; color:${colour.text}; border-radius:2px; padding:0 2px;`;
                    mark.textContent = fr.source_snippet;
                    const after = document.createTextNode(fullText.slice(idx + fr.source_snippet.length));
                    td.appendChild(before);
                    td.appendChild(mark);
                    td.appendChild(after);
                }
            }
            td.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    } else if (fr.value !== null) {
        // Value exists but no source cell — possible hallucination
        if (warning) warning.classList.remove('d-none');
    }
}
```

- [ ] **Step 5: Update `renderFieldTable()` to add click handlers and MEDIUM→red and PENDING state**

In `renderFieldTable()`:

1. Change MEDIUM/inferred colour from `info` to `danger`:
```javascript
// Before:
const confClass = !hasValue ? 'secondary' :
                  isInferred ? 'info' :
// After:
const confClass = !hasValue ? 'secondary' :
                  isInferred ? 'danger' :
```

2. Add PENDING state for `confidence='none'` with null value:
```javascript
const isPending = !hasValue && fr.confidence === 'none' && !fr.edited;
```
In the row HTML, add class:
```javascript
<tr style="border-left: 4px solid ${groupColor}; ${rowBg}" class="${isPending ? 'pending-row' : ''}"
    onclick="highlightSource(${JSON.stringify({value: fr.value, confidence: fr.confidence, source_cell: fr.source_cell, source_snippet: fr.source_snippet})})">
```
And in badge text:
```javascript
const confText = !hasValue ? (isPending ? 'PENDING' : 'EMPTY') : ...
```

- [ ] **Step 6: Update sidebar badge colour for `medium` in `renderPatientList()`**

In `app.js`, in `renderPatientList()`, find:
```javascript
<span class="badge bg-warning text-dark" style="font-size:10px">${c.medium || 0} med</span>
```
Change to:
```javascript
<span class="badge bg-danger" style="font-size:10px">${c.medium || 0} med</span>
```

This makes the sidebar confidence counts consistent with the field-level badge colours (both show MEDIUM as red).

- [ ] **Step 7: Add live SSE subscription to review page**

At the end of `app.js`, add:
```javascript
// ===== Live Review During Extraction =====
function initLiveReview() {
    fetch('/status')
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'extracting') return;
            const source = new EventSource('/progress');
            let lastCompleted = 0;

            source.onmessage = function(event) {
                const d = JSON.parse(event.data);
                const completed = (d.completed_patients || []).length;
                if (completed > lastCompleted) {
                    lastCompleted = completed;
                    loadPatients();
                }
                if (d.status === 'complete' || d.status === 'stopped') {
                    source.close();
                    loadPatients();
                }
            };
            window.addEventListener('beforeunload', () => source.close());
        })
        .catch(() => {});
}

// Only run on review page
if (document.getElementById('source-panel')) {
    initLiveReview();
}
```

- [ ] **Step 7: Manual smoke test**

1. Start the app: `python app.py`
2. Upload a `.docx`, start extraction with limit=5
3. Navigate to `/review` immediately — verify sidebar shows patients as they complete
4. Click a patient → click the `endoscopy_findings` row → source panel should highlight the correct cell in green/red
5. Click an LLM-only field with no source → hallucination warning appears
6. Export Excel → re-import → verify confidence badges match original

- [ ] **Step 8: Commit**

```bash
git add templates/review.html static/js/app.js
git commit -m "feat: source document panel with confidence-coloured highlighting and live review"
```

---

## Task 11: Final Validation

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 2: Run schema tests**

```bash
python -m pytest tests/test_schema.py -v
```

- [ ] **Step 3: Final commit**

```bash
git add models.py config/field_schema.yaml extractor/ parser/ app.py export/ templates/ static/ tests/
git commit -m "feat: complete source panel, confidence overhaul, pipeline and Excel round-trip"
```

---

## Quick Reference — Confidence Colour Mapping

| Confidence | Source `<td>` border | `<mark>` bg | Review badge | Row bg |
|---|---|---|---|---|
| `high` | `#198754` green | `rgba(25,135,84,0.3)` | `bg-success` | none |
| `medium` (INFERRED) | `#dc3545` red | `rgba(220,53,69,0.25)` | `bg-danger` | `rgba(220,53,69,0.05)` |
| `low` | `#dc3545` red 2px | `rgba(220,53,69,0.35)` | `bg-danger` | none |
| `none` (EMPTY/PENDING) | none | none | `bg-secondary` | pending-row class |
