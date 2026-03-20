# How the MDT Data Extractor Works — Detailed Technical Guide

This document explains every part of the system in detail, so you can understand, debug, and modify it.

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Project File Structure](#2-project-file-structure)
3. [Step-by-Step: What Happens When You Use It](#3-step-by-step-what-happens-when-you-use-it)
4. [Component Deep Dives](#4-component-deep-dives)
   - 4.1 [The Field Schema (field_schema.yaml)](#41-the-field-schema)
   - 4.2 [The Data Models (models.py)](#42-the-data-models)
   - 4.3 [The Document Parser (docx_parser.py)](#43-the-document-parser)
   - 4.4 [The Prompt Builder (prompt_builder.py)](#44-the-prompt-builder)
   - 4.5 [The LLM Client (llm_client.py)](#45-the-llm-client)
   - 4.6 [The Response Parser (response_parser.py)](#46-the-response-parser)
   - 4.7 [The Excel Writer (excel_writer.py)](#47-the-excel-writer)
   - 4.8 [The Audit Logger (audit.py)](#48-the-audit-logger)
   - 4.9 [The Flask App (app.py)](#49-the-flask-app)
   - 4.10 [The Frontend (app.js)](#410-the-frontend)
5. [How the LLM Extraction Actually Works](#5-how-the-llm-extraction-actually-works)
6. [Confidence Scoring Explained](#6-confidence-scoring-explained)
7. [Common Issues and How to Fix Them](#7-common-issues-and-how-to-fix-them)

---

## 1. High-Level Overview

The program does one thing: **reads a Word document containing MDT patient notes and turns it into a structured Excel spreadsheet.**

The flow is:

```
User uploads .docx file
        |
        v
Document Parser reads the Word file
        |  Each table in the document = one patient
        |  Extracts raw text for each patient
        v
For each patient, for each clinical category (16 total):
        |
        v
Prompt Builder creates an LLM prompt
        |  "Here is a patient's notes. Extract these specific fields..."
        v
LLM (Claude API or local Ollama) processes the prompt
        |  Returns JSON: {"dob": {"value": "26/05/1970", "confidence": "high"}, ...}
        v
Response Parser validates the JSON
        |  Checks data types, applies confidence overrides
        v
Results stored in memory (Python objects)
        |
        v
Review Dashboard shows results to clinician
        |  Clinician can edit values, filter by confidence
        v
Excel Writer exports to .xlsx file
        |  Maps each field to the correct column (1-88)
        v
Done. Excel file downloads.
```

---

## 2. Project File Structure

```
Clinical AI/
├── .env                    # API key (ANTHROPIC_API_KEY=sk-ant-...)
├── app.py                  # Flask web server — all routes, SSE progress, session management
├── models.py               # Data structures (FieldResult, PatientBlock, ExtractionSession)
├── audit.py                # Logs every action to logs/audit.jsonl
│
├── config/
│   ├── __init__.py         # Loads and caches field_schema.yaml
│   └── field_schema.yaml   # THE SINGLE SOURCE OF TRUTH — defines all 88 fields
│
├── parser/
│   └── docx_parser.py      # Reads .docx, splits into per-patient text blocks
│
├── extractor/
│   ├── llm_client.py       # Sends prompts to Claude API or Ollama
│   ├── prompt_builder.py   # Builds prompts from the schema
│   └── response_parser.py  # Parses LLM JSON responses, validates, applies confidence rules
│
├── export/
│   └── excel_writer.py     # Generates the 97-column Excel file
│
├── static/
│   ├── css/style.css       # Dark theme styling
│   └── js/app.js           # All frontend logic (upload, progress, editing, filtering)
│
├── templates/
│   ├── base.html           # Base layout (nav bar, Bootstrap, scripts)
│   ├── index.html          # Landing page (drag-and-drop upload)
│   ├── process.html        # Processing page (progress bar, extraction status)
│   ├── review.html         # Review dashboard (patient list, category tabs, editable table)
│   └── analytics.html      # Analytics page (Chart.js charts)
│
├── tests/
│   ├── test_schema.py      # Validates field_schema.yaml is complete and correct
│   └── test_export.py      # Tests Excel export round-trip
│
├── data/                   # Uploaded files and exports (gitignored)
└── logs/                   # Audit trail (gitignored)
```

**Key principle:** `field_schema.yaml` drives everything. The prompts, the UI, and the Excel export all read from this one file. If you want to add a new field, you add it to the YAML and everything else picks it up automatically.

---

## 3. Step-by-Step: What Happens When You Use It

### Step 1: User opens http://localhost:5000

- Flask serves `templates/index.html`
- The page shows a drag-and-drop upload zone
- `app.py` calls `check_ollama()` to see if the LLM backend is available
- If Claude API key is set in `.env`, it reports available immediately
- If using Ollama, it pings `http://localhost:11434/api/tags` to check

### Step 2: User uploads a .docx file

**Frontend (`app.js`):**
- User drags a file onto the upload zone (or clicks to browse)
- JavaScript creates a `FormData` object and POSTs to `/upload`

**Backend (`app.py` → `/upload` route):**
1. Saves the file to `data/` directory
2. Calls `parse_docx(file_path)` from `parser/docx_parser.py`
3. The parser opens the Word document using `python-docx`
4. It finds that the document contains 50 tables — one table per patient
5. For each table:
   - Reads row 1, cell 0 to get patient details (hospital number, NHS number, name, DOB, gender)
   - Extracts the name using regex patterns (handles 3 different name formats found in the data)
   - Converts the name to initials (e.g., "AIDEN O'CONNOR" → "AOC")
   - Flattens the entire table into a single text string (the "raw_text")
   - Creates a `PatientBlock` object
6. Returns JSON: `{"patients_detected": 50, "patient_list": [...]}`
7. JavaScript stores this in `sessionStorage` and redirects to `/process`

### Step 3: User clicks "Start Extraction"

**Frontend (`app.js`):**
- Reads the optional patient limit field (e.g., "5" to only process 5 patients)
- POSTs to `/extract` with `{"limit": 5}`
- Immediately opens an `EventSource` on `/progress` to listen for SSE (Server-Sent Events)

**Backend (`app.py` → `/extract` route):**
1. Starts a **background thread** running `_run_extraction()`
2. Returns immediately with `{"status": "started"}`

**Background thread (`_run_extraction`):**

This is the core of the program. For each patient:

```
For patient 1 (out of 50):
    For group "Demographics" (7 fields):
        1. prompt_builder.build_prompt(patient.raw_text, demographics_group)
           → Creates a prompt like:
             "You are a clinical data extraction assistant.
              Extract: dob, initials, mrn, nhs_number, gender, previous_cancer, previous_cancer_site
              From this text: [patient's raw text]
              Return JSON with value and confidence for each field."

        2. llm_client.generate(prompt)
           → Sends to Claude API (or Ollama)
           → Gets back JSON like:
             {"dob": {"value": "26/05/1970", "confidence": "high"},
              "gender": {"value": "Male", "confidence": "high"}, ...}

        3. response_parser.parse_llm_response(raw_response, group)
           → Extracts JSON from the response (handles markdown code blocks)
           → Validates each field against expected keys
           → Applies confidence overrides (e.g., bad date format → low)
           → Returns dict of FieldResult objects

        4. Stores results: patient.extractions["Demographics"] = results

    For group "Endoscopy" (3 fields):
        ... same process ...

    For group "Histology" (3 fields):
        ... same process ...

    ... 13 more groups ...

    After all 16 groups done for this patient:
        → Add to completed_patients list
        → Update session.progress for SSE

Move to patient 2...
```

**Retry logic:** If all fields come back null after the first LLM call (likely a malformed response), it retries once with the same prompt.

**Error handling:** If an LLM call fails (network error, timeout, API error), all fields in that group are set to `null` with confidence `"none"`. The error is logged to the audit trail. Processing continues with the next group.

### Step 4: SSE Progress Updates

**Backend (`app.py` → `/progress` route):**
- Runs an infinite loop checking `session.progress`
- Every time the current patient number changes, it sends an SSE event:
  ```json
  {"current_patient": 3, "total": 50, "current_group": "Baseline MRI",
   "completed_patients": [{"id": "9990001", "initials": "AOC", "confidence_summary": {"high": 12, "medium": 3, "low": 1}}]}
  ```
- When extraction finishes, sends `{"status": "complete"}`

**Frontend (`app.js` → `listenProgress()`):**
- Updates the progress bar width
- Shows which patient and group is being processed
- Renders the completed patients log with confidence summaries
- When "complete" event arrives, shows the completion section with Review/Export buttons

### Step 5: User reviews data

**Frontend → `/review` page:**
- Calls `GET /patients` to load the patient list
- Renders sidebar with each patient's initials, NHS number, and confidence badges
- When user clicks a patient:
  - Calls `GET /patients/<id>` to get all their extracted data + raw source text
  - Renders category tabs (Demographics, Endoscopy, Histology, etc.)
  - Shows editable table for the selected category
  - Shows source text panel at the bottom

**Inline editing:**
- User changes a value in the table
- JavaScript calls `PUT /patients/<id>/fields` with `{"group": "Demographics", "field": "dob", "value": "27/05/1970"}`
- Backend updates the `FieldResult`: sets `edited = True`, stores `original_value`, updates `value`
- Logs the edit to the audit trail

**Confidence filter:**
- Dropdown with "All", "Low Only", "Medium + Low"
- JavaScript filters the table rows in `renderFieldTable()` — only shows fields matching the selected confidence levels
- Fields with confidence `"none"` (null/absent) are hidden by default

### Step 6: User exports to Excel

**Frontend → clicks "Export Excel":**
- Browser navigates to `GET /export`

**Backend (`app.py` → `/export` route):**
1. Calls `write_excel(session.patients, output_path)`
2. The Excel writer:
   - Creates a workbook with sheet "Prototype V1"
   - Reads all field definitions from `field_schema.yaml` via `get_all_fields()`
   - Writes header row: for each field, puts the `excel_header` text in column `excel_column`
   - For each patient (one row per patient):
     - For each extracted field that has a non-null value:
       - Looks up the column number from the schema
       - Writes the value to that cell
       - If the field type is "date", applies DD/MM/YYYY formatting
3. Returns the .xlsx file as a download

---

## 4. Component Deep Dives

### 4.1 The Field Schema

**File:** `config/field_schema.yaml`

This is the most important file in the project. It defines every field the system extracts.

**Structure:**
```yaml
groups:
  - name: Demographics          # Category name (shown as a tab in the UI)
    description: "Patient demographic information"
    fields:
      - key: dob                # Internal identifier (used in code and JSON)
        excel_column: 1         # Which column in the Excel output (1-based)
        excel_header: "Demographics: DOB(a)"  # Header text in Excel
        prompt_hint: "Date of birth. Format: DD/MM/YYYY"  # Instruction for the LLM
        type: date              # Data type: "date", "string", or "text"
```

**How it's used:**
- `prompt_builder.py` reads the `prompt_hint` to tell the LLM what to extract
- `response_parser.py` reads the `type` to validate extracted values
- `excel_writer.py` reads `excel_column` and `excel_header` to write the correct columns
- The frontend reads group names to create category tabs

**If you want to add a new field:** Add it to the YAML under the right group. Set the `excel_column` to a unique number. Everything else picks it up automatically.

**Total:** 16 groups, 88 fields, covering Excel columns 1-88. Columns 89-97 in the ground truth are empty/reserved.

### 4.2 The Data Models

**File:** `models.py`

Three dataclasses hold all the data in memory (no database):

**`FieldResult`** — One extracted field value:
```python
@dataclass
class FieldResult:
    value: Optional[str] = None      # The extracted text, or None if not found
    confidence: str = "low"          # "high", "medium", "low", or "none" (absent)
    edited: bool = False             # True if the clinician changed it
    original_value: Optional[str] = None  # What the LLM originally extracted (before edit)
```

**`PatientBlock`** — One patient:
```python
@dataclass
class PatientBlock:
    id: str              # Hospital number (e.g., "9990001")
    initials: str        # e.g., "AOC"
    nhs_number: str      # e.g., "9990000001"
    raw_text: str        # The full text from their table in the Word document
    extractions: dict    # {"Demographics": {"dob": FieldResult, ...}, "Endoscopy": {...}, ...}
```

**`ExtractionSession`** — The whole session:
```python
@dataclass
class ExtractionSession:
    file_name: str       # e.g., "hackathon-mdt-outcome-proformas.docx"
    upload_time: str     # ISO timestamp
    patients: list       # List of PatientBlock objects
    status: str          # "idle" → "parsing" → "parsed" → "extracting" → "complete"
    progress: dict       # {"current_patient": 12, "total": 50, "current_group": "MRI"}
```

There is one global `ExtractionSession` object. It exists only in memory — closing the app loses everything. This is by design for the hackathon (no database needed for 50 patients).

### 4.3 The Document Parser

**File:** `parser/docx_parser.py`

**What it does:** Opens the `.docx` file, finds each patient, extracts their text.

**How it works:**

The hackathon Word document has a specific structure: **one table per patient, 50 tables total**. Each table has 8 rows and 3 columns:

| Row | Content |
|-----|---------|
| 0 | Headers ("Patient Details" / "Cancer Target Dates") |
| 1 | Demographics: hospital number, NHS number, name, gender, DOB |
| 2 | Staging/diagnosis header |
| 3 | Diagnosis + staging detail |
| 4 | Clinical details header |
| 5 | Clinical details free text |
| 6 | MDT outcome header |
| 7 | MDT outcome free text |

The parser:
1. Opens the document with `python-docx`
2. Iterates through `doc.tables` (one per patient)
3. For each table:
   - Reads row 1, cell 0 for patient details
   - Extracts the hospital number using regex: `Hospital Number:\s*(\S+)`
   - Extracts the NHS number using regex: `NHS Number:\s*([\d\s()\w]+)`
   - Extracts the patient name using three strategies:
     - Look for `Name: <value>` prefix
     - Look for an all-uppercase line (old format)
     - Take the third non-empty line (after hospital/NHS lines)
   - Converts the name to initials (e.g., "AIDEN O'CONNOR" → "AOC")
   - Flattens the entire table into a single text block (deduplicating columns 1/2 which copy column 0)
4. Returns a list of `PatientBlock` objects

**Important:** If you use a different Word document with a different structure, the parser will need to be adjusted. The splitting logic is specific to this proforma format.

### 4.4 The Prompt Builder

**File:** `extractor/prompt_builder.py`

**What it does:** Creates the text prompt sent to the LLM for each patient × category.

**How it works:**

For each schema group (e.g., "Demographics"), it builds a prompt like:

```
You are a clinical data extraction assistant. Extract the following fields
from the patient's MDT notes below.

For each field, provide:
- "value": the extracted value, or null if not mentioned in the text
- "confidence": "high" if explicitly stated, "medium" if inferred, "low" if uncertain

Return ONLY valid JSON in this exact format:
{
  "dob": {"value": "...", "confidence": "high|medium|low"},
  "initials": {"value": "...", "confidence": "high|medium|low"},
  ...
}

Fields to extract:
- dob: Date of birth. Format: DD/MM/YYYY
- initials: Patient initials (e.g., AO, BK)
- mrn: Medical Record Number (numeric)
- nhs_number: NHS number (10-digit numeric, may start with NNN)
- gender: Patient gender: Male or Female
- previous_cancer: Previous cancer history: Yes or No
- previous_cancer_site: Site of previous cancer if applicable, or N/A

Patient MDT Notes:
---
[the patient's raw text goes here]
---
```

The field list and JSON example are generated automatically from the schema. The `prompt_hint` for each field tells the LLM exactly what to look for and what format to use.

### 4.5 The LLM Client

**File:** `extractor/llm_client.py`

**What it does:** Sends prompts to the LLM and gets responses back.

**Two backends:**

1. **Claude API** (used when `ANTHROPIC_API_KEY` is set in `.env`):
   - Calls `POST https://api.anthropic.com/v1/messages`
   - Uses model `claude-haiku-4-5-20251001` (fast, cheap)
   - Temperature 0 (deterministic output)
   - Each call takes ~2-3 seconds

2. **Ollama** (fallback when no API key):
   - Calls `POST http://localhost:11434/api/generate`
   - Uses model `llama3.1:8b` (runs locally)
   - Temperature 0, context window 8192 tokens
   - Each call takes ~30-60 seconds on CPU

**How the backend is selected:**

```python
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
USE_CLAUDE = bool(ANTHROPIC_API_KEY)
```

If the `.env` file contains `ANTHROPIC_API_KEY=sk-ant-...`, it uses Claude. Otherwise Ollama. No config needed — just presence of the key.

### 4.6 The Response Parser

**File:** `extractor/response_parser.py`

**What it does:** Takes the raw text from the LLM and turns it into validated `FieldResult` objects.

**The challenge:** LLMs don't always return clean JSON. They might wrap it in markdown code blocks, add explanatory text, or return malformed JSON.

**How it handles this (3 attempts):**

1. Try `json.loads(raw_response)` directly
2. Look for ` ```json ... ``` ` blocks and parse the content
3. Find the first `{ ... }` block in the text and try parsing that

If all three fail, every field in the group is set to `null` with confidence `"none"`.

**Confidence overrides:**

After parsing, it applies programmatic rules on top of the LLM's self-reported confidence:

| Situation | Action |
|-----------|--------|
| Value is `null` / `None` / `"N/A"` / empty | Confidence = `"none"` (field not present in document) |
| Field type is `date` but value doesn't match `DD/MM/YYYY` | Confidence = `"low"` |
| Otherwise | Keep the LLM's self-reported confidence |

This hybrid approach (LLM self-assessment + programmatic validation) is more reliable than trusting the LLM alone, especially on smaller models.

### 4.7 The Excel Writer

**File:** `export/excel_writer.py`

**What it does:** Takes all the patient data and writes it to a `.xlsx` file matching the ground truth format.

**How it works:**

1. Creates a workbook with sheet name "Prototype V1" (matching the hackathon template)
2. Reads all field definitions from the schema using `get_all_fields()`
3. Writes row 1 (headers): for each of the 88 fields, writes the `excel_header` text into the column specified by `excel_column`
4. For each patient (rows 2, 3, 4, ...):
   - Loops through all their extractions
   - For each field that has a non-null value, writes it to the correct column
   - Date fields get `DD/MM/YYYY` number formatting
5. Saves the file

**Result:** A 97-column Excel file where columns 1-88 have data (matching the schema) and columns 89-97 are empty (reserved in the ground truth).

### 4.8 The Audit Logger

**File:** `audit.py`

**What it does:** Logs every action to `logs/audit.jsonl` for clinical safety traceability.

**Events logged:**
- `upload` — file uploaded, number of patients detected
- `extraction` — per group per patient, how many fields extracted, confidence breakdown
- `extraction_error` — if an LLM call fails, logs the error message
- `manual_edit` — when a clinician edits a field, logs old and new values
- `export` — when Excel is exported, how many patients
- `reset` — when session is wiped

**Format:** One JSON object per line (JSON Lines format):
```json
{"timestamp": "2026-03-20T01:23:45", "action": "manual_edit", "patient_id": "9990000001", "group": "Demographics", "field": "dob", "old_value": "26/05/1970", "new_value": "27/05/1970"}
```

### 4.9 The Flask App

**File:** `app.py`

**What it does:** The web server. Connects everything together.

**Key routes:**

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Landing page with upload zone |
| `/upload` | POST | Receive .docx file, parse it, return patient count |
| `/extract` | POST | Start LLM extraction in background thread |
| `/progress` | GET | SSE stream of extraction progress |
| `/process` | GET | Processing page (progress bar UI) |
| `/patients` | GET | List all patients with confidence summaries |
| `/patients/<id>` | GET | Get one patient's full data + raw text |
| `/patients/<id>/fields` | PUT | Edit a field value |
| `/patients/<id>/re-extract` | POST | Re-run extraction for one patient |
| `/export` | GET | Download Excel file |
| `/analytics` | GET | JSON data for charts |
| `/analytics-page` | GET | Analytics page with charts |
| `/review` | GET | Review dashboard page |
| `/audit` | GET | View audit trail |
| `/reset` | POST | Wipe all data, start fresh |
| `/debug/raw-text` | GET | View raw document text (debugging) |

**Important design choice:** The extraction runs in a **background thread**, not in the request handler. This lets the server respond immediately and stream progress via SSE. The `session` object is a module-level global, shared between the request thread and the extraction thread.

### 4.10 The Frontend

**File:** `static/js/app.js`

**What it does:** All client-side logic — no frontend framework, just vanilla JavaScript.

**Key functions:**

| Function | What it does |
|----------|-------------|
| `uploadFile(file)` | POSTs file to `/upload`, redirects to `/process` |
| `startExtraction()` | POSTs to `/extract`, opens SSE listener |
| `listenProgress()` | Receives SSE events, updates progress bar and log |
| `loadPatients(filters)` | GETs `/patients`, renders sidebar list |
| `selectPatient(id)` | GETs `/patients/<id>`, renders tabs and table |
| `renderGroupTabs(groups)` | Creates the category tab bar |
| `renderFieldTable(fields, group)` | Renders the editable field table with confidence colours |
| `filterConfidence(filter)` | Filters table to show only selected confidence levels |
| `editField(group, field, value)` | PUTs edited value to server |

---

## 5. How the LLM Extraction Actually Works

This is the core of the system, so let's trace a single extraction in detail.

**Patient:** AIDEN O'CONNOR (hospital number 9990001)

**Raw text (from the Word document):**
```
Patient Details
Hospital Number: 9990001
NHS Number: 9990000001
AIDEN O'CONNOR
Male
26/05/1970 Age: 55
62 DAY TARGET: 20/05/2025
Colonoscopy complete showing malignant-looking mass at 13cm...
Biopsy: ADENOCARCINOMA, NOT OTHERWISE SPECIFIED
MMR Status: Deficient
Baseline MRI: mrT3b, mrN1, mrEMVI positive, mrCRM clear...
MDT Decision: Total Neoadjuvant Therapy (TNT)...
```

**Group being processed:** Demographics (7 fields)

**Step 1 — Prompt Builder creates the prompt:**
Combines the template + field hints + patient text into a ~2400 character prompt.

**Step 2 — LLM Client sends it to Claude:**
Claude responds in ~2 seconds with:
```json
{
  "dob": {"value": "26/05/1970", "confidence": "high"},
  "initials": {"value": "AO", "confidence": "high"},
  "mrn": {"value": "9990001", "confidence": "high"},
  "nhs_number": {"value": "9990000001", "confidence": "high"},
  "gender": {"value": "Male", "confidence": "high"},
  "previous_cancer": {"value": "No", "confidence": "medium"},
  "previous_cancer_site": {"value": null, "confidence": "low"}
}
```

**Step 3 — Response Parser validates:**
- `dob`: value "26/05/1970" matches DD/MM/YYYY → keep "high" ✓
- `previous_cancer_site`: value is null → override to "none" (absent, not uncertain)

**Step 4 — Stored in patient object:**
```python
patient.extractions["Demographics"] = {
    "dob": FieldResult(value="26/05/1970", confidence="high"),
    "initials": FieldResult(value="AO", confidence="high"),
    ...
    "previous_cancer_site": FieldResult(value=None, confidence="none"),
}
```

**Then repeat for Endoscopy, Histology, Baseline MRI, ... (15 more groups)**

Total per patient: 16 LLM calls, extracting up to 88 fields.
Total for 50 patients: ~800 LLM calls.

---

## 6. Confidence Scoring Explained

Every extracted field has a confidence level:

| Level | Meaning | Colour in UI | Counted in badges? |
|-------|---------|-------------|-------------------|
| `high` | Explicitly stated in the text (e.g., "DOB: 26/05/1970") | Green | Yes |
| `medium` | Inferred from context (e.g., treatment approach derived from discussion) | Amber | Yes |
| `low` | Value was extracted but looks uncertain or potentially wrong | Red | Yes |
| `none` | Field not mentioned in the document — value is null | Hidden | No |

**Where confidence comes from:**

1. **LLM self-assessment:** The prompt asks the LLM to rate each field as high/medium/low. This is the primary signal.

2. **Programmatic overrides:** After the LLM responds, the code applies rules:
   - If the value is null → `"none"` (not counted as a problem)
   - If a date field doesn't match DD/MM/YYYY format → `"low"` (probably wrong)

**Why this matters for the presentation:**
- It demonstrates clinical safety awareness
- Clinicians don't have to check all 88 fields — they can filter to "Low Only"
- The audit trail records the original LLM extraction and any manual edits

---

## 7. Common Issues and How to Fix Them

### "All fields are null / 0 high, 0 med, 0 low"
**Cause:** The LLM calls failed (check `logs/audit.jsonl` for `extraction_error` entries).
**Common reasons:**
- API key not loaded (Flask was started before `.env` was created — restart Flask)
- API key invalid or expired
- Ollama not running (if using local mode)

### "Progress bar stuck"
**Cause:** SSE connection dropped or extraction thread crashed.
**Fix:** Check the Flask terminal for error tracebacks. Restart Flask and try again.

### "Wrong number of patients detected"
**Cause:** The document has a different structure than expected.
**Fix:** Visit `/debug/raw-text` to see what the parser is reading. Adjust the table-splitting logic in `docx_parser.py`.

### "Columns don't match ground truth"
**Cause:** The `excel_column` values in `field_schema.yaml` don't match the template.
**Fix:** Open the ground truth Excel and compare headers. Update column numbers in the YAML.

### "Want to start over"
**Fix:** Click the "Reset" button in the nav bar, or POST to `/reset`. This wipes all data and the audit log.
