# Design Spec: Source Panel, Confidence Overhaul, Live Review, Pipeline Optimisation

**Date:** 2026-03-22
**Status:** Approved

---

## Overview

Six related improvements to the MDT Extractor, designed and confirmed together:

1. Source document panel with reconstructed Word table and confidence-coloured highlighting
2. Method-based confidence levels (replaces LLM self-report)
3. Live review during extraction (review page populates as patients complete)
4. Excel round-trip with confidence + reasoning preserved via hidden Metadata sheet
5. Two-phase extraction pipeline (regex sweep → LLM queue)
6. Bug fixes: race condition, re-extract pipeline, export on stop, LLM_GROUPS in schema

---

## 1. Source Document Panel

### Goal
Show the original Word document table structure below the field table in the review page. When a field row is clicked, highlight the source cell (coloured border) and the specific matched text within it (coloured mark). Colour reflects confidence level.

### Data Model Changes

**`models.py` — `PatientBlock`**
```python
raw_cells: list = field(default_factory=list)
# Each item: {"row": int, "col": int, "text": str}
# Empty cells are INCLUDED (text="") so row/col coordinates are stable
```
`raw_text` remains unchanged (used for LLM prompts, debug).

**`models.py` — `FieldResult`**
```python
source_cell: Optional[dict] = None   # {"row": int, "col": int} — absolute table coordinates
source_snippet: Optional[str] = None  # exact matched text within that cell (raw match span)
```
`source_cell` stores absolute `{"row": i, "col": j}` table coordinates, NOT list indices. This is stable regardless of how many empty cells exist.

### Parser Changes (`parser/docx_parser.py`)

Add `_table_to_cells(table) -> list[dict]`:
```python
def _table_to_cells(table) -> list[dict]:
    cells = []
    for i, row in enumerate(table.rows):
        for j, cell in enumerate(row.cells):
            cells.append({"row": i, "col": j, "text": cell.text.strip()})
    return cells
```
All cells included (including empty ones) so row/col coordinates are stable. All 3 columns included (the Word table has 3 columns). `parse_docx()` calls both `_table_to_text()` (unchanged) and `_table_to_cells()`, stores result in `PatientBlock.raw_cells`.

### Regex Extractor Changes (`extractor/regex_extractor.py`)

The actual code structure: each private extractor function (e.g. `_extract_demographics`, `_extract_endoscopy`) returns a `dict[str, Optional[str]]` mapping field key → normalised value. The public `regex_extract()` iterates these dicts to build `FieldResult` objects.

The change: dict values change from `Optional[str]` to `Optional[tuple[str, str]]` — `(normalised_value, raw_match_span)`:
- `normalised_value` is the processed field value (e.g. `"T3b"`, `"Positive"`, `"AO"`)
- `raw_match_span` is `match.group()` — the exact unprocessed substring as it appears in the document

The **public `regex_extract()` function** is the single place that unpacks these tuples:
```python
for key, result in extractor_dict.items():
    if result is not None:
        value, raw_span = result
        # Find source cell
        source_cell = None
        source_snippet = None
        for cell in raw_cells:
            if raw_span and raw_span in cell["text"]:
                source_cell = {"row": cell["row"], "col": cell["col"]}
                source_snippet = raw_span
                break
        field_results[key] = FieldResult(value=value, confidence='high',
                                          source_cell=source_cell,
                                          source_snippet=source_snippet)
    else:
        field_results[key] = FieldResult(value=None, confidence='none')
```
`raw_cells` is passed into `regex_extract()` as a new parameter alongside `raw_text`.

### LLM Source Cell Resolution (merge step in `app.py`)

After LLM extraction and merge:
- For each LLM-filled field, search `patient.raw_cells` for a cell containing the extracted value as a substring
- If found: set `source_cell = {"row": r, "col": c}` and `source_snippet = field_result.value`
- If not found: leave `source_cell = None` — this is the hallucination signal shown to the user

### Backend (`app.py`)

`GET /patients/<id>` serialisation must include `source_cell` and `source_snippet` per field:
```python
extractions[group_name] = {
    key: {
        "value": fr.value,
        "confidence": fr.confidence,
        "reason": fr.reason,
        "edited": fr.edited,
        "source_cell": fr.source_cell,        # {"row": int, "col": int} or null
        "source_snippet": fr.source_snippet,  # string or null
    }
    for key, fr in fields.items()
}
```
Response also includes `raw_cells` array at the top level alongside `raw_text`.

### Frontend

**`review.html`**
- Source panel: `max-height: 150px` → `min-height: 250px; resize: vertical; overflow-y: auto`
- `<pre id="source-text">` → `<div id="source-table"></div>`
- Hallucination warning element: `<div id="source-warning" class="d-none alert alert-danger py-1 small mt-1">Value not found in source document — possible hallucination</div>`

**`app.js`**

`selectPatient()` renders `raw_cells` as an HTML table:
- Groups cells by row index
- Renders as `<table>` with `<tr>` per row and `<td data-row="r" data-col="c">` per cell
- Header rows (row 0, row 2, row 4, row 6 based on known structure) get a distinct background
- Deduplicates repeated cell text within the same row (col 1 often duplicates col 0)

`renderFieldTable()` adds `onclick="highlightSource(fr)"` to each `<tr>`.

`highlightSource(fr)`:
1. Clears all existing highlights: remove border/background from all `<td>`, clear all `<mark>` wrappers, hide `#source-warning`
2. If `fr.source_cell` is set:
   - Find `<td data-row="r" data-col="c">` matching `fr.source_cell`
   - Apply confidence-coloured border to that `<td>`
   - Wrap `fr.source_snippet` in `<mark>` using **textContent-based re-render** (not innerHTML string replace) to avoid XSS: read `td.textContent`, find the snippet by string index, reconstruct the cell as `textNode + markNode + textNode`
   - Scroll source panel to that `<td>`
3. If `fr.source_cell` is null and `fr.value` is not null: show `#source-warning` (possible hallucination)
4. If `fr.value` is null: do nothing (empty field)

`#source-warning` is auto-dismissed when `highlightSource()` is called for the next row.

### Highlight Colour Scheme

| Confidence | `<td>` border | `<mark>` background | Review badge colour |
|---|---|---|---|
| HIGH | `#198754` green | `rgba(25,135,84,0.3)` | Green |
| MEDIUM (INFERRED) | `#dc3545` red | `rgba(220,53,69,0.25)` | Red |
| LOW | `#dc3545` red (2px) | `rgba(220,53,69,0.35)` | Red |
| EMPTY / null | none | none | Grey |

---

## 2. Method-Based Confidence Levels

### Rationale
LLM self-reported confidence is unreliable. Confidence must reflect the extraction method.

### Rules

| Extraction method | Confidence |
|---|---|
| Regex match | `high` |
| LLM extracted (any self-reported level except low) | `medium` |
| LLM extracted, self-reported `low` | `low` |
| Not found | `none` |

### Implementation Location

The confidence cap is applied **in `extractor/response_parser.py`** only — specifically in `parse_llm_response()`, after the per-field confidence value is read from the LLM JSON. `response_parser.py` does not receive regex-filled results, so there is no risk of accidentally capping those.

Exact insertion point — in `parse_llm_response()`, after `confidence = field_data.get("confidence", "low")` is set and before it is stored in `FieldResult`:
```python
# Cap: LLM may not claim HIGH — only regex earns HIGH
if confidence == "high":
    confidence = "medium"
```
`_apply_confidence_overrides()` (which handles `none`-for-null and `low`-for-bad-date) runs after this cap and is unaffected. `app.py` applies no additional cap.

### UI Changes

- MEDIUM/INFERRED fields: badge colour changes from teal/blue to **red**
- Badge label text stays `INFERRED` (distinguishes from `LOW` label)
- Field input border: `border-info` → `border-danger` for MEDIUM fields
- Row background: `rgba(13,202,240,0.05)` → `rgba(220,53,69,0.05)` for MEDIUM
- **`_confidence_summary()` in `app.py` is NOT changed** — it continues returning `{"high": 0, "medium": 0, "low": 0}` as three separate keys. The sidebar in `app.js` continues rendering three separate badges. Only the badge CSS class for `medium` changes: `bg-warning text-dark` → `bg-danger` (red). No dict key renaming, no summing with `low`.

---

## 3. Live Review During Extraction

### Goal
User can navigate to `/review` while extraction is running. Sidebar populates as patients complete regex phase.

### State During Two-Phase Extraction

When Phase 1 (regex) completes for a patient, LLM groups are **pre-populated with `confidence='none'` stubs** for all their fields:
```python
patient.extractions[group_name] = {
    f['key']: FieldResult(value=None, confidence='none')
    for f in group['fields']
}
```
This means `patient.extractions` always has a complete dict structure for all groups, even for patients not yet LLM-processed. The review page never encounters a missing group key.

### New Route (`app.py`)
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

### Frontend Changes (`app.js`)

On review page load:
1. Call `GET /status`
2. If `status == 'extracting'`: open `EventSource('/progress')`, call `loadPatients()` on each SSE event that includes a newly completed patient ID
3. SSE is **page-scoped**: opened on load, closed when status becomes `complete` or `stopped`, or when the page is unloaded (`window.addEventListener('beforeunload', () => source.close())`)
4. If user navigates away and returns during extraction, step 1–3 repeat on the new page load

In `renderFieldTable()`: if a field has `confidence='none'` and `value=null`, render the row greyed-out with label `PENDING` instead of `EMPTY`.

---

## 4. Excel Round-Trip with Confidence + Reasoning

### Goal
Export preserves confidence + reasoning. Re-import restores full state. The Metadata sheet is written for **all exports going forward**. Files exported before this change (no Metadata sheet) fall back to `confidence='high'` for all fields — this is correct for legacy files.

### Export Changes (`export/excel_writer.py`)

Existing "Prototype V1" sheet: **unchanged**.

Add sheet `"Metadata"` immediately after writing the main sheet:
```python
ws_meta = wb.create_sheet("Metadata")
ws_meta.sheet_state = 'hidden'
ws_meta.append(["patient_id", "field_key", "confidence", "reason"])
for patient in patients:
    for group_name, fields in patient.extractions.items():
        for field_key, fr in fields.items():
            ws_meta.append([patient.id, field_key, fr.confidence or 'none', fr.reason or ''])
```

### Import Changes (`app.py` — `_import_excel`)

```python
# After loading workbook:
meta_lookup = {}  # {(patient_id, field_key): {"confidence": str, "reason": str}}
if "Metadata" in wb.sheetnames:
    ws_meta = wb["Metadata"]
    for row in ws_meta.iter_rows(min_row=2, values_only=True):
        pid, fkey, conf, reason = row
        meta_lookup[(pid, fkey)] = {"confidence": conf, "reason": reason or ""}

# When building FieldResult for each field:
meta = meta_lookup.get((patient_id, field['key']), {})
confidence = meta.get('confidence', 'high')  # legacy fallback
reason = meta.get('reason', '')
group_fields[field['key']] = FieldResult(value=value, confidence=confidence, reason=reason)
```

---

## 5. Two-Phase Extraction Pipeline

### Goal
Decouple instant regex from slow LLM. Review page usable within seconds. LLM requests serialised to match Ollama throughput.

### `session.progress` New Fields (`models.py` — also update `ExtractionSession`)

```python
progress: dict = field(default_factory=lambda: {
    # existing fields unchanged ...
    "phase": "idle",          # "regex" | "llm" | "complete"
    "regex_complete": 0,       # patients with regex done
    "llm_queue_size": 0,       # total LLM (patient, group) pairs
    "llm_complete": 0,         # LLM calls completed
})
```

### New `_run_extraction` Structure

```python
def _run_extraction(patient_limit=None, concurrency=1):
    import time, threading
    from concurrent.futures import ThreadPoolExecutor

    groups = get_groups()
    llm_groups = [g for g in groups if g.get('llm_required', False)]
    patients = session.patients[:patient_limit] if patient_limit else session.patients

    session.progress['total'] = len(patients)
    session.progress['phase'] = 'regex'

    # --- Phase 1: Regex sweep (fully parallel) ---
    _counter_lock = threading.Lock()

    def regex_phase(patient):
        if session.stop_requested:
            return
        session.progress['active_patients'][patient.id] = {
            "initials": patient.initials, "group": "Regex", "start": time.time()
        }
        for group in groups:
            results = regex_extract(patient.raw_text, group['name'], group['fields'], patient.raw_cells)
            # Pre-populate LLM groups with none-stubs so review page has complete structure
            if group.get('llm_required', False):
                for key, fr in results.items():
                    if fr.value is None:
                        results[key] = FieldResult(value=None, confidence='none')
            patient.extractions[group['name']] = results
        del session.progress['active_patients'][patient.id]
        with _counter_lock:
            session.progress['regex_complete'] = session.progress.get('regex_complete', 0) + 1

    with ThreadPoolExecutor(max_workers=min(len(patients), 16)) as ex:
        list(ex.map(regex_phase, patients))

    if session.stop_requested:
        session.status = 'stopped'
        return

    # --- Phase 2: LLM queue (semaphore-controlled) ---
    session.progress['phase'] = 'llm'
    llm_semaphore = threading.Semaphore(1)  # 1 concurrent LLM call (Ollama is serial)

    # Collect all (patient, group) pairs with gaps
    llm_tasks = [
        (patient, group)
        for patient in patients
        for group in llm_groups
        if any(fr.value is None for fr in patient.extractions.get(group['name'], {}).values())
    ]
    session.progress['llm_queue_size'] = len(llm_tasks)

    def llm_phase(task):
        patient, group = task
        if session.stop_requested:
            return
        session.progress['active_patients'][f"{patient.id}:{group['name']}"] = {
            "initials": patient.initials, "group": group['name'], "start": time.time()
        }
        with llm_semaphore:
            try:
                prompt = build_prompt(patient.raw_text, group)
                raw_response = generate(prompt)
                llm_results = parse_llm_response(raw_response, group)
                # Merge: LLM fills only empty fields
                for key, llm_fr in llm_results.items():
                    if patient.extractions[group['name']][key].value is None and llm_fr.value is not None:
                        # Resolve source_cell
                        _resolve_source_cell(patient, llm_fr)
                        llm_fr.reason = f"[LLM] {llm_fr.reason}"
                        patient.extractions[group['name']][key] = llm_fr
            except Exception:
                pass  # regex stubs remain
        del session.progress['active_patients'][f"{patient.id}:{group['name']}"]
        with _counter_lock:
            session.progress['llm_complete'] = session.progress.get('llm_complete', 0) + 1
            session.progress['current_patient'] = session.progress['llm_complete']

    # max_workers=2: one task runs (held by semaphore), one waits ready to start.
    # Prevents dead time between tasks. Effective concurrency is still 1 (semaphore-controlled).
    with ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(llm_phase, llm_tasks))

    session.status = 'complete' if not session.stop_requested else 'stopped'
    session.progress['phase'] = 'complete'
```

`_resolve_source_cell(patient, fr)`: helper that searches `patient.raw_cells` for a cell containing `fr.value` and sets `fr.source_cell` and `fr.source_snippet`.

**Connection pooling:** Module-level `_session = requests.Session()` in `llm_client.py`. All `requests.post()` calls replaced with `_session.post()`.

---

## 6. Bug Fixes

### 6a. Race Condition on Patient Counter
Addressed in the two-phase pipeline above: `_counter_lock` wraps all increments to shared counters. `current_patient` tracks LLM-complete count (Phase 2 completion = fully processed patient).

### 6b. Re-extract Uses Hybrid Pipeline
`_do_re_extract()` in `app.py`: call `regex_extract` first for each group, then LLM for gaps only — same hybrid logic as `process_single_patient`.

### 6c. Export Allowed After Stop
```python
if session.status not in ('complete', 'stopped'):
    return jsonify({"error": "No data to export"}), 400
```

### 6d. `llm_required` in Schema
`config/field_schema.yaml`: add `llm_required: true` to Endoscopy, Baseline CT, Surgery, Watch and Wait groups. All other groups omit the key (treated as `False` by callers via `.get('llm_required', False)`).

**`config/__init__.py` requires no code change** — `get_groups()` returns raw YAML dicts unchanged, so `llm_required` passes through automatically. Note: the schema is cached on first load (`_schema` module-level variable). After editing the YAML, the app must be restarted for the change to take effect.

---

## Files Touched

| File | Change |
|---|---|
| `models.py` | `raw_cells` on `PatientBlock`; `source_cell`, `source_snippet` on `FieldResult`; new `progress` keys on `ExtractionSession` |
| `parser/docx_parser.py` | Add `_table_to_cells()`; call in `parse_docx()` |
| `extractor/regex_extractor.py` | Return `(value, raw_match_span)` tuples; calling code stores `source_cell` + `source_snippet` |
| `extractor/response_parser.py` | Cap LLM `high` → `medium` here (single location) |
| `extractor/llm_client.py` | Module-level `requests.Session()` for connection pooling |
| `app.py` | Two-phase pipeline; `/status` route; export fix; re-extract fix; `_resolve_source_cell()` helper; Metadata sheet import; `source_cell`/`source_snippet` in `/patients/<id>` response |
| `export/excel_writer.py` | Add hidden Metadata sheet |
| `config/field_schema.yaml` | `llm_required: true` on LLM groups |
| `config/__init__.py` | No code change — `llm_required` already passes through unchanged |
| `templates/review.html` | `<div id="source-table">`; resize panel; `#source-warning` element |
| `static/js/app.js` | `highlightSource()` (textContent-based); SSE subscription on review page; PENDING state for stubs; `/status` check on load |
| `static/css/style.css` | MEDIUM → red; source panel resize; PENDING row style |

---

## Out of Scope

- `raw_cells` for Excel-imported patients (no docx available; source panel shows "Imported from Excel — no source document")
- Per-field re-extraction from the review UI
- Changing the main Excel sheet column layout
- Ollama concurrency > 1 (left as configurable but default 1)
