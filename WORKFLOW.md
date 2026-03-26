# Clinical AI MDT Data Extractor -- Complete Workflow

This document traces every step of the application from launch to final export. It is the definitive operational reference for the system.

---

## 1. Application Launch

### Starting the Application

Two processes must be running:

```bash
ollama serve                    # Terminal 1 -- starts the local LLM server on port 11434
python app.py                   # Terminal 2 -- starts Flask on http://localhost:5000
```

An optional `--port` argument overrides the default Flask port:

```bash
python app.py --port 8080
```

### What the Console Shows

On startup, Flask runs in debug mode (`app.run(debug=True, port=port, threaded=True)`). A `QuietFilter` is attached to the werkzeug logger to suppress noisy polling endpoints (`/status`, `/progress`, `/backend`) from the console output. All other HTTP requests are logged normally.

A `.env` file at the project root is loaded before any imports. If `ANTHROPIC_API_KEY` is found, the default backend is set to `claude`; otherwise it defaults to `ollama`.

### Initial State of ExtractionSession

A single global `ExtractionSession` dataclass is instantiated at module level:

```python
session = ExtractionSession()
```

Its initial state:
- `file_name`: `""`
- `upload_time`: `""`
- `patients`: `[]` (empty list)
- `status`: `"idle"`
- `stop_requested`: `False`
- `concurrency`: `1`
- `progress`: dict with `current_patient=0`, `total=0`, `current_group=""`, `patient_times=[]`, `active_patients={}`, `phase="idle"`, `regex_complete=0`, `llm_queue_size=0`, `llm_complete=0`, `completed_patients=[]`

---

## 2. Landing Page (index.html)

**Route:** `GET /` renders `templates/index.html`.

The route passes these values to the template: `session_active` (whether patients are loaded), `current_backend`, `ollama_available`, `claude_available`, `ollama_models` (list of installed Ollama models), `suggested_models` (hardcoded list), and `current_ollama_model`.

### Backend Selection

Two radio buttons: **Claude API** and **Local LLM (Ollama)**.

- Each shows a status badge: "Ready" (green) if the backend is available, or "No API key" / "Not running" (grey) if unavailable.
- Claude is available when `ANTHROPIC_API_KEY` is set in the environment.
- Ollama is available when `GET http://localhost:11434/api/tags` returns 200 with at least one model.
- Changing backend calls `switchBackend()` which POSTs to `/backend` with `{backend: "claude"|"ollama"}`. The server calls `set_backend()` in `llm_client.py`.

### Model Picker

The Ollama model selector appears only when the Ollama backend is selected. It contains:
- **Installed Models** optgroup: models returned by `list_ollama_models()` (via `GET /api/tags` on Ollama).
- **Suggested Models** optgroup: the hardcoded `SUGGESTED_MODELS` list (`qwen2.5:14b-instruct`, `qwen3:8b`, `qwen3.5:4b`, `llama3.1:8b`, `llama3.2:3b`). Models already installed are excluded from this group.
- Uninstalled suggestions show "(not pulled)" in the option text.
- Changing the model calls `switchModel()` which POSTs to `/backend` with `{backend: "ollama", ollama_model: modelName}`.

### File Upload Zone

A dashed-border drop zone accepts click or drag-and-drop:
- Accepted file types: `.docx` and `.xlsx` (enforced both by the `accept` attribute on the hidden file input and by client-side validation in `uploadFile()`).
- A spinner appears during upload with "Parsing document..." text.
- Privacy notice: "All processing happens locally -- no data leaves your machine."

---

## 3. DOCX Upload Flow

### Client Side (app.js `uploadFile()`)

1. User drops or selects a `.docx` file.
2. Client-side validation rejects anything not `.docx` or `.xlsx`.
3. A `FormData` with the file is POSTed to `/upload`.
4. On success, the response is saved to `sessionStorage` and the browser redirects to `/process`.
5. On `.xlsx` upload, the redirect goes straight to `/review` (imported data needs no extraction).

### Server Side (app.py `POST /upload`)

1. **Cleanup**: Old uploads matching `*_*.*` in `data/` are deleted.
2. **Save**: The file is saved as `{unix_timestamp}_{original_filename}` in `data/`.
3. **Session update**: `session.file_name` and `session.upload_time` are set.

#### DOCX Parsing Path

4. `session.status` is set to `"parsing"`.
5. `parse_docx(file_path)` is called from `parser/docx_parser.py`.

### How Patients Are Detected and Split (parse_docx)

The Word document contains one table per patient. Each table has a consistent **8-row x 3-column** structure:

| Row | Content |
|-----|---------|
| 0 | Section headers: "Patient Details", "Cancer Target Dates" |
| 1 | Patient demographics: hospital number, NHS number, name, gender, DOB |
| 2 | Staging/diagnosis header |
| 3 | Diagnosis + staging detail |
| 4 | Clinical details header |
| 5 | Clinical details free text |
| 6 | MDT outcome header |
| 7 | MDT outcome free text |

**Splitting strategy:** `doc.tables` is iterated. Each table with >= 2 rows becomes one `PatientBlock`. Tables with fewer than 2 rows are skipped.

### MDT Header Extraction

Before iterating tables, `_extract_mdt_headers(doc)` scans all document paragraphs for patterns like:

```
Colorectal Multidisciplinary Meeting 07/03/2025(i)
```

This extracts a list of `{cancer_type, date}` dicts, one per patient. The nth header is matched to the nth table by index.

### Per-Patient Processing

For each table:

1. **Details cell**: Row 1, cell 0 is cleaned (annotation markers removed).
2. **Name extraction** (`_extract_name`): Three strategies tried in order:
   - Explicit `Name: <value>` prefix.
   - All-uppercase line (filtering out medical keywords like "DAY", "TARGET", "STAGING").
   - Third non-empty line (after Hospital Number and NHS Number lines, sanity-checked for no digits).
3. **Initials** (`_initials`): Name split on spaces/apostrophes/hyphens, first character of each part uppercased and joined.
4. **NHS number** (`_extract_nhs`): Regex `NHS Number:\s*(...)`, digits extracted.
5. **Gender** (`_extract_gender`): Regex for "Male" or "Female".
6. **Hospital number**: Used as the stable `id`. Falls back to `PATIENT_{idx+1:03d}`.
7. **raw_text** (`_table_to_text`): Flattens the table. Only columns 0 and 2 are used (column 1 is typically a duplicate). Deduplication is by exact text match.
8. **raw_cells** (`_table_to_cells`): All cells with stable `{row, col, text}` coordinates.

### Annotation Markers

The document uses markers to identify data sections:
- `(a)` = DOB
- `(b)` = Name
- `(c)` = NHS number
- `(d)` = MRN (Hospital Number)
- `(e)` = Gender
- `(f)` = Clinical Details
- `(g)` = Staging/Histology
- `(h)` = MDT Outcome
- `(i)` = MDT date

The `_clean()` function strips these markers from cell text. They remain in `raw_text` for LLM section targeting.

### Cell Deduplication from Word Merged Cells

`_table_to_cells()` uses two deduplication strategies:

1. **XML element identity**: Python-docx merged cells share the same `_tc` element. Cells whose `id(cell._tc)` has already been seen in the same row are skipped.
2. **Adjacent text comparison**: If the current cell's text is identical to the previous cell's text in the same row, it is skipped (handles cases where Word copies content without a true XML merge).

Column indices are renumbered sequentially after deduplication.

### MDT Date and Cancer Type Injection

If an MDT header was found for this patient:
- A prefix `Cancer Type: {type}\nMDT Meeting Date: {date}` is prepended to `raw_text`.
- A synthetic cell at `row=-1, col=0` is inserted at the start of `raw_cells` with this prefix text. This allows `source_cell` tracking to locate the MDT date.

### Gender and MDT Date at Parse Time

`PatientBlock` fields `gender`, `mdt_date`, and `initials` are populated during parsing (before extraction). These are used later by `assign_unique_id()`.

### Preview Rendering

After parsing, `render_patient_preview(p, preview_dir)` is called for each patient. This generates PNG images and JSON coordinate maps in `static/previews/{timestamp}/`. The preview renderer (`extractor/preview_renderer.py`) uses Pillow to create a 6-section layout image. If Pillow is unavailable, the error is logged but does not block the flow.

### Upload Response

```json
{
  "status": "ok",
  "patients_detected": 50,
  "imported": false,
  "patient_list": [{"id": "...", "unique_id": "", "initials": "AO", "nhs_number": "1234567890"}, ...]
}
```

`session.status` is set to `"parsed"`.

---

## 4. Extraction Process (process.html)

**Route:** `GET /process` renders `templates/process.html`.

### Process Page Layout

The page has three sections (only one visible at a time):

1. **Parse result section**: Shows file name, patient count, model name, and extraction controls.
2. **Progress section** (hidden initially): Live extraction progress with progress bar, active patients, completed log.
3. **Complete section** (hidden initially): Success message with links to Review and Export.

### Setting Concurrency and Patient Limit

- **Patients to process**: Optional numeric input. If blank, all patients are processed.
- **Parallel processes**: 1-3 (max enforced at 5 in the HTML, capped at 3 in the backend via `max(1, min(concurrency, 3))`).

### Auto-Init

When the page loads, `initProcessPage()` runs:
1. Fetches `/backend` to display the current model name.
2. Fetches `/status` -- if extraction is already running (user navigated away and back), it skips the parse-result view and resumes the live progress view.
3. Otherwise, reads `sessionStorage` for file name and patient count.

### Starting Extraction

Clicking "Start Extraction" calls `startExtraction()`:
1. Hides the parse-result section, shows the progress section.
2. POSTs to `/extract` with `{limit: N|null, concurrency: N}`.
3. On success, calls `listenProgress()`.

### POST /extract (Server Side)

1. Validates session status is `"parsed"` or `"complete"`.
2. Sets `session.status = "extracting"`, `session.stop_requested = False`, `session.concurrency = concurrency`.
3. Spawns a daemon thread running `_run_extraction(patient_limit, concurrency)`.
4. Returns `{"status": "started"}` immediately.

### _run_extraction (Background Thread)

This is the core extraction orchestrator. It runs in a background thread.

#### Initialization

1. Wires up the stop-check callback via `set_stop_check()` so LLM calls can abort mid-generation.
2. Loads all schema groups and filters for `llm_required` groups.
3. Slices `session.patients` by `patient_limit` if set.
4. Initializes progress tracking: total count, phase, timing, active/completed patient lists.
5. Prints to console: `=== Extraction started: N patients, model=X, concurrency=Y ===`

#### ThreadPoolExecutor

A `ThreadPoolExecutor(max_workers=max(1, min(concurrency, 3)))` processes patients in parallel. A `threading.Semaphore(concurrency)` gates LLM calls so at most `concurrency` patients run LLM at once. A `threading.Lock` protects counter updates.

#### Per-Patient Processing (`process_patient`)

Each patient goes through two stages:

##### Stage 1: Regex Extraction (Inline, Fast)

For every group in the schema (all 18), `regex_extract()` is called:

```python
results = regex_extract(patient.raw_text, group['name'], group['fields'], patient.raw_cells)
```

**How regex_extract works:**

1. A dispatch table maps group names to private extractor functions (`_extract_demographics`, `_extract_endoscopy`, `_extract_histology`, `_extract_baseline_mri`, `_extract_baseline_ct`, `_extract_mdt`, `_extract_chemotherapy`, `_extract_immunotherapy`, `_extract_radiotherapy`, `_extract_cea`, `_extract_surgery`, `_extract_second_mri`, `_extract_12week_mri`, `_extract_flexsig`, `_extract_watch_wait`, `_extract_ww_dates`).
2. Groups without an extractor get all fields set to `absent`.
3. Each extractor returns `dict[str, tuple[str, str]]` where each value is `(normalised_value, raw_match_span)`.

**What each group extractor does:**

| Group | Extraction Logic |
|-------|-----------------|
| Demographics | DOB from `(a)` marker, name/initials from `(b)` marker or all-caps line, MRN from Hospital Number, NHS number from NHS Number, gender from Male/Female, previous cancer from keyword search |
| Endoscopy | Date from colonoscopy/flexi sig mentions, findings from text after procedure name, type from explicit "flexi sig" or "incomplete colonoscopy" |
| Histology | Biopsy result from Diagnosis line or "Histo:" mentions, biopsy date, MMR status |
| Baseline MRI | MRI date, T/N staging from MRI text block, EMVI, CRM, PSW. Also checks Staging section |
| Baseline CT | CT date, T/N/M staging, EMVI, incidental findings, M staging inference from metastases text |
| MDT | MDT meeting date from prepended header, treatment from "Outcome:" text, 6-week/12-week MDT dates from subsequent MDT date mentions |
| Chemotherapy | Drug names (capecitabine, oxaliplatin, FOLFOX, etc.), goals (palliative/curative), cycle count |
| Immunotherapy | Drug names (pembrolizumab, nivolumab, etc.) |
| Radiotherapy | Total dose in Gy, concomitant chemo |
| CEA and Clinical | CEA numeric value |
| Surgery | Surgery date, defunctioning/stoma status. Surgery intent is left for LLM |
| Second MRI | Finds second MRI mention (index 1 in list of MRI dates), extracts T/N/EMVI/CRM/PSW/TRG |
| 12-Week MRI | Looks for "12 week" or "third" MRI, extracts same fields as Second MRI |
| Follow-up Flex Sig | Flexi sig date and findings |
| Watch and Wait | W&W entry date, frequency. W&W reasoning left for LLM |
| Watch and Wait Dates | Repeated flexi sig and MRI dates in W&W context |

**How source_cell is set:**

For each extracted value with a non-empty `raw_span`, the extractor iterates `raw_cells` looking for a cell whose text contains the `raw_span` substring. The first match becomes `source_cell = {row, col}` and `source_snippet = raw_span[:200]`.

**How confidence_basis is determined:**

After finding the source cell:
- If `source_cell.row` is in `_FREEFORM_ROWS` (4, 5, 6, 7): `"freeform_verbatim"`
- Otherwise: `"structured_verbatim"`
- If no source cell found: defaults to `"structured_verbatim"` (assumes structured origin)

For `llm_required` groups, any field with `value=None` after regex is explicitly set to `FieldResult(value=None, confidence_basis='absent')`.

The regex-complete counter is incremented under lock.

##### Stage 2: LLM Extraction (Only for llm_required Groups with Gaps)

**Which groups trigger LLM:**

Groups with `llm_required: true` in the schema: **Endoscopy**, **Baseline CT**, **Surgery**, **Watch and Wait**.

LLM is skipped for a group if:
1. All fields in that group already have values from regex (no gaps).
2. The relevant text section has fewer than 20 characters of actual content (after stripping headers/markers).

**Relevant text extraction (`_extract_relevant_text`):**

Not the full patient document. The `_GROUP_SECTIONS` mapping determines which annotation-marked sections are included:

| Group | Sections Included |
|-------|------------------|
| Endoscopy | (f) Clinical Details |
| Baseline CT | (h) MDT Outcome |
| Surgery | (h) MDT Outcome |
| Watch and Wait | (h) MDT Outcome, (f) Clinical Details |

The Cancer Type + MDT Meeting Date header is always prepended.

**Per-group prompt files (config/prompts/):**

| File | Group |
|------|-------|
| `system_base.txt` | All groups (base system instructions) |
| `endoscopy.txt` | Endoscopy (type classification rules + few-shot example) |
| `baseline_ct.txt` | Baseline CT |
| `surgery.txt` | Surgery (surgery types, intent classification) |
| `watch_and_wait.txt` | Watch and Wait (W&W entry criteria) |

**Prompt construction (`build_prompt`):**

The system prompt is assembled from:
1. `system_base.txt` -- base rules (return JSON only, use DD/MM/YYYY, copy verbatim, etc.)
2. Group-specific prompt file -- group instructions + clinical reference + few-shot example
3. If no group file exists, `get_context_for_group()` provides clinical definitions
4. JSON format specification showing expected field keys

The user prompt contains:
1. Field list with descriptions, prompt hints, and allowed values from overrides
2. The relevant patient text section (not full document)

**Clinical context injection (G049 + Radiopaedia):**

The `extractor/clinical_context.py` module provides RCPath G049 definitions:

| Group | Context Injected |
|-------|-----------------|
| Histology | MMR (Proficient/Deficient definitions) |
| Baseline MRI | T staging (mrT1-T4b with substages), N staging (mrN0-N2b with criteria), EMVI, CRM, Stage groupings |
| Baseline CT | T staging, N staging, M staging (M0-M1c), EMVI, Stage groupings |
| Second MRI | TRG (0-3), EMVI, CRM |
| 12-Week MRI | TRG, EMVI, CRM |
| Endoscopy | Endoscopy type classification rules |
| Surgery | Surgery types (APR, LAR, etc.) and intent classification |
| Watch and Wait | W&W entry criteria and reasoning |

**Abbreviation dictionary:**

A shared abbreviation block is injected into all LLM prompts:
```
CRT=chemoradiotherapy, TNT=total neoadjuvant therapy, SCRT=short-course radiotherapy,
LCCRT=long-course chemoradiotherapy, APR=abdominoperineal resection, ...
```

**Field overrides (allowed values):**

For each field, `get_field_override()` checks `config/field_overrides.yaml`. If allowed values are defined, they are appended to the field hint:
```
MUST be one of: Positive, Negative, or null.
```

**Ollama API call:**

`_generate_ollama()` in `llm_client.py`:

1. Builds a messages array with system + user prompts.
2. Sets model-aware parameters:
   - `format: "json"` -- enforces JSON output
   - `think: false` -- only for qwen3+ / qwen3.5+ models (breaks JSON on qwen2.5)
   - `num_ctx: 16384` for 14B+ models, `8192` for smaller
   - `temperature: 0.1` + `seed: 42` for reproducibility
3. Uses streaming (`stream: True`) so the stop-check callback can abort mid-generation.
4. Connection timeout: 30s. Read timeout: 180s for large models, 30s for small.
5. Each chunk is accumulated. The stop-check is evaluated after each chunk.

**Claude API call:**

`_generate_claude()` uses the Anthropic Messages API with `claude-haiku-4-5-20251001`, `max_tokens: 4096`, `temperature: 0`. Non-streaming. Timeout: 30s.

**Response parsing (`parse_llm_response`):**

1. `_extract_json()` strips `<think>...</think>` blocks (qwen3 thinking mode), then tries:
   - Direct JSON parse
   - Code fence extraction (`\`\`\`json...`)
   - Regex for any `{...}` block
2. For each expected field key:
   - Extracts `value`, `reason`, `source_section` from the JSON
   - Normalizes null-like values ("null", "none", "n/a", "missing", "") to `None`
   - Spell-checks text-type fields using pyspellchecker with a medical dictionary
3. **Verbatim check** determines `confidence_basis`:
   - Default: `"freeform_inferred"` (LLM guessed)
   - Tries to find `source_snippet` (from LLM's `source_section` or quoted text in `reason`) in freeform cells (rows 4-7). Case-insensitive substring match.
   - If found: upgraded to `"freeform_verbatim"` with `source_cell` set.
   - If `source_snippet` does not match, tries the `value` itself in freeform cells.
   - `source_snippet` is capped at 200 characters.

**Merging LLM results with regex results:**

Only fields where the regex left `value=None` and LLM produced a non-null value are updated. The LLM result is merged:
- `_resolve_source_cell()` searches freeform cells (rows 4-7) for a cell containing the value, setting `source_cell` and `source_snippet`.
- The reason is prefixed with `"[LLM] "`.
- The field in `patient.extractions[group_name]` is replaced.

**Active patient tracking:**

While processing, each patient's status is tracked in `session.progress['active_patients']`:
- `initials`, `group` (current group being processed), `start` (wall clock), `llm_start` (when semaphore acquired), `status` ("queued" or "running"), `has_context` (whether clinical context is injected), `groups_done`, `groups_total`.

#### Post-Processing

After all patients complete (or stop is requested):

1. **assign_unique_id**: For each patient without a `unique_id`:
   - Format: `{DDMMYYYY}_{initials}_{M/F/U}_{disambiguator}`
   - Disambiguator priority: MRN (preferred) > NHS last 4 digits > zero-padded row index
   - Gender is read from Demographics extraction results

2. **compute_coverage**: For each patient, the coverage module computes what percentage of source document characters were matched by extracted fields:
   - All content cells are included (rows not in `_HEADER_ROWS` = {0, 2, 4, 6})
   - `structured_verbatim` and `freeform_verbatim` fields mark character ranges as "used"
   - `freeform_inferred` fields are counted separately (they do not appear in source text)
   - Per-cell coverage spans are stored in `patient.coverage_map` as `{"{row},{col}": [{start, end, used}, ...]}`
   - Stats: `used_pct`, `unused_pct`, `inferred_fields`, `total_chars`

3. **_deduplicate_unique_ids**: Ensures uniqueness within the batch. Collisions get `_b`, `_c`, `_d`... suffixes.

4. **_save_benchmark**: Saves results to `data/benchmarks.xlsx` (see Section 11).

5. `session.status` is set to `"complete"` (or `"stopped"` if abort was requested).

6. Console output: `=== Extraction COMPLETE: N/N patients in Xs (avg Ys/patient) ===`

### SSE Progress Streaming (GET /progress)

The `/progress` endpoint returns a Server-Sent Events stream. Every 2 seconds it emits a JSON event containing:
- `current_patient`, `total`, `phase`, `regex_complete`, `llm_complete`, `llm_queue_size`
- `active_patients`: dict of currently-processing patients with group, timing, context info
- `completed_patients`: list of finished patients with confidence summaries and timing
- `average_seconds`, `throughput_seconds`, `start_time`, `status`

The stream terminates when `session.status` is `"complete"` or `"stopped"`.

### Console Reporting Per Patient

Each completed patient prints:
```
  [3/50] AO -- 5H 2M 1L -- 12.3s
```
Showing position, initials, high/medium/low confidence counts, and LLM processing time. Slow groups (>120s) get a warning.

### Active Processing Row Display

The frontend renders each active patient as a card showing:
- Patient initials
- Current group name (or "Queued")
- Clinical context badge ("ctx") if context is injected
- Group progress: segmented bar (green=done, blue=active, grey=pending)
- Per-patient timer (grey when queued, amber when running)

### Stop Button

The stop button calls `POST /stop` which sets `session.stop_requested = True`. The streaming LLM client checks this flag after each chunk and aborts. The extraction loop checks it between patients and between groups. The frontend shows "Stopping..." immediately and waits for SSE confirmation.

---

## 5. Review Page (review.html)

**Route:** `GET /review` renders `templates/review.html`.

The layout is a full-height flex container with three main areas:

### Patient Sidebar (Left, 200px)

**Fixed controls:**
- **Search input**: Filters patients by initials or NHS number (calls `loadPatients({search: value})`).
- **Cancer type dropdown**: Populated dynamically from patient data. Filters by extracted cancer type.

**Scrollable patient list:**
- Each patient card shows: initials, gender, NHS number (or "MISSING NHS NUMBER" in red), cancer type, and confidence badges (high/medium/low counts with green/orange/red backgrounds).
- Active patient is highlighted with a blue left border.

**Patient loading (`loadPatients`):**
- Fetches `GET /patients?cancer_type=X&search=Y`.
- The server filters patients. During extraction, only patients whose LLM is complete are exposed.
- Each patient includes `id`, `unique_id`, `initials`, `nhs_number`, `gender`, `cancer_type`, `confidence_summary`, `coverage_pct`.
- Cancer type is extracted by `_get_cancer_type()`: first from Diagnosis line in raw_text, then from raw_cells, then from biopsy_result, finally "Pending Diagnosis".

### Group Tabs (Top Bar)

**18 groups** arranged horizontally with colour-coded tab backgrounds:

| Excel Colour | Dark UI Colour | Groups |
|-------------|----------------|--------|
| Grey #F2F2F2 | Slate #8A8FA0 | Demographics, MDT, Second MRI, MDT 6-Week, 12-Week MRI, Follow-up Flex Sig, MDT 12-Week |
| Peach #FCD5B4 | Warm Orange #D48A4A | Endoscopy |
| Light Blue #D6E4F0 | Stronger Blue #4A90C4 | Baseline MRI, Baseline CT, Surgery, Watch and Wait Dates |
| Green #E2EFDA | Stronger Green #5AAF5E | Histology, Chemotherapy, Immunotherapy, Radiotherapy, CEA and Clinical, Watch and Wait |

Tabs are sorted: groups with data first, then a "No data ->" divider, then empty groups (at reduced opacity 0.4).

A confidence filter dropdown allows filtering: All, Low Only, Medium + Low, Inferred Only, High Only.

### Field Table (Left 50%)

Each field row shows:
- **Field description**: From `excel_header`, with the group prefix stripped.
- **Value**: Inline editable text input, border-coloured by confidence (green/orange/red/grey).
- **Confidence badge**: HIGH (green), INFERRED (orange), LOW (red), EMPTY (grey), PENDING (grey italic), N/A (grey).
- **Context badge** ("ctx"): Purple badge shown when the LLM reason contains `[REF]` or `[G049]`, indicating clinical reference was used.
- **Source badge** ("src"): Clickable badge showing source cell coordinates. "no src" if source cell is unavailable.
- **Edited badge**: Blue "EDITED" badge if the field was manually changed.
- **Reason row**: Below the main row, showing the LLM's reasoning in italic grey text.

The entire row is clickable to trigger source highlighting.

### Source Document Preview (Right 50%)

**Route:** `GET /patient/{id}/preview` returns HTML preview + coverage data.

The preview is rendered by `render_html_preview()` in `extractor/html_preview.py`. It produces an interactive HTML document (not an image) with selectable text.

#### 6-Section Layout

1. **Meeting Date**: Full-width banner showing "MDT Meeting: DD/MM/YYYY" on dark blue background.
2. **Patient Details | Cancer Target Dates**: Two-column row. Patient details show initials instead of full name (privacy). Cancer target dates from cell (0,1).
3. **Staging & Diagnosis(g)**: Diagnosis and staging data from rows 2-3.
4. **Clinical Details(f)**: Free text from rows 4-5 (header row skipped).
5. **MDT Outcome(h)**: Free text from rows 6-7 (header row skipped).

Each section has:
- Blue section headers (`background: #375a82`)
- Content cells with `data-row` and `data-col` attributes for source tracking
- `data-group` attributes for group colouring (CSS borders)

#### Coverage Spans

Each content cell's text is wrapped in `<span>` tags with classes:
- `cov-used`: Text matched by an extracted field (green highlight when visible)
- `cov-unused`: Text not matched by any field (amber highlight when visible)

These spans are invisible by default. The "show-coverage" CSS class on the document root toggles visibility.

#### Group Colouring

Cells with extracted data get `data-group` attributes. CSS rules apply left borders:
- Grey (#B0B0B0) for Demographics, MDT, etc.
- Orange (#D48A4A) for Endoscopy
- Green (#70AD47) for Histology, Chemo, etc.
- Blue (#4A90C4) for Baseline MRI/CT, Surgery

#### Privacy

The preview replaces the patient's full name with their initials. Lines in the patient details cell that are not labeled (no colon, not numeric, not "Male"/"Female") are replaced with `patient.initials`.

### Field Highlighting on Click

When a field row is clicked, `highlightSource(fr)` is called:

1. **Clear previous highlights**: Removes `cell-highlighted` classes and `text-match` spans.
2. **Determine target cells**: Uses the `MARKER_TO_ROWS` mapping to translate source_snippet annotation markers to row indices:
   - `(a)-(e)` -> row 1 (patient details)
   - `(f)` -> rows 4, 5 (clinical details)
   - `(g)` -> rows 2, 3 (staging)
   - `(h)` -> rows 6, 7 (MDT outcome)
   - `(i)` -> row 0 (meeting date)
3. **Cell-level highlight**: Adds `cell-highlighted hl-{confidence}` classes (green/orange/red outline + background tint).
4. **Text-level match**: Uses the DOM Range API to highlight the specific source_snippet text within the cell. A TreeWalker traverses text nodes to find the exact character range, then wraps it in a `<span class="text-match hl-{confidence}">`.
5. **Source warning**: If no matching cell is found and the field has a non-structured value, a red alert appears: "Value not found in source document -- possible hallucination."
6. **Auto-scroll**: The highlighted cell is scrolled into view.

### Coverage Toggle

Below the preview:
- **"Highlight unused" button**: Toggles the `.show-coverage` class on the preview document, making coverage spans visible.
- **Three stat badges**:
  - Green: `X% extracted` (percentage of source text matched by fields)
  - Red: `N inferred` (number of fields inferred by LLM, not found in source)
  - Grey: `X% unused` (percentage of source text not matched by any field)

### Field Editing

Each field value is an inline `<input>` element. On change:
1. `editField(group, field, newValue)` sends `PUT /patients/{id}/fields` with `{group, field, value}`.
2. Server side: `fr.original_value` is saved (if first edit), `fr.value` is updated, `fr.edited = True`, `fr.confidence_basis = "edited"`.
3. An audit log entry is created.
4. Client side: local cache is updated, confidence changes to "high" (edited values are trusted), tabs are re-sorted.

### Source Document Linking (Drop Zone for .docx)

When viewing an imported Excel session (no original DOCX), the preview shows a drop zone:
- Click or drag a `.docx` file onto the drop zone.
- `linkSourceFile()` POSTs to `/link-source`.
- Server parses the DOCX, matches patients by: (1) Hospital Number, (2) NHS Number, (3) Initials (only if exactly one candidate).
- Matched patients get their `raw_cells` and `raw_text` replaced with data from the linked DOCX.
- Preview PNGs are re-rendered for all patients with raw_cells.
- Success message shows how many patients were matched.

### Live Review During Extraction

If the review page is opened while extraction is running:
- `initLiveReview()` checks `/status`.
- If extracting: Attaches an SSE listener to `/progress`. Each time a new patient completes, `loadPatients()` is called to add them to the sidebar.
- If parsed (not yet started): Polls `/status` every 3 seconds until extraction begins, then attaches SSE.

---

## 6. Excel Export

**Route:** `GET /export` triggers `write_excel()` and sends `mdt_extraction.xlsx`.

### 3-Sheet Structure

#### Sheet 1: Prototype V1 (Visible)

- **Column 1**: `unique_id` (format: `DDMMYYYY_XX_G_disambiguator`)
- **Columns 2-89**: 88 field columns, each at `excel_column + OFFSET` (OFFSET=1 because unique_id takes column 1)
- **Header row**: Field headers from `excel_header` in the schema, colour-coded by group colour, bold, wrapped text
- **Data rows**: One per patient. Each cell is colour-coded by `confidence_basis`:

| Basis | Fill | Font |
|-------|------|------|
| `structured_verbatim` | Green (#C6EFCE) | Normal |
| `freeform_verbatim` | Orange (#FFEB9C) | Italic, colour #9C6500 |
| `freeform_inferred` | Red (#FFC7CE) | Normal, colour #9C0006 |
| `edited` | Grey (#D9D9D9) | Normal |
| `absent` | No fill | Normal |

- Date fields get `DD/MM/YYYY` number format.
- Edited cells get a comment: "Original: {original_value}".
- A legend at the bottom explains the colour coding.

#### Sheet 2: Metadata (Hidden)

- **Row 1**: `["SOURCE_FILE", filename]`
- **Row 2**: Column headers (read by name on import, position-independent):
  `unique_id, field_key, confidence_basis, reason, source_cell_row, source_cell_col, source_snippet, edited, original_value, coverage_pct`
- **Row 3+**: One row per patient-field combination (all 88 fields x all patients).
- `source_snippet` is capped at 200 characters.

#### Sheet 3: RawCells (Hidden)

- Headers: `unique_id, row, col, text, coverage_json`
- One row per cell per patient. `coverage_json` contains the serialized coverage spans for that cell.
- This sheet enables preview regeneration on import without the original DOCX.

---

## 7. Excel Import (Round-Trip)

**Route:** `POST /upload` with `.xlsx` file triggers `_import_excel()`.

### Format Detection

The importer supports two formats:
- **New format**: Has `RawCells` sheet + `confidence_basis` column in Metadata. Detected by checking `"RawCells" in wb.sheetnames` and `'confidence_basis' in header_row`.
- **Legacy format**: Has `confidence` column only (maps via `_LEGACY_MAP`):
  - `high` -> `structured_verbatim`
  - `medium` -> `freeform_verbatim`
  - `low` -> `freeform_inferred`
  - `none` -> `absent`

### Metadata Reading (by Header Name)

The `_col_first()` helper uses `is not None` (not falsy check) because column index 0 is valid but falsy. Columns are found by name, not position, making the format forward-compatible.

For each metadata row, the importer reads: `unique_id`, `field_key`, `confidence_basis`, `reason`, `source_cell` (either separate row/col columns or legacy JSON), `source_snippet`, `edited`, `original_value`, `coverage_pct`.

### RawCells Restore

If the `RawCells` sheet exists:
- Each row is restored as `{row, col, text}` in `rawcells_lookup[unique_id]`.
- Coverage JSON is parsed back into `coverage_map_lookup[unique_id]`.

### Patient Reconstruction

For each data row in "Prototype V1":
- MRN, NHS number, and unique_id are read to identify the patient.
- Rows without any identifier (no MRN, no NHS, no valid unique_id) are skipped.
- For each group/field, the cell value and metadata are combined into `FieldResult` objects.
- A `PatientBlock` is created with `raw_text = "(imported from Excel)"`.

### Initials Recovery (6DT Bug Fix)

If initials contain digits (e.g., from "62 DAY TARGET" being misidentified as a name), the importer re-extracts the name from raw_cells:
1. Finds the patient details cell (row 1, col 0).
2. Calls `_extract_name()` and `_initials()` from the parser.

### Cancer Type from raw_cells

`_get_cancer_type()` searches raw_cells for `Diagnosis:` patterns when `raw_text` is the placeholder string `"(imported from Excel)"`.

### Preview Regeneration

If RawCells are available, preview PNGs are regenerated from raw_cells data (no DOCX needed). `render_patient_preview()` is called for each patient with raw_cells.

### Import Response

```json
{
  "status": "ok",
  "patients_detected": 50,
  "imported": true,
  "patient_list": [...]
}
```

`session.status` is set to `"complete"`. The client redirects to `/review` (skipping extraction entirely).

---

## 8. Consultation Excel

### Export (GET /export/consultation)

Generates `field_consultation.xlsx` using `write_consultation_excel()`:

#### Layout

| Column | Content |
|--------|---------|
| A | Field Key |
| B | Field Header (human-readable) |
| C | Group name |
| D | Current Type (from schema or overrides) |
| E | Current Allowed Values (from overrides) |
| F | All Unique Values Found (across all patients) |
| G | LLM Suggested Type (auto-detected: date, number, dropdown, boolean, text) |
| H | LLM Suggested Values (normalised: Positive/Negative, Male/Female, etc.) |
| I+ | One column per patient (header = initials), showing extracted value |
| Last 2 | Doctor's Type, Doctor's Values (green fill, blank for doctor to fill) |

- Cells with no value show "VALUE NOT FOUND" in red fill + red font.
- Header row: blue fill (#4472C4) with white font. Doctor columns: green fill (#E2EFDA).
- First row + first 2 columns are frozen (`freeze_panes = 'C2'`).

**Type suggestion logic (`_suggest_type`):**
- All dates -> `date`
- All numeric -> `number`
- 6 or fewer unique values -> `dropdown`
- Yes/No variants -> `boolean`
- Otherwise -> `text`

**Value suggestion logic (`_suggest_values`):**
- Normalises common clinical variants: `+ve`/`positive` -> `Positive`, `pMMR`/`MSS` -> `Proficient`, `clear`/`R0` -> `Clear`, etc.
- Capped at 10 suggestions.

### Import (POST /import/consultation)

`import_consultation_excel()` reads the "Doctor's Type" and "Doctor's Values" columns:
1. Finds columns by header name.
2. For each row with a field key and either a doctor type or doctor values:
   - Doctor's values are split by comma.
   - An override dict is built: `{field_key: {type: "...", allowed_values: [...]}}`
3. New overrides are merged with existing overrides via `save_overrides()`.
4. Saved to `config/field_overrides.yaml`.

### How Overrides Feed Into LLM Prompts

When `build_prompt()` constructs the user prompt, each field checks `get_field_override(f['key'])`. If `allowed_values` is non-empty, the text `"MUST be one of: X, Y, Z, or null."` is appended to the field's extraction hint. This constrains the LLM's output to predefined categories.

---

## 9. Settings Page

**Route:** `GET /settings` renders `templates/settings.html`.

### Layout

- **Header**: "Field Configuration" with buttons for Export/Import Consult Sheet and Save All Changes.
- **Search bar**: Filters fields by key, header, or group name.
- **Table**: All 88 fields with columns:
  - Field Key (code style)
  - Header (description)
  - Group (colour-coded badge)
  - Type (dropdown: string, date, text, number, boolean, dropdown)
  - Allowed Values (comma-separated text input)
  - Status: "Configured" (green) if override exists, "Default" (grey) otherwise.

### Data Flow

1. On page load, fetches `/schema` (for field structure) and `/settings/overrides` (for current overrides).
2. Renders the table with current values.
3. Changes to type or allowed values update the local `overrides` object.
4. "Save All Changes" POSTs the full overrides object to `/settings/overrides`.
5. Server saves to `config/field_overrides.yaml` via `save_overrides()`.
6. Confirmation message: "Saved N field overrides to config/field_overrides.yaml".

### Consultation Sheet Integration

- "Export Consult Sheet" links to `GET /export/consultation`.
- "Import Consult Sheet" triggers a file picker, uploads to `POST /import/consultation`, and refreshes the table with merged overrides.

---

## 10. Analytics

**Route:** `GET /analytics-page` renders `templates/analytics.html`.

### Charts (Chart.js)

#### Cancer Type Distribution (Doughnut)

- Data from `GET /analytics` -> `cancer_types` (dict of type -> count).
- Colours: blue, green, amber, red.

#### Treatment Approaches (Bar)

- Data from `GET /analytics` -> `treatments` (dict of keyword -> count).
- Treatment keywords are extracted by `_extract_treatment_keywords()` from the `first_mdt_treatment` free-text field.
- Recognised keywords: TNT, Chemotherapy, Radiotherapy, Short-course RT, Long-course CRT, Surgery, Watch & Wait, Palliative, MRI, CT scan, Papillon, Immunotherapy, Stoma, Biopsy, Referred. Unrecognised -> "Other".

#### Extraction Confidence (Doughnut)

- Data from `GET /analytics` -> `confidence` (high/medium/low counts across all fields of all patients).
- Colours: green (#238636), amber (#9e6a03), red (#da3633).

#### Column Analysis (Interactive)

- Field dropdown populated from `/schema`, grouped by schema group with group colours.
- Selecting a field fetches `GET /analytics/column/{field_key}`.
- Statistics table: total patients, populated, empty, unique values.
- Numeric analysis (if applicable): mean, standard deviation, min, max, count.
- Special case: `dob` field is converted to age before analysis.
- Value distribution bar chart (horizontal if >8 values, bucketed into 8 ranges if >10 numeric values).

---

## 11. Benchmarking

**File:** `data/benchmarks.xlsx`

### Structure

One sheet per model (sheet name = model name with colons/slashes replaced by underscores, truncated to 31 characters).

If a sheet for the current model already exists, it is deleted and recreated (overwrite).

### Per-Patient Data

| Column | Content |
|--------|---------|
| Initials | Patient initials or ID |
| High | Count of high-confidence fields |
| Medium | Count of medium-confidence fields |
| Low | Count of low-confidence fields |
| Seconds | LLM processing time (excludes queue wait) |

### Summary Row

After a blank row:
```
Total: N patients | =SUM(B2:BN) | =SUM(C2:CN) | =SUM(D2:DN) | =AVERAGE(E2:EN)
```

The benchmark is saved at the end of extraction, after all post-processing.

---

## 12. Day/Night Mode

### Theme Toggle

A button in the navbar (`#theme-toggle`) calls `toggleTheme()`:

1. Reads the current `data-bs-theme` attribute on `<html>` (default: `"dark"`).
2. Toggles between `"dark"` and `"light"`.
3. Sets `data-bs-theme` on the `<html>` element.
4. Persists the choice in `localStorage` under key `"theme"`.
5. Updates the button icon: moon (dark mode) or sun (light mode).

### CSS Variables

All colours use `var(--app-*)` custom properties. Two sets are defined in `style.css`:

**Dark theme** (`[data-bs-theme="dark"]`):
```css
--app-bg: #0d1117;
--app-surface: #161b22;
--app-border: #30363d;
--app-text: #c9d1d9;
--app-text-muted: #8b949e;
--app-accent: #58a6ff;
```

**Light theme** (`[data-bs-theme="light"]`):
```css
--app-bg: #ffffff;
--app-surface: #f6f8fa;
--app-border: #d0d7de;
--app-text: #1f2328;
--app-text-muted: #656d76;
--app-accent: #0969da;
```

Additional light-theme overrides handle: navbar background, form controls, tables, sidebar borders, preview headers/meeting-date section.

### localStorage Persistence

On page load, an IIFE reads `localStorage.getItem('theme')` and applies it immediately (before render). Default is `"dark"`. The theme persists across sessions and page navigations.

---

## Appendix: Route Reference

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Landing page (upload + backend selection) |
| `/upload` | POST | Upload DOCX or import XLSX |
| `/extract` | POST | Start extraction (params: limit, concurrency) |
| `/progress` | GET | SSE stream for live extraction progress |
| `/stop` | POST | Stop extraction gracefully |
| `/process` | GET | Process page |
| `/patients` | GET | List patients (filterable by cancer_type, search) |
| `/patients/<id>` | GET | Patient detail with all extractions |
| `/patients/<id>/fields` | PUT | Edit a field (sets confidence_basis="edited") |
| `/patients/<id>/re-extract` | POST | Re-extract a single patient |
| `/patient/<id>/preview` | GET | HTML preview + coverage data |
| `/export` | GET | Download main Excel |
| `/export/consultation` | GET | Download consultation Excel for doctor review |
| `/import/consultation` | POST | Import consultation Excel (updates field_overrides.yaml) |
| `/review` | GET | Review page |
| `/settings` | GET | Settings page |
| `/settings/overrides` | GET/POST | Get/set field overrides |
| `/backend` | GET/POST | Get/set LLM backend and model |
| `/schema` | GET | Return field schema as JSON |
| `/analytics` | GET | Analytics data (JSON) |
| `/analytics-page` | GET | Analytics page |
| `/analytics/column/<field_key>` | GET | Per-column analytics |
| `/link-source` | POST | Link source .docx to imported session |
| `/status` | GET | Current session status |
| `/audit` | GET | Audit log |
| `/reset` | POST | Wipe session and start over |
| `/debug/raw-text` | GET | Raw document text (debug) |

## Appendix: Data Model

### FieldResult
```
value: Optional[str]              # Extracted value or None
confidence_basis: str             # structured_verbatim | freeform_verbatim | freeform_inferred | edited | absent
reason: str                       # Explanation of extraction
edited: bool                      # Whether manually changed
original_value: Optional[str]     # Pre-edit value (if edited)
source_cell: Optional[dict]       # {"row": int, "col": int}
source_snippet: Optional[str]     # Matched text (max 200 chars)
confidence: str (property)        # Maps basis to high/medium/low/none
```

### PatientBlock
```
id: str                           # Hospital Number or PATIENT_NNN
unique_id: str                    # DDMMYYYY_XX_G_disambiguator
initials: str                     # e.g., "AO"
nhs_number: str                   # 10-digit NHS number
gender: str                       # Male/Female
mdt_date: str                     # DD/MM/YYYY
raw_text: str                     # Flattened table text
extractions: dict                 # {group_name: {field_key: FieldResult}}
raw_cells: list                   # [{row, col, text}, ...]
coverage_map: dict                # {"{row},{col}": [{start, end, used}, ...]}
coverage_pct: Optional[float]     # Percentage of text matched
coverage_stats: Optional[dict]    # {used_pct, unused_pct, inferred_fields, total_chars}
```

### ExtractionSession
```
file_name: str
upload_time: str
patients: list[PatientBlock]
status: str                       # idle | parsing | parsed | extracting | complete | stopped
stop_requested: bool
concurrency: int
progress: dict                    # Detailed progress tracking
```
