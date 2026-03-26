# Extraction Pipeline -- Technical Reference

This document is the definitive technical reference for the Clinical AI extraction pipeline. It covers every module, function, constant, regex pattern, prompt structure, and algorithm involved in transforming raw DOCX MDT outcome proformas into structured clinical data.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Models (`models.py`)](#2-data-models)
3. [DOCX Parser (`parser/docx_parser.py`)](#3-docx-parser)
4. [Regex Extractor (`extractor/regex_extractor.py`)](#4-regex-extractor)
5. [Clinical Context (`extractor/clinical_context.py`)](#5-clinical-context)
6. [Prompt Builder (`extractor/prompt_builder.py`)](#6-prompt-builder)
7. [LLM Client (`extractor/llm_client.py`)](#7-llm-client)
8. [Response Parser (`extractor/response_parser.py`)](#8-response-parser)
9. [Coverage (`extractor/coverage.py`)](#9-coverage)
10. [HTML Preview (`extractor/html_preview.py`)](#10-html-preview)
11. [Prompt Templates (`config/prompts/`)](#11-prompt-templates)
12. [Configuration (`config/`)](#12-configuration)

---

## 1. Architecture Overview

The extraction pipeline is a two-phase system:

```
DOCX File
  |
  v
[docx_parser] -- parse_docx() --> list[PatientBlock]
  |                                  (raw_text, raw_cells)
  v
Phase 1: REGEX EXTRACTION
  |
  [regex_extractor] -- regex_extract() per group --> FieldResult (high confidence)
  |
  v
Phase 2: LLM EXTRACTION (only for fields regex could not fill)
  |
  [prompt_builder] -- build_prompt() --> (system_prompt, user_prompt)
  [llm_client]     -- generate()     --> raw LLM response string
  [response_parser] -- parse_llm_response() --> FieldResult (medium/low confidence)
  |
  v
[coverage]      -- compute_coverage()    --> coverage_map, coverage_pct
[html_preview]  -- render_html_preview() --> HTML string for review panel
```

Data flows through three core types:
- **`PatientBlock`**: Container for one patient's raw data and all extraction results.
- **`FieldResult`**: Result for a single field, with value, confidence, provenance.
- **`CellRef`**: TypedDict `{row, col, text}` identifying a cell in the source table.

---

## 2. Data Models

**File**: `models.py`

### `CellRef` (TypedDict)

| Field  | Type  | Description                         |
|--------|-------|-------------------------------------|
| `row`  | `int` | Row index in the source DOCX table  |
| `col`  | `int` | Column index (post-dedup)           |
| `text` | `str` | Cell text content                   |

### `FieldResult` (dataclass)

| Field              | Type            | Default    | Description                                             |
|--------------------|-----------------|------------|---------------------------------------------------------|
| `value`            | `Optional[str]` | `None`     | Extracted value                                         |
| `confidence_basis` | `str`           | `"absent"` | One of: `structured_verbatim`, `freeform_verbatim`, `freeform_inferred`, `edited`, `absent` |
| `reason`           | `str`           | `""`       | Human-readable extraction rationale                     |
| `edited`           | `bool`          | `False`    | Whether a reviewer manually changed this value          |
| `original_value`   | `Optional[str]` | `None`     | Pre-edit value, if edited                               |
| `source_cell`      | `Optional[dict]`| `None`     | `{"row": int, "col": int}` pointing to the origin cell |
| `source_snippet`   | `Optional[str]` | `None`     | Exact matched text from the source (max 200 chars)      |

**Confidence mapping** (`_CONFIDENCE_MAP`):

| `confidence_basis`    | `confidence` property | Meaning                              |
|-----------------------|-----------------------|--------------------------------------|
| `structured_verbatim` | `"high"`              | Regex match from structured cell     |
| `freeform_verbatim`   | `"medium"`            | Verbatim text found in freeform cell |
| `freeform_inferred`   | `"low"`               | LLM inferred from context            |
| `edited`              | `"medium"`            | Manually edited by reviewer          |
| `absent`              | `"none"`              | Not found anywhere                   |

### `PatientBlock` (dataclass)

| Field            | Type              | Description                                   |
|------------------|-------------------|-----------------------------------------------|
| `id`             | `str`             | Legacy MRN-based ID                           |
| `unique_id`      | `str`             | Format: `{DDMMYYYY}_{initials}_{G}_{disambig}`|
| `initials`       | `str`             | Patient initials                               |
| `nhs_number`     | `str`             | NHS number (digits only)                       |
| `gender`         | `str`             | `"Male"` / `"Female"` / `""`                  |
| `mdt_date`       | `str`             | MDT meeting date DD/MM/YYYY                   |
| `raw_text`       | `str`             | Flattened text of entire patient table         |
| `extractions`    | `dict`            | `{group_name: {field_key: FieldResult}}`       |
| `raw_cells`      | `list[CellRef]`   | All cells from the source table                |
| `coverage_map`   | `dict`            | `{"{row},{col}": [{start, end, used}]}`        |
| `coverage_pct`   | `Optional[float]` | Percentage of source characters matched        |
| `coverage_stats` | `Optional[dict]`  | `{used_pct, unused_pct, inferred_fields, total_chars}` |

### `ExtractionSession` (dataclass)

| Field            | Type   | Description                                    |
|------------------|--------|------------------------------------------------|
| `file_name`      | `str`  | Uploaded DOCX filename                         |
| `upload_time`    | `str`  | ISO timestamp                                  |
| `patients`       | `list` | `list[PatientBlock]`                           |
| `status`         | `str`  | `"idle"` / `"running"` / `"done"`              |
| `stop_requested` | `bool` | Flag to abort extraction                       |
| `concurrency`    | `int`  | Number of parallel extraction threads           |
| `progress`       | `dict` | Detailed progress tracking (see source)        |

---

## 3. DOCX Parser

**File**: `parser/docx_parser.py`

### Document Structure

The MDT outcome proforma DOCX contains:
- **Paragraph headers** before each table: `"{CancerType} Multidisciplinary Meeting {DD/MM/YYYY}(i)"`
- **One table per patient** (50 patients total)
- Each table has a consistent **8-row x 3-column** structure:

| Row | Content                       | Row Type    |
|-----|-------------------------------|-------------|
| 0   | Headers: "Patient Details" / "Cancer Target Dates" | Header |
| 1   | Demographics (MRN, NHS, name, gender, DOB) | Content    |
| 2   | "Staging & Diagnosis(g)" header | Header     |
| 3   | Diagnosis + staging detail    | Content     |
| 4   | "Clinical Details(f)" header  | Header      |
| 5   | Clinical details free text    | Content     |
| 6   | "MDT Outcome(h)" header      | Header      |
| 7   | MDT outcome free text         | Content     |

Columns 1 and 2 are often duplicates of column 0. Column 2 holds cancer target dates where appropriate.

### Public Functions

#### `parse_docx(file_path: str) -> list[PatientBlock]`

Main entry point. Steps:
1. Opens the DOCX with `python-docx`.
2. Calls `_extract_mdt_headers(doc)` to get MDT dates and cancer types from paragraph headers.
3. Iterates over `doc.tables` (one per patient).
4. For each table:
   - Extracts patient name via `_extract_name()` (3 strategies: explicit "Name:" prefix, all-caps line, third non-empty line).
   - Extracts NHS number via `_extract_nhs()`.
   - Extracts hospital number via `_HOSPITAL_RE`.
   - Calls `_table_to_text()` for flattened raw text.
   - Calls `_table_to_cells()` for structured cell list.
   - Prepends `"Cancer Type: {type}\nMDT Meeting Date: {date}"` to raw_text.
   - Inserts a synthetic cell at `row=-1, col=0` with the prepended header.
5. Returns `list[PatientBlock]`.

#### `get_raw_text(file_path: str) -> str`

Debug helper that returns the entire document as a single string (all paragraphs + all table cells).

### Cell Deduplication (`_table_to_cells`)

Two deduplication strategies:
1. **XML element identity**: `python-docx` merged cells share the same `_tc` object. Tracked via `id(cell._tc)` in a `seen_tcs` set.
2. **Adjacent text comparison**: Word sometimes copies cell content without a true merge. If `cell.text == prev_text`, the cell is skipped.

Column indices are renumbered sequentially per row after deduplication.

### Internal Constants

| Constant          | Pattern                                                              |
|-------------------|----------------------------------------------------------------------|
| `_NHS_RE`         | `r'NHS Number:\s*([\d\s()\w]+?)(?:\n\|$)'`                          |
| `_HOSPITAL_RE`    | `r'Hospital Number:\s*(\S+)'`                                       |
| `_GENDER_RE`      | `r'\b(Male\|Female)\b'`                                             |
| `_NAME_RE`        | `r'(?:Name:\s*)?([A-Z][A-Za-z\'\-]+(?:\s+[A-Za-z\'\-]+)+)'`        |
| `_MDT_DATE_RE`    | `r'Multidisciplinary.*?Meeting\s+(\d{2}/\d{2}/\d{4})'`             |
| `_MDT_HEADER_RE`  | `r'(\w[\w\s]*?)\s*Multidisciplinary.*?Meeting\s+(\d{2}/\d{2}/\d{4})'` |

### Name Extraction Strategies

`_extract_name(details_text)` tries three approaches in order:

1. **Explicit prefix**: `Name: <value>` on a line.
2. **All-caps line**: A line where `stripped.replace(' ','').replace("'",'').replace('-','').isupper()` is true, AND none of the words match `_NOT_NAME` keywords (`DAY`, `TARGET`, `BREACH`, `DATE`, `PATHWAY`, `PLEASE`, `TREATMENT`, `DECISION`, `STAGING`, `DIAGNOSIS`, `CLINICAL`, `MDT`, `OUTCOME`, `NOTE`, `NUMBER`, `HOSPITAL`, `NHS`).
3. **Third non-empty line**: `lines[2]` if it contains a space and no digits (heuristic: lines[0] = Hospital Number, lines[1] = NHS Number, lines[2] = name).

---

## 4. Regex Extractor

**File**: `extractor/regex_extractor.py`

This module handles approximately 90% of fields without any LLM call. Only fields requiring contextual interpretation (endoscopy type inference, M staging inference, surgery intent, W&W reasoning) are left for the LLM.

### Public Functions

#### `regex_extract(raw_text, group_name, fields, raw_cells=None) -> dict[str, FieldResult]`

```python
def regex_extract(raw_text: str, group_name: str, fields: list[dict],
                  raw_cells: list[dict] | None = None) -> dict[str, FieldResult]
```

Dispatches to the appropriate per-group extractor. For each extracted field:
1. Receives `(normalised_value, raw_match_span)` from the group extractor.
2. Searches `raw_cells` for the cell containing `raw_match_span` (substring match).
3. Determines `confidence_basis`:
   - If `source_cell.row` is in `_FREEFORM_ROWS` ({4, 5, 6, 7}): `"freeform_verbatim"`.
   - Otherwise: `"structured_verbatim"`.
4. Returns `FieldResult` with `source_cell`, `source_snippet` (capped at 200 chars).

Fields not extracted return `FieldResult(value=None, confidence_basis='absent')`.

#### `build_unique_id(mdt_date, initials, gender, mrn, nhs, row_index=0) -> str`

```python
def build_unique_id(mdt_date: str, initials: str, gender: str,
                    mrn: str, nhs: str, row_index: int = 0) -> str
```

Format: `{DDMMYYYY}_{initials}_{G}_{disambiguator}`

- Date: all separators (`/`, `-`, `.`, space) stripped.
- Gender: `M`, `F`, or `U` (unknown).
- Disambiguator priority: MRN > last 4 digits of NHS > zero-padded row_index.

#### `assign_unique_id(patient, demographics_results, row_index=0) -> None`

Sets `patient.unique_id` using demographics extraction results.

### Key Constants

```python
_FREEFORM_ROWS = {4, 5, 6, 7}  # Clinical details (4,5) and MDT outcome (6,7)
```

### Extractor Dispatch Table

```python
extractors = {
    "Demographics":       _extract_demographics,
    "Endoscopy":          _extract_endoscopy,
    "Histology":          _extract_histology,
    "Baseline MRI":       _extract_baseline_mri,
    "Baseline CT":        _extract_baseline_ct,
    "MDT":                _extract_mdt,
    "Chemotherapy":       _extract_chemotherapy,
    "Immunotherapy":      _extract_immunotherapy,
    "Radiotherapy":       _extract_radiotherapy,
    "CEA and Clinical":   _extract_cea,
    "Surgery":            _extract_surgery,
    "Second MRI":         _extract_second_mri,
    "12-Week MRI":        _extract_12week_mri,
    "Follow-up Flex Sig": _extract_flexsig,
    "Watch and Wait":     _extract_watch_wait,
    "Watch and Wait Dates": _extract_ww_dates,
}
```

### Helper Utilities

#### `_find_section(text, header) -> str`

Extracts text under a section header until the next known section. Used section boundaries:
```
Staging | Clinical Details | MDT Outcome | Patient Details | Cancer Target
```

#### `_find_dates(text) -> list[str]`

Finds all dates matching `DD/MM/YYYY` or `D/M/YY` (short dates auto-converted to full format with `20` prefix).

#### `_normalize_date(date_str) -> str`

Converts `D/M/YY` to `DD/MM/YYYY` by prepending `20` to two-digit years.

#### `_find_tnm(text) -> dict`

Extracts T, N, M staging. Two search strategies:
1. **Combined pattern**: `r'\b(T\d[a-d]?)\s*(N\d[a-c]?)\s*(M\d)'` -- matches `T3bN1M0` or `T3b N1 M0`.
2. **Individual patterns**: Separate `T\d[a-d]?`, `N\d[a-c]?`, `M\d` searches.

Returns `dict` of `{'t': (value, span), 'n': (value, span), 'm': (value, span)}`.

#### `_find_emvi(text) -> tuple | None`

Pattern: `r'EMVI\s*[\-:]?\s*(\+ve|positive|negative|\-ve|yes|no)'`

Normalises to `"Positive"` or `"Negative"`.

#### `_find_crm(text) -> tuple | None`

Two patterns:
1. `r'CRM\s*[\-:]?\s*(clear|involved|threatened|unsafe|positive|negative|\+ve|\-ve)'`
2. `r'CRM\s*[\-:]?\s*(\d+)\s*mm'` -- produces e.g. `"3mm"`.

Normalises involved/threatened/unsafe/positive/+ve to capitalised form; clear/negative/-ve to `"Clear"`.

#### `_find_psw(text) -> tuple | None`

Pattern: `r'(?:PSW|pelvic\s*side\s*wall?|peritoneal)\s*[\-:]?\s*(positive|negative|\+ve|\-ve|clear|involved)'`

Normalises to `"Positive"` or `"Negative"`.

### Complete Regex Pattern List by Group

#### Demographics

| Field               | Pattern                                                                  | Notes                            |
|---------------------|--------------------------------------------------------------------------|----------------------------------|
| `dob`               | `r'(\d{1,2}/\d{1,2}/\d{4})\s*\(a\)'`                                   | Falls back to date followed by "Age" |
| `initials`          | `r'([A-Z][A-Za-z\'\-]+(?:\s+[A-Za-z\'\-]+)+)\s*\(b\)'`                  | Falls back to all-caps name line |
| `mrn`               | `r'Hospital\s*Number:\s*(\d+)'`                                         |                                  |
| `nhs_number`        | `r'NHS\s*Number:\s*([\d\s\(\)c]+)'`                                     | Digits extracted via `re.sub(r'[^\d]', '', ...)` |
| `gender`            | `r'(Male\|Female)\s*\(?e?\)?'`                                          |                                  |
| `previous_cancer`   | `r'previous\s*cancer\|prior\s*(?:malignan\|cancer\|lymphoma\|leukaemia)\|...'` | Also extracts site/type |

#### Endoscopy

| Field                | Pattern                                                                   | Notes                            |
|----------------------|---------------------------------------------------------------------------|----------------------------------|
| `endoscopy_date`     | `r'(?:Colonoscopy\|Flexi\s*sig(?:moidoscopy)?\|Endoscopy)\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})'` | |
| `endoscopy_findings` | `r'(?:Colonoscopy\|Flexi\s*sig(?:moidoscopy)?)\s*(?:on\s*...)?[:\-]...\s*(.+?)(?=\n\n\|...)'` | Searches Clinical Details first, then full text. Min length 10 chars. |
| `endoscopy_type`     | `r'flexi\s*sig'` or `r'incomplete\s*colonoscopy'`                        | Only explicit mentions; inference left for LLM |

#### Histology

| Field           | Pattern                                                                 | Notes                            |
|-----------------|-------------------------------------------------------------------------|----------------------------------|
| `biopsy_result` | `r'Diagnosis:\s*([A-Z][A-Z\s\-,]+?)(?:\s*\n\|ICD)'`                     | Falls back to `r'Histo?(?:logy)?:\s*([A-Za-z\s]+?)(?:\.\|,\|\n)'` |
| `biopsy_date`   | `r'biops(?:y\|ied)\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})'`               |                                  |
| `mmr_status`    | `r'MMR\s*[\-:]?\s*(proficient\|deficient\|intact\|loss\|dMMR\|pMMR)'`    | Normalises to `"Proficient"` or `"Deficient"` |

#### Baseline MRI

| Field               | Pattern                                                              | Notes                             |
|----------------------|----------------------------------------------------------------------|-----------------------------------|
| `baseline_mri_date`  | `r'MRI\s*(?:pelvis\s*)?(?:on\s*)?(\d{1,2}/\d{1,2}/\d{2,4})\s*[:\-]...'` | Also scans Staging section as fallback |
| `baseline_mri_t`     | via `_find_tnm()` on MRI text block                                 |                                   |
| `baseline_mri_n`     | via `_find_tnm()` on MRI text block                                 |                                   |
| `baseline_mri_emvi`  | via `_find_emvi()` on MRI text block                                |                                   |
| `baseline_mri_crm`   | via `_find_crm()` on MRI text block                                 |                                   |
| `baseline_mri_psw`   | via `_find_psw()` on MRI text block                                 |                                   |

#### Baseline CT

| Field                        | Pattern                                                              | Notes                             |
|------------------------------|----------------------------------------------------------------------|-----------------------------------|
| `baseline_ct_date`           | `r'CT\s*(?:TAP\s*)?(?:on\s*)?(\d{1,2}/\d{1,2}/\d{2,4})\s*[:\-]...'` |                                   |
| `baseline_ct_t`              | via `_find_tnm()` on CT text block                                  | Fallback: staging line `r'staging[:\s]*(T\d...)'` |
| `baseline_ct_n`              | via `_find_tnm()` on CT text block                                  |                                   |
| `baseline_ct_m`              | via `_find_tnm()` on CT text block                                  | If not found: infers from `r'metastas[ei]s\|metastatic'` with negation check |
| `baseline_ct_emvi`           | via `_find_emvi()` on CT text block                                 |                                   |
| `baseline_ct_incidental`     | `r'incidental\|unexpected\|additionally\|also\s+(?:noted\|found)'`   | Second pass: `r'incidental\|enlarged\s+(?:retro)?peritoneal\s+nodes\|suspicious\s+lesion\|indeterminate'` |
| `baseline_ct_incidental_detail` | `r'((?:Mildly\s+)?enlarged[^.]+\|suspicious[^.]+\|indeterminate[^.]+)'` |                           |

**M-staging inference logic** (when no explicit M code found):
1. Search for `r'metastas[ei]s|metastatic'`.
2. If found, check for negation: `r'no\s+(?:distant\s+)?metastas|no\s+evidence\s+of\s+metastas'`.
3. If negation found: `M0`. Otherwise: `M1`.
4. If CT was done but no incidental findings mentioned: `baseline_ct_incidental = 'N'`.

#### MDT

| Field               | Pattern                                                                   | Notes                            |
|----------------------|---------------------------------------------------------------------------|----------------------------------|
| `first_mdt_date`     | `r'MDT Meeting Date:\s*(\d{1,2}/\d{1,2}/\d{4})'`                         | From prepended header            |
| `first_mdt_treatment`| `r'Outcome:\s*(.+?)(?=\n\n\|$)'`                                          | DOTALL match                     |
| `mdt_6week_date`     | All `r'MDT\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})'` matches, skip first date | Second chronological MDT date    |
| `mdt_12week_date`    | Same as above, third match                                               |                                  |

#### Chemotherapy

| Field          | Pattern                                                                         | Notes                            |
|----------------|---------------------------------------------------------------------------------|----------------------------------|
| `chemo_drugs`  | `r'\b(capecitabine\|oxaliplatin\|FOLFOX\|CAPOX\|5-?FU\|irinotecan\|FOLFIRI\|FOLFOXIRI)\b'` | All matches, deduplicated, uppercased |
| `chemo_goals`  | `r'palliative'` then `r'curative\|radical'`                                      | Priority: palliative first       |
| `chemo_cycles` | `r'(\d+)\s*(?:cycles?\|courses?)\s*(?:of)?\s*(?:chemo\|FOLFOX\|CAPOX)?'`         |                                  |

#### Immunotherapy

| Field         | Pattern                                                                        |
|---------------|--------------------------------------------------------------------------------|
| `immuno_drug` | `r'\b(pembrolizumab\|nivolumab\|ipilimumab\|atezolizumab\|dostarlimab)\b'`     |

#### Radiotherapy

| Field                    | Pattern                                                                     |
|--------------------------|-----------------------------------------------------------------------------|
| `radio_total_dose`       | `r'(\d+(?:\.\d+)?)\s*Gy'`                                                  |
| `radio_concomitant_chemo`| `r'concom(?:itant\|mittant)\s*(?:chemo(?:therapy)?)?\s*[\-:]?\s*(\w+)?'`     |
|                          | Fallback: `r'chemoradio'` -> `"Yes"`                                        |

#### CEA and Clinical

| Field       | Pattern                                   |
|-------------|-------------------------------------------|
| `cea_value` | `r'CEA\s*[\-:]?\s*(\d+(?:\.\d+)?)'`       |

#### Surgery

| Field           | Pattern                                                                              | Notes                     |
|-----------------|--------------------------------------------------------------------------------------|---------------------------|
| `surgery_date`  | `r'(?:surgery\|operation\|resection\|hemicolectomy\|colectomy\|APR)\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})'` | |
| `defunctioned`  | `r'defunction\|stoma\s*form'`                                                        |                           |
| `surgery_intent`| -- not extracted by regex --                                                         | Left for LLM              |

#### Second MRI

| Field             | Pattern                                                                 | Notes                                     |
|-------------------|-------------------------------------------------------------------------|-------------------------------------------|
| `second_mri_date` | All MRI mentions via `r'(?:repeat\s+\|2nd\s+\|second\s+)?MRI\s*...(\d{1,2}/\d{1,2}/\d{2,4})...'`, takes index [1] | |
| `second_mri_t`    | via `_find_tnm()`                                                       |                                           |
| `second_mri_n`    | via `_find_tnm()`                                                       |                                           |
| `second_mri_emvi` | via `_find_emvi()`                                                      |                                           |
| `second_mri_crm`  | via `_find_crm()`                                                       |                                           |
| `second_mri_psw`  | via `_find_psw()`                                                       |                                           |
| `second_mri_trg`  | `r'TRG\s*[\-:]?\s*(\d)'`                                               |                                           |

#### 12-Week MRI

| Field              | Pattern                                                                    | Notes                   |
|--------------------|----------------------------------------------------------------------------|-------------------------|
| `week12_mri_date`  | `r'(?:12\s*week\|third\|3rd)\s*MRI\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})\s*:?\s*(.*?)(?=\n\n\|$)'` | |
| `week12_mri_t`     | via `_find_tnm()`                                                          |                         |
| `week12_mri_n`     | via `_find_tnm()`                                                          |                         |
| `week12_mri_emvi`  | via `_find_emvi()`                                                         |                         |
| `week12_mri_crm`   | via `_find_crm()`                                                          |                         |
| `week12_mri_psw`   | via `_find_psw()`                                                          |                         |
| `week12_mri_trg`   | `r'TRG\s*[\-:]?\s*(\d)'`                                                  |                         |

#### Follow-up Flex Sig

| Field             | Pattern                                                                                   |
|-------------------|-------------------------------------------------------------------------------------------|
| `flexsig_date`    | `r'(?:flexi(?:ble)?\s*sig(?:moidoscopy)?\|flex\s*sig)\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})...'` |
| `flexsig_findings`| Text captured after the date match                                                        |

#### Watch and Wait

| Field             | Pattern                                                                          | Notes                     |
|-------------------|----------------------------------------------------------------------------------|---------------------------|
| `ww_entered_date` | `r'MDT\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4}).*?watch\s*(?:and\|&)\s*wait'`        | Date of W&W decision      |
| `ww_frequency`    | `r'(\d+)\s*(?:month\|week)(?:ly\|s)?'` (searched from W&W mention position)       |                           |
| `ww_reason`       | -- not extracted by regex --                                                     | Left for LLM              |

#### Watch and Wait Dates

Only runs if `watch\s*(?:and|&)\s*wait` is found in text.

| Field                | Pattern                                                                           | Notes         |
|----------------------|-----------------------------------------------------------------------------------|---------------|
| `ww_flexi_{1-4}_date`| All `r'(?:flexi...sig...)\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})'` matches, up to 4  |               |
| `ww_mri_{1-2}_date`  | All `r'MRI\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})'` matches, skip first (baseline)   | Up to 2       |

---

## 5. Clinical Context

**File**: `extractor/clinical_context.py`

Provides clinical reference text injected into LLM system prompts. Sources cited: RCPath G049, Radiopaedia, NHS standards, NICE NG151.

### Context Blocks

| Constant             | Topic                                          | Injected For Groups                        |
|----------------------|------------------------------------------------|--------------------------------------------|
| `_MRI_T`             | MRI Tumour staging (mrT1-T4b, substages)       | Baseline MRI, Baseline CT                  |
| `_MRI_N`             | MRI Nodal staging (mrN0-N2b, criteria)         | Baseline MRI, Baseline CT                  |
| `_CT_M`              | CT Metastasis staging (M0-M1c)                 | Baseline CT                                |
| `_EMVI`              | Extramural Vascular Invasion                   | Baseline MRI, Baseline CT, Second MRI, 12-Week MRI |
| `_CRM`               | Circumferential Resection Margin               | Baseline MRI, Second MRI, 12-Week MRI     |
| `_TRG`               | Tumour Regression Grade (0-3)                  | Second MRI, 12-Week MRI                   |
| `_STAGE_GROUPS`      | Stage groupings (Stage 0-IV)                   | Baseline MRI, Baseline CT                  |
| `_MMR`               | Mismatch Repair status                         | Histology                                  |
| `_ENDOSCOPY_CONTEXT` | Endoscopy type classification rules            | Endoscopy                                  |
| `_SURGERY_CONTEXT`   | Surgery types and intent classification        | Surgery                                    |
| `_WATCH_WAIT_CONTEXT`| W&W programme entry reasons                    | Watch and Wait                             |

### Group-to-Context Mapping (`_GROUP_CONTEXT`)

```python
{
    "Histology":     _MMR,
    "Baseline MRI":  _MRI_T + _MRI_N + _EMVI + _CRM + _STAGE_GROUPS,
    "Baseline CT":   _MRI_T + _MRI_N + _CT_M + _EMVI + _STAGE_GROUPS,
    "Second MRI":    _TRG + _EMVI + _CRM,
    "12-Week MRI":   _TRG + _EMVI + _CRM,
    "Endoscopy":     _ENDOSCOPY_CONTEXT,
    "Surgery":       _SURGERY_CONTEXT,
    "Watch and Wait": _WATCH_WAIT_CONTEXT,
}
```

Groups not listed (Demographics, MDT, Chemotherapy, Immunotherapy, Radiotherapy, CEA and Clinical, Follow-up Flex Sig, Watch and Wait Dates) receive no clinical context block.

### Abbreviations Constant (`ABBREVIATIONS`)

Injected into all LLM prompts. Contains:
```
CRT=chemoradiotherapy, TNT=total neoadjuvant therapy, SCRT=short-course radiotherapy,
LCCRT=long-course chemoradiotherapy, APR=abdominoperineal resection, LAR=low anterior resection,
AR=anterior resection, TME=total mesorectal excision, ISP=intersphincteric plane,
+ve=positive, -ve=negative, NAD=nothing abnormal detected, Hx=history, Bx=biopsy,
Dx=diagnosis, Rx=treatment, FS=flexi sig, CT TAP=CT thorax abdomen pelvis,
PET-CT=positron emission tomography CT, FDG=fluorodeoxyglucose, CEA=carcinoembryonic antigen,
DRE=digital rectal examination, MDT=multidisciplinary team, W&W=watch and wait.
```

### Public Function

```python
def get_context_for_group(group_name: str) -> str
```

Returns the clinical reference string for the group, or `""` if none is mapped.

---

## 6. Prompt Builder

**File**: `extractor/prompt_builder.py`

Constructs system and user prompts from per-group template files and the schema.

### Prompt Structure (What the LLM Sees)

The LLM receives a **system prompt** and a **user prompt**, structured as follows:

#### System Prompt

```
[1] Base system instructions (from system_base.txt)

[2] Group-specific instructions + clinical reference + few-shot example (from {group}.txt)
    OR, if no group file exists: clinical context from clinical_context.py

[3] Return JSON in this exact format:
{
  "field_key_1": {"value": "...", "reason": "...", "source_section": "(f)|(g)|(h)|null"},
  "field_key_2": {"value": "...", "reason": "...", "source_section": "(f)|(g)|(h)|null"}
}
```

#### User Prompt

```
Fields to extract:
- field_key_1: [Column Header] Extraction hint. MUST be one of: val1, val2, or null.
- field_key_2: [Column Header] Extraction hint.

Patient notes:
---
{relevant_text_sections_only}
---
```

### Section Filtering

The prompt builder does NOT send the full patient text to the LLM. It extracts only relevant sections based on the group.

#### `_GROUP_SECTIONS` Mapping

| Group                 | Sections Included          | Annotation Markers        |
|-----------------------|----------------------------|---------------------------|
| Endoscopy             | Clinical Details           | `(f)`                     |
| Baseline CT           | MDT Outcome                | `(h)`                     |
| Surgery               | MDT Outcome                | `(h)`                     |
| Watch and Wait        | MDT Outcome + Clinical     | `(h)`, `(f)`              |
| Histology             | Staging + MDT Outcome      | `(g)`, `(h)`              |
| Baseline MRI          | MDT Outcome                | `(h)`                     |
| Second MRI            | MDT Outcome                | `(h)`                     |
| 12-Week MRI           | MDT Outcome                | `(h)`                     |
| MDT                   | MDT Outcome + MDT Date     | `(h)`, `(i)`              |
| MDT 6-Week            | MDT Outcome                | `(h)`                     |
| MDT 12-Week           | MDT Outcome                | `(h)`                     |
| Chemotherapy          | MDT Outcome                | `(h)`                     |
| Immunotherapy         | MDT Outcome                | `(h)`                     |
| Radiotherapy          | MDT Outcome                | `(h)`                     |
| CEA and Clinical      | Clinical + MDT Outcome     | `(f)`, `(h)`              |
| Follow-up Flex Sig    | Clinical + MDT Outcome     | `(f)`, `(h)`              |
| Watch and Wait Dates  | Clinical + MDT Outcome     | `(f)`, `(h)`              |

#### `_SECTION_HEADERS` Mapping

| Marker | Regex Header Pattern                |
|--------|-------------------------------------|
| `(f)`  | `r'Clinical Details\(f\)'`          |
| `(g)`  | `r'Staging & Diagnosis\(g\)'`       |
| `(h)`  | `r'MDT Outcome\(h\)'`              |
| `(i)`  | `r'MDT Meeting Date'`              |

### `_extract_relevant_text(patient_text, group_name) -> str`

1. Always includes the header (Cancer Type + MDT date) from the first lines.
2. For each section marker in `_GROUP_SECTIONS[group_name]`, searches for the section header and extracts text until the next section boundary.
3. Falls back to full text if no sections are extracted.

### Public Functions

#### `build_prompt(patient_text, group) -> tuple[str, str]`

```python
def build_prompt(patient_text: str, group: dict) -> tuple[str, str]
```

Returns `(system_prompt, user_prompt)`.

Steps:
1. Builds the field list with `[Column Header]` + `prompt_hint` + allowed values from overrides.
2. Constructs JSON format example showing expected output structure.
3. Loads `system_base.txt` (cached).
4. Loads group-specific prompt file: `{group_name}.txt` (e.g., `endoscopy.txt`, `baseline_ct.txt`).
5. If no group file, falls back to `get_context_for_group()`.
6. Assembles system prompt: base + group-specific + JSON format.
7. Extracts relevant text via `_extract_relevant_text()`.
8. Assembles user prompt: field list + relevant patient text.

#### `build_all_prompts(patient_text) -> list[tuple[dict, str, str]]`

Returns `[(group, system_prompt, user_prompt), ...]` for all schema groups.

### Prompt File Loading

```python
_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'prompts')
```

Files are loaded and cached in `_prompt_cache`. Group file name is derived:
```python
group_file = group_name.lower().replace(' ', '_').replace('&', 'and') + '.txt'
```

Examples: `endoscopy.txt`, `baseline_ct.txt`, `surgery.txt`, `watch_and_wait.txt`, `cea_and_clinical.txt`.

---

## 7. LLM Client

**File**: `extractor/llm_client.py`

Manages communication with the LLM backend (either Anthropic Claude API or local Ollama).

### Constants

| Constant          | Value                                     | Description                        |
|-------------------|-------------------------------------------|------------------------------------|
| `OLLAMA_URL`      | `"http://localhost:11434"`                | Local Ollama endpoint              |
| `CLAUDE_URL`      | `"https://api.anthropic.com/v1/messages"` | Anthropic API endpoint             |
| `CLAUDE_MODEL`    | `"claude-haiku-4-5-20251001"`             | Default Claude model               |
| `TIMEOUT_SMALL`   | `30`                                      | Timeout for 8B and smaller models  |
| `TIMEOUT_LARGE`   | `180`                                     | Timeout for 14B+ models            |

### Suggested Models

```python
SUGGESTED_MODELS = [
    "qwen2.5:14b-instruct",
    "qwen3:8b",
    "qwen3.5:4b",
    "llama3.1:8b",
    "llama3.2:3b",
]
```

### Backend Selection

| Function                | Signature               | Description                                        |
|-------------------------|-------------------------|----------------------------------------------------|
| `get_backend()`         | `-> str`                | Returns `"claude"` or `"ollama"`                   |
| `set_backend(backend)`  | `(str) -> None`         | Must be `"claude"` or `"ollama"`                   |
| `get_ollama_model()`    | `-> str`                | Returns current Ollama model name                  |
| `set_ollama_model(model)`| `(str) -> None`        | Sets the Ollama model                              |
| `list_ollama_models()`  | `-> list[str]`          | Queries Ollama `/api/tags`                         |
| `check_ollama_available()`| `-> bool`             | True if Ollama is running with at least one model  |
| `check_claude_available()`| `-> bool`             | True if `ANTHROPIC_API_KEY` is set                 |
| `check_ollama()`        | `-> bool`               | Checks the currently selected backend              |

Default backend: `"claude"` if `ANTHROPIC_API_KEY` is set, otherwise `"ollama"`.
Default Ollama model: `"qwen3.5:4b"`.

### Model-Aware Parameter Table

| Parameter       | Claude                | Ollama (small: <=8B)           | Ollama (large: 14B+)           |
|-----------------|----------------------|-------------------------------|-------------------------------|
| `temperature`   | `0`                  | `0.1`                         | `0.1`                         |
| `seed`          | N/A                  | `42`                          | `42`                          |
| `num_ctx`       | N/A                  | `8192`                        | `16384`                       |
| `max_tokens`    | `4096`               | N/A (Ollama default)          | N/A (Ollama default)          |
| `format`        | N/A                  | `"json"`                      | `"json"`                      |
| `stream`        | `False`              | `True`                        | `True`                        |
| `think`         | N/A                  | `False` (only for qwen3/3.5)  | `False` (only for qwen3/3.5)  |
| Timeout         | `30s`                | `30s`                         | `180s`                        |

**Large model detection**: `any(x in model for x in ('14b', '32b', '70b'))`.

**Thinking model detection**: `any(x in model for x in ('qwen3:', 'qwen3.5:'))`. The `think: false` parameter is only sent for thinking-capable models because sending it to non-thinking models (e.g., qwen2.5) breaks JSON format enforcement.

### Stop Check Mechanism

```python
_stop_check = None  # Callable that returns True to abort

def set_stop_check(fn):
    global _stop_check
    _stop_check = fn
```

During Ollama streaming, each chunk checks `_stop_check()`. If it returns `True`, the response stream is closed and partial content is returned. Additionally, a time-based safety abort triggers if generation exceeds the timeout.

### Generate Function

```python
def generate(user_prompt: str, system_prompt: str = "") -> str
```

Dispatches to `_generate_claude()` or `_generate_ollama()` based on current backend.

#### Claude Generation

- Sends a non-streaming POST to `CLAUDE_URL`.
- Payload: `{model, max_tokens: 4096, temperature: 0, messages: [{role: "user", content}], system}`.
- Returns `content[0].text`.

#### Ollama Generation

- Sends a streaming POST to `OLLAMA_URL/api/chat`.
- Uses connection pooling via module-level `requests.Session`.
- Iterates over `resp.iter_lines()`, assembling content parts.
- Checks `_stop_check()` and `chunk.get('done')` each iteration.
- Safety timeout abort: `time.time() - start > timeout`.

### Environment Loading

The module reads `.env` from the project root at import time, setting environment variables via `os.environ.setdefault()`.

---

## 8. Response Parser

**File**: `extractor/response_parser.py`

Parses raw LLM response strings into `FieldResult` dictionaries and performs the verbatim check algorithm.

### Public Function

#### `parse_llm_response(raw_response, group, raw_cells=None) -> dict[str, FieldResult]`

```python
def parse_llm_response(raw_response: str, group: dict,
                       raw_cells: list | None = None) -> dict[str, FieldResult]
```

Steps:
1. Extracts expected keys and field types from the group schema.
2. Identifies freeform cells: cells where `row` is in `{4, 5, 6, 7}`.
3. Calls `_extract_json()` to parse the LLM's JSON response.
4. For each expected field key:
   - Extracts `value`, `reason`, `source_section` from the parsed JSON.
   - Normalises null-like strings (`"null"`, `"none"`, `"n/a"`, `"missing"`, `""`) to `None`.
   - Runs spell checking on text-type fields.
   - Executes the **verbatim check algorithm** (see below).
5. Returns `dict[str, FieldResult]`.

### The Verbatim Check Algorithm

This is the core provenance algorithm that determines whether an LLM-extracted value can be traced back to source text.

```
For each non-null value:
  1. Default confidence_basis = "freeform_inferred" (low confidence)
  2. Set source_snippet = source_section annotation from LLM

  3. QUOTED TEXT EXTRACTION:
     Search the LLM's "reason" field for quoted strings: r"['\"]([^'\"]{3,})['\"]"
     If found, use the LONGEST quoted string as source_snippet
     (only if longer than current source_snippet)

  4. STEP 1 -- Source Snippet Check:
     If source_snippet exists:
       For each freeform cell (rows 4,5,6,7):
         If source_snippet.lower() is found in cell.text.lower():
           -> confidence_basis = "freeform_verbatim"
           -> source_cell = {row, col}
           -> STOP

  5. STEP 2 -- Normalised Value Check (fallback):
     If still "freeform_inferred" AND value exists:
       val_lower = value.strip().lower()
       For each freeform cell:
         If val_lower is found in cell.text.lower():
           -> confidence_basis = "freeform_verbatim"
           -> source_cell = {row, col}
           -> source_snippet = value.strip()
           -> STOP

  6. Cap source_snippet at 200 chars (append ellipsis if truncated)
```

The algorithm promotes confidence from `"freeform_inferred"` (low) to `"freeform_verbatim"` (medium) only when either the quoted source text or the extracted value itself can be found verbatim in a freeform cell.

### JSON Extraction (`_extract_json`)

Three parsing strategies tried in order:

1. **Direct parse**: `json.loads(raw)` after stripping Qwen3 `<think>...</think>` blocks.
2. **Fenced code block**: `r'```(?:json)?\s*\n?(.*?)\n?```'` -- extracts JSON from markdown code fences.
3. **Greedy object match**: `r'\{.*\}'` with DOTALL -- finds the first JSON-like object.

Returns `None` if all strategies fail.

### Spell Checking

Uses the `pyspellchecker` library with a custom medical vocabulary. Applied only to `text`-type fields.

**Custom medical terms loaded** (complete list):
```
adenocarcinoma, carcinoma, colonoscopy, sigmoidoscopy, flexisigmoidoscopy,
flexi, sig, ileocecal, rectosigmoid, mesorectal, circumferential,
neoadjuvant, chemoradiotherapy, capecitabine, oxaliplatin, folfox, capox,
pembrolizumab, nivolumab, immunotherapy, radiotherapy, chemotherapy,
deficient, proficient, emvi, crm, psw, trg, tnm, mri, mdt,
nhs, mrn, dob, icd, cea, dre, hpb, tnt,
rectal, rectum, sigmoid, caecum, colon, hepatic, splenic,
transverse, ascending, descending, peritoneal, retroperitoneal,
ampulla, neoplasm, malignant, differentiated, moderately, poorly,
ulceration, mucinous, polypoid, sessile, pedunculated,
metastasis, metastatic, palliative, curative, adjuvant,
stoma, defunctioned, hemicolectomy, colectomy, resection,
gy, ebrt, papillon, concomitant, concomittant,
gleason, prostate, polyneuropathy, demyelinating, stenosis,
ct, pet, ivc, seg
```

**Spell check logic** (`_check_spelling`):
1. Extract words matching `r'[a-zA-Z]{3,}'` (3+ letter words only).
2. Skip all-uppercase abbreviations of 5 or fewer characters.
3. Check remaining words against the dictionary (including custom medical terms).
4. If misspellings found, prepend `"[Possible misspelling: word1, word2] "` to the reason (max 3 words reported).

---

## 9. Coverage

**File**: `extractor/coverage.py`

Computes what percentage of the source document's text was matched by extracted fields.

### Public Function

#### `compute_coverage(patient: PatientBlock) -> None`

```python
def compute_coverage(patient: PatientBlock) -> None
```

Mutates `patient` in place, setting `coverage_map`, `coverage_pct`, and `coverage_stats`.

### The Coverage Span Algorithm

```
1. IDENTIFY CONTENT CELLS:
   Filter raw_cells to exclude header rows {0, 2, 4, 6} and empty cells.
   Compute total_chars = sum of all content cell text lengths.

2. INITIALISE COVERAGE MAP:
   For each content cell, create a single "unused" span: {start: 0, end: len(text), used: False}.
   Key: "{row},{col}".

3. MARK USED SPANS:
   For each extraction group -> each field:
     - Skip if value is None.
     - Skip if confidence_basis == "freeform_inferred" (inferred fields don't count).
     - Skip if source_snippet or source_cell is missing.
     - Find the cell text for source_cell.
     - Find ALL occurrences of source_snippet (case-insensitive) in the cell text.
     - For each occurrence, add a {start: idx, end: idx+len, used: True} span.
   Count inferred fields separately.

4. MERGE SPANS (per cell):
   Call _merge_spans() to flatten overlapping spans.

5. COMPUTE STATISTICS:
   Sum used and unused character counts from merged spans.
   used_pct = (total_used / total_chars) * 100
   unused_pct = (total_unused / total_chars) * 100
```

### Span Merging Algorithm (`_merge_spans`)

```
1. Find max_end across all spans.
2. Build character-level boolean array: char_used[0..max_end-1].
3. For each span where used=True, mark those positions as True.
   (Used takes priority: if a character is covered by both a "used" and "unused" span,
    it is counted as "used".)
4. Collapse consecutive runs of same-boolean-value into spans.
5. Return list of non-overlapping {start, end, used} spans.
```

### Key Constants

```python
_HEADER_ROWS = {0, 2, 4, 6}  # Section header rows (excluded from coverage)
```

### Output Written to PatientBlock

| Field             | Type                | Content                                        |
|-------------------|---------------------|-------------------------------------------------|
| `coverage_map`    | `dict[str, list]`   | `{"{row},{col}": [{start, end, used}, ...]}`    |
| `coverage_pct`    | `float`             | Percentage of source chars matched (0.0-100.0)  |
| `coverage_stats`  | `dict`              | `{used_pct, unused_pct, inferred_fields, total_chars}` |

---

## 10. HTML Preview

**File**: `extractor/html_preview.py`

Renders a `PatientBlock`'s raw cells as interactive HTML for the review panel.

### Public Function

#### `render_html_preview(patient) -> str`

```python
def render_html_preview(patient) -> str
```

Returns an HTML string. If no `raw_cells`, returns `<div class="preview-empty">No source data available</div>`.

### 6-Section Layout

The HTML mirrors the original DOCX table structure:

| Section | Content                            | Row Sources | HTML Structure                     |
|---------|------------------------------------|-------------|------------------------------------|
| 1       | Meeting Date                       | Row -1      | Single div                         |
| 2       | Patient Details + Cancer Targets   | Rows 0-1    | Two-column: details (0,0) + cancer dates (0,1) |
| 3       | Staging & Diagnosis                | Rows 2-3    | Two-column if 2+ staging cells, else full-width |
| 4       | Clinical Details                   | Rows 4-5    | Full-width, header skipped         |
| 5       | MDT Outcome                        | Rows 6-7    | Full-width, header skipped         |

### Section Building Logic

**Meeting Date (Section 1)**:
Priority chain for the meeting date value:
1. `patient.mdt_date`
2. `patient.extractions["MDT"]["first_mdt_date"]` or `patient.extractions["Demographics"]["first_mdt_date"]`
3. Synthetic cell at `row=-1` containing `"MDT Meeting Date"` (regex extraction: `r'(\d{1,2}/\d{1,2}/\d{4})'`)

**Patient Details (Section 2)**:
- Left column: `cell_text(1, 0)` (demographics).
- Right column: `cell_text(1, 1)` or `cell_text(0, 1)` (cancer target dates).
- **Privacy**: Full patient name is replaced with `patient.initials` in the details text. The replacement logic checks each line: if the line has no colon, doesn't start with a digit, isn't "male"/"female", and doesn't contain "age", it's assumed to be a name and replaced.

**Staging (Section 3)**:
- Collects cells from row 3, sorted by column index.
- If 2+ cells: two-column layout.
- If 1 cell: full-width layout.
- If 0 cells: dash placeholder.

**Clinical Details (Section 4)**:
- Iterates rows 4 and 5.
- Skips cells where text contains both "clinical" and "details" (header detection).
- Joins remaining cell texts with newlines.

**MDT Outcome (Section 5)**:
- Iterates rows 6 and 7.
- Skips cells where text contains both "mdt" and "outcome" (header detection).
- Joins remaining cell texts with newlines.

### Cell HTML Rendering (`_cell_html`)

Each cell produces:
```html
<div class="cell-content{width_class}" data-row="{row}" data-col="{col}" data-group="{group}">
  {content with coverage spans}
</div>
```

Data attributes:
- `data-row`, `data-col`: Source cell coordinates for JS interaction.
- `data-group`: Extraction group name (for colouring), set from `_build_extraction_map()`.

### Coverage HTML (`_build_coverage_html`)

Wraps text characters in `<span>` tags based on coverage spans:

```html
<span class="cov-used">matched text</span>
<span class="cov-unused">unmatched text</span>
```

These classes are invisible by default, toggled via JavaScript in the review panel.

Algorithm:
1. Sanitise text (Unicode normalisation).
2. Sort spans by start position.
3. For gaps between spans, emit `cov-unused`.
4. For each span, emit `cov-used` or `cov-unused` based on `span.used`.
5. Trailing text after last span gets `cov-unused`.

### Extraction Map (`_build_extraction_map`)

Builds `dict[str, str]` mapping `"{row},{col}"` to `group_name` by iterating all extractions and checking `source_cell`. Only fields with non-null values and a source_cell are included.

### Unicode Sanitisation (`_sanitize`)

| Unicode | Replacement |
|---------|-------------|
| `\u2013` (en-dash) | `-` |
| `\u2014` (em-dash) | `-` |
| `\u2018` (left single quote) | `'` |
| `\u2019` (right single quote) | `'` |
| `\u201c` (left double quote) | `"` |
| `\u201d` (right double quote) | `"` |
| `\u2026` (ellipsis) | `...` |
| `\u00a0` (non-breaking space) | ` ` |
| `\u2022` (bullet) | `-` |
| `\ufffd` (replacement char) | `?` |

### Key Constants

```python
_HEADER_ROWS = {0, 2, 4, 6}  # Blue header rows, not content
```

---

## 11. Prompt Templates

**Directory**: `config/prompts/`

### `system_base.txt`

The base system prompt injected into every LLM call:

```
Extract clinical data from NHS MDT notes. Return ONLY valid JSON.

Rules:
- Return null if a value is not mentioned and cannot be reasonably inferred.
- If you infer a value from descriptive text (not a formal code), explain what text
  you based it on in the reason.
- Dates in DD/MM/YYYY format.
- Copy text verbatim where possible.
- For each field return: value, reason (1 sentence), source_section (annotation marker or null).

Annotation markers: (f)=Clinical Details, (g)=Staging/Histology, (h)=MDT Outcome/Imaging, (i)=MDT date.
```

### `endoscopy.txt`

```
Extract endoscopy data from the Clinical Details(f) section.

Endoscopy type rules:
- "Colonoscopy complete": caecum reached, complete exam, or colonoscopy without "incomplete"
- "Incomplete colonoscopy": unable to pass, could not reach caecum, failed, stenosis
- "Flexi sig": flexible sigmoidoscopy, FS
- If just "Colonoscopy:" with findings and no qualifier, report "Colonoscopy complete"

Example input:
"Colonoscopy 15/03/2024: circumferential tumour at 8cm, biopsied"

Example output:
{
  "endoscopy_date": {"value": "15/03/2024", "reason": "Date stated before findings", "source_section": "(f)"},
  "endoscopy_type": {"value": "Colonoscopy complete", "reason": "Colonoscopy performed without incomplete qualifier", "source_section": "(f)"},
  "endoscopy_findings": {"value": "circumferential tumour at 8cm, biopsied", "reason": "Verbatim text after Colonoscopy:", "source_section": "(f)"}
}
```

### `baseline_ct.txt`

```
Extract CT staging data from MDT Outcome(h) section.

CT staging reference:
- T staging: T1-T4 (from TNM pattern like T3N1M0, or "T3" alone)
- N staging: N0-N2 (from TNM pattern, or infer from lymph node description)
  "mesorectal lymph nodes" without count = likely N1
  "multiple/extensive lymph nodes" = likely N2
- M staging: M0=no metastasis, M1a=one organ, M1b=multiple organs, M1c=peritoneal
  "no distant metastases" = M0. "liver mets" = M1a. "lung and liver" = M1b
  "suspicious for lung metastases" = M1a (single organ)
- EMVI: Positive or Negative

If you infer a staging value from descriptive text rather than a formal TNM code,
explain what text you based it on in the reason, quoting the exact words.

Example input:
"CT TAP 01/02/2025: Rectal mass T3N1. Liver metastasis in segment 6. No lung lesions. EMVI negative."

Example output:
{
  "baseline_ct_date": {"value": "01/02/2025", ...},
  "baseline_ct_t": {"value": "T3", ...},
  "baseline_ct_n": {"value": "N1", ...},
  "baseline_ct_m": {"value": "M1a", "reason": "[REF] Liver metastasis in single organ = M1a", ...},
  "baseline_ct_emvi": {"value": "Negative", ...},
  "baseline_ct_incidental": {"value": "N", ...},
  "baseline_ct_incidental_detail": {"value": null, ...}
}
```

### `surgery.txt`

```
Extract surgery details from MDT Outcome(h) section.

Surgery types: APR, LAR, AR, Hemicolectomy, TME, Hartmann's
Intent: "Curative" or "Palliative"
Defunctioned: "Yes" if stoma formed/defunctioned mentioned, "No" otherwise

Example input:
"Plan: Neoadjuvant CRT then LAR with TME. Defunctioning ileostomy likely."

Example output:
{
  "surgery_date": {"value": null, "reason": "No surgery date stated, only planned", ...},
  "defunctioned": {"value": "Yes", "reason": "Defunctioning ileostomy mentioned", ...},
  "surgery_intent": {"value": "Curative", "reason": "LAR with TME after neoadjuvant = curative intent", ...}
}
```

### `watch_and_wait.txt`

```
Extract Watch and Wait (W&W) programme details.

W&W is offered when a patient achieves complete clinical response (cCR) after treatment.
Entry reasons: "Complete clinical response", "Near-complete response", "Patient preference"
Look for: "watch and wait", "W&W", "active surveillance", "organ preservation"

Example input:
"Following excellent response to CRT, MRI shows no residual tumour. Flexi sig: scar only.
 Entered W&W programme 15/06/2025, 3-monthly surveillance."

Example output:
{
  "ww_entered_date": {"value": "15/06/2025", ...},
  "ww_reason": {"value": "Complete clinical response", ...},
  "ww_frequency": {"value": "3-monthly", ...},
  "ww_progression_date": {"value": null, ...},
  "ww_progression_site": {"value": null, ...}
}
```

---

## 12. Configuration

**File**: `config/__init__.py`

### Public Functions

| Function                          | Signature                           | Description                                                    |
|-----------------------------------|-------------------------------------|----------------------------------------------------------------|
| `load_schema()`                   | `-> dict`                           | Loads `config/field_schema.yaml` (cached)                      |
| `get_groups()`                    | `-> list[dict]`                     | Returns all group definitions from schema                      |
| `get_all_fields()`               | `-> list[dict]`                     | Returns all fields with `group_name` appended                  |
| `load_overrides()`               | `-> dict`                           | Loads `config/field_overrides.yaml` (cached)                   |
| `save_overrides(overrides)`      | `(dict) -> None`                    | Persists overrides to YAML                                     |
| `get_field_override(field_key)`  | `(str) -> dict`                     | Returns override for a field (e.g., `allowed_values`)          |

### Schema Structure

The schema YAML defines groups, each containing fields:
```yaml
groups:
  - name: "Demographics"
    fields:
      - key: "dob"
        type: "date"
        excel_header: "Demographics: Date of Birth"
        prompt_hint: "Patient date of birth in DD/MM/YYYY"
      - key: "initials"
        type: "text"
        ...
```

### Override Structure

```yaml
overrides:
  endoscopy_type:
    allowed_values:
      - "Colonoscopy complete"
      - "Incomplete colonoscopy"
      - "Flexi sig"
  mmr_status:
    allowed_values:
      - "Proficient"
      - "Deficient"
```

When `allowed_values` are present, the prompt builder appends `"MUST be one of: val1, val2, or null."` to the field's extraction hint.

---

## Cross-Module Data Flow Summary

```
                     parse_docx()
                         |
                    PatientBlock
                    (raw_text, raw_cells)
                         |
            +------------+------------+
            |                         |
     regex_extract()           build_prompt()
     per-group dispatch        section filtering
            |                  prompt assembly
     FieldResult(high)              |
     (structured_verbatim     generate()
      or freeform_verbatim)   Claude or Ollama
            |                       |
            |               parse_llm_response()
            |               JSON extraction
            |               verbatim check
            |               spell check
            |                       |
            |               FieldResult(medium/low)
            |               (freeform_verbatim
            |                or freeform_inferred)
            |                       |
            +----------+------------+
                       |
              patient.extractions
              {group: {field: FieldResult}}
                       |
              +--------+--------+
              |                 |
      compute_coverage()  render_html_preview()
      span merging        6-section layout
      stats               coverage highlighting
              |                 |
      coverage_map         HTML string
      coverage_pct
      coverage_stats
```

---

*End of technical reference.*
