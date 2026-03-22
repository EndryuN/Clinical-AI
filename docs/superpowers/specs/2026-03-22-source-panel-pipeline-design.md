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
Show the original Word document table structure below the field table in the review page. When a field row is clicked, highlight the source cell (amber border) and the specific matched text within it (coloured mark). Colour reflects confidence level.

### Data Model Changes

**`models.py` — `PatientBlock`**
Add field:
```python
raw_cells: list = field(default_factory=list)
# Each item: {"row": int, "col": int, "text": str}
```
`raw_text` remains unchanged (used for LLM prompts, debug).

**`models.py` — `FieldResult`**
Add fields:
```python
source_cell: Optional[tuple] = None   # (row_index, col_index) into raw_cells
source_snippet: Optional[str] = None  # exact matched text within that cell
```

### Parser Changes (`parser/docx_parser.py`)

Add `_table_to_cells(table) -> list[dict]`:
- Iterates `table.rows[i].cells[j]`
- Returns `[{"row": i, "col": j, "text": cell.text.strip()}, ...]`
- Skips empty cells

`parse_docx()` calls both `_table_to_text()` (unchanged) and `_table_to_cells()`, stores result in `PatientBlock.raw_cells`.

### Regex Extractor Changes (`extractor/regex_extractor.py`)

After each regex match, find the source cell:
- Search `raw_cells` for the cell whose `text` contains the matched value
- Store `(row, col)` as `source_cell` and the matched string as `source_snippet` in the returned `FieldResult`
- If no cell found (should not happen for regex), leave both `None`

### LLM Extractor Changes (`extractor/response_parser.py` or merge step in `app.py`)

After LLM extraction, for each LLM-filled field:
- Substring-search `raw_cells` for the extracted value
- If found: set `source_cell` and `source_snippet`
- If not found: leave `source_cell = None` — this is a hallucination signal

### Backend (`app.py`)

`GET /patients/<id>` response adds `raw_cells` array. No new routes needed.

### Frontend

**`review.html`**
Source panel height increases from `max-height: 150px` to `min-height: 250px`, resizable via CSS `resize: vertical`.
`<pre id="source-text">` replaced with `<div id="source-table">` for HTML table rendering.

**`app.js`**

`selectPatient()`:
- Renders `raw_cells` as an HTML `<table>` in `#source-table`, mirroring the Word document layout (rows and columns preserved)
- Row header cells (col 0 of header rows) styled distinctly

`renderFieldTable()`:
- Each `<tr>` gets `onclick="highlightSource(fr)"` where `fr` contains `source_cell` and `source_snippet`

`highlightSource(fr)`:
- Clears all existing highlights from source table
- If `fr.source_cell` is set:
  - Adds confidence-coloured border to the target `<td>`
  - Wraps `source_snippet` text in `<mark>` within that cell using innerHTML replacement
  - Scrolls source panel to that cell
- If `fr.source_cell` is null:
  - Shows warning banner: "Value not found in source document — possible hallucination"

### Highlight Colour Scheme

| Confidence | Cell border | Text mark background | Label |
|---|---|---|---|
| HIGH | `#198754` (green) | `rgba(25,135,84,0.3)` | GREEN |
| MEDIUM | `#dc3545` (red) | `rgba(220,53,69,0.25)` | RED |
| LOW | `#dc3545` (red, darker border) | `rgba(220,53,69,0.35)` | RED |
| EMPTY / null | none | none | — |

---

## 2. Method-Based Confidence Levels

### Rationale
LLM self-reported confidence is unreliable — an LLM can claim HIGH for a hallucinated value. Confidence should reflect the extraction method.

### New Rules

| Extraction method | Confidence assigned |
|---|---|
| Regex match | `high` |
| Structural docx row/cell (known position) | `high` |
| LLM extracted | `medium` |
| LLM extracted, self-reported low | `low` |
| Not found by any method | `none` (empty) |

### Implementation

In `app.py` `_run_extraction`, after LLM merge step:
- Any field filled by LLM gets confidence capped at `medium` (overrides LLM self-report of `high`)
- If LLM self-reported `low`, keep `low`
- Regex-filled fields keep `high` (already set by regex extractor)

### UI Colour Changes

| Confidence | Current colour | New colour |
|---|---|---|
| HIGH | Green | Green (unchanged) |
| MEDIUM / INFERRED | Blue/teal | **Red** (same as LOW) |
| LOW | Red | Red (unchanged) |
| EMPTY | Grey | Grey (unchanged) |

MEDIUM label text stays `INFERRED` to distinguish from `LOW` label, but both render red. Review badges, field input borders, and source panel highlights all use this scheme.

---

## 3. Live Review During Extraction

### Goal
User can navigate to `/review` while extraction is running. The patient sidebar populates as patients complete. Patients with completed regex (but no LLM yet) are browsable immediately.

### How It Works

`session.patients` is fully populated at parse time — all `PatientBlock` objects exist before extraction begins. Their `extractions` dict grows as processing completes. The `/patients` and `/patients/<id>` routes already work during extraction; only the frontend needs updating.

### Frontend Changes (`app.js`)

In `selectPatient()` and `renderFieldTable()`:
- If a patient's extractions dict is empty or a group has no fields yet, show "Extracting..." placeholder in that tab
- Field rows show greyed-out state while not yet extracted

Patient sidebar refresh during extraction:
- Review page checks `session.status` via a new lightweight `GET /status` route
- If status is `extracting`, subscribes to `/progress` SSE
- On each SSE event containing a newly completed patient, calls `loadPatients()` to refresh sidebar
- SSE subscription closes when status becomes `complete` or `stopped`

### New Route (`app.py`)

```python
@app.route('/status')
def status():
    return jsonify({"status": session.status, "current": session.progress['current_patient'], "total": session.progress['total']})
```

---

## 4. Excel Round-Trip with Confidence + Reasoning

### Goal
Export preserves confidence levels and reasoning per field. Re-importing the Excel restores full session state identically to post-extraction state.

### Export Changes (`export/excel_writer.py`)

The existing "Prototype V1" sheet is **unchanged**.

Add a second sheet `"Metadata"` (hidden: `ws.sheet_state = 'hidden'`):

| Column | Content |
|---|---|
| A | `patient_id` |
| B | `field_key` |
| C | `confidence` (`high`/`medium`/`low`/`none`) |
| D | `reason` (string) |

One row per (patient × field). Written after the main sheet.

### Import Changes (`app.py` — `_import_excel`)

On re-import:
- Check if `"Metadata"` sheet exists in workbook
- If yes: build lookup `{(patient_id, field_key): {confidence, reason}}`
- Apply to each `FieldResult` after reading values from main sheet
- If no Metadata sheet: fall back to current behaviour (all fields get `confidence='high'`)

---

## 5. Two-Phase Extraction Pipeline

### Goal
Decouple instant regex work from slow LLM calls. Review page usable within seconds. LLM requests serialised to match Ollama's actual throughput (one at a time).

### New Pipeline in `_run_extraction`

**Phase 1 — Regex sweep (fully parallel):**
```
ThreadPoolExecutor(max_workers=len(patients))
  → regex_extract(patient, all_groups) for every patient
  → stores results in patient.extractions immediately
  → updates progress: "Regex complete: X/50"
```
All 50 patients get regex done in ~1 second. Review page is immediately browsable.

**Phase 2 — LLM queue (serialised):**
```
Collect (patient, group) pairs where gaps > 0 AND group in LLM_GROUPS
Queue → Semaphore(max_workers=1)  [configurable, default 1 for Ollama]
  → LLM call → merge result into patient.extractions
  → update progress per completed LLM call
```
LLM requests run one (or optionally two) at a time, matching Ollama capacity. No thread pile-up.

**Progress tracking:**
`session.progress` gains:
```python
"phase": "regex" | "llm" | "complete"
"regex_complete": int   # patients with regex done
"llm_queue_size": int   # total LLM calls remaining
"llm_complete": int     # LLM calls done
```
SSE stream includes these fields. Review page shows two progress indicators.

### Additional Optimisations

**Connection pooling (`extractor/llm_client.py`):**
Replace bare `requests.post()` calls with a module-level `requests.Session()`. Reuses TCP connections across LLM calls.

**Group-level parallelism within a patient:**
The LLM groups for one patient are independent. Within Phase 2, all 4 LLM groups for a given patient can submit concurrently — they still respect the global semaphore so only 1 runs at a time, but they don't wait for each other to start.

---

## 6. Bug Fixes

### 6a. Race Condition on Patient Counter
**File:** `app.py:298`
**Fix:** Add `_counter_lock = threading.Lock()` at module level. Wrap `session.progress['current_patient'] += 1` and the average calculation in `with _counter_lock`.

### 6b. Re-extract Uses Hybrid Pipeline
**File:** `app.py` — `_do_re_extract()`
**Fix:** Call `regex_extract` first, then LLM for gaps only — same logic as `process_single_patient`.

### 6c. Export Allowed After Stop
**File:** `app.py:452`
**Fix:** Change `if session.status != 'complete'` to `if session.status not in ('complete', 'stopped')`.

### 6d. LLM_GROUPS Moved to Schema
**File:** `config/field_schema.yaml` and `config/__init__.py`
**Fix:** Add `llm_required: true` flag to relevant groups in the YAML. `get_groups()` returns this flag. `_run_extraction` reads it from schema instead of hardcoded set.

---

## Files Touched

| File | Change |
|---|---|
| `models.py` | Add `raw_cells` to `PatientBlock`; add `source_cell`, `source_snippet` to `FieldResult` |
| `parser/docx_parser.py` | Add `_table_to_cells()`; call it in `parse_docx()` |
| `extractor/regex_extractor.py` | Store `source_cell` + `source_snippet` after each match |
| `extractor/response_parser.py` | Cap LLM confidence at `medium`; set `source_cell` via cell search |
| `extractor/llm_client.py` | Use `requests.Session()` for connection pooling |
| `app.py` | Two-phase pipeline; `/status` route; export fix; re-extract fix; race condition fix; Metadata sheet import |
| `export/excel_writer.py` | Add hidden Metadata sheet |
| `config/field_schema.yaml` | Add `llm_required: true` to LLM groups |
| `config/__init__.py` | Expose `llm_required` from `get_groups()` |
| `templates/review.html` | Replace `<pre>` with `<div>` for source table; resize panel |
| `static/js/app.js` | `highlightSource()`; live SSE subscription; "Extracting..." placeholders |
| `static/css/style.css` | MEDIUM/INFERRED → red; source panel resize |

---

## Out of Scope

- Storing raw_cells for Excel-imported patients (no docx available)
- Per-field re-extraction from the review UI
- Changing the main Excel sheet column layout
