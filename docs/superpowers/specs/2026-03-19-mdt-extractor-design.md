# MDT Data Extractor — Design Specification

## Overview

A locally-hosted browser application that extracts structured patient data from NHS Multidisciplinary Team (MDT) outcome proforma Word documents and outputs it as a 97-column Excel spreadsheet matching the hackathon ground truth format.

All processing happens on the user's machine. No data leaves the local environment.

## Problem

Cancer patients in the NHS are discussed in weekly MDT meetings. Patient histories, treatments, and outcomes are circulated as Word documents. Extracting meaningful data from these documents for audit, research, or clinical review currently requires manual data entry — a laborious, error-prone process.

## Solution

A config-driven extraction pipeline that:
1. Accepts a `.docx` upload via browser UI
2. Parses and splits the document into per-patient text blocks
3. Uses a local LLM (Ollama + Llama 3.1 8B) to extract structured fields grouped by clinical category
4. Presents results in an editable dashboard with confidence scoring
5. Exports to the 97-column Excel format matching the ground truth template

---

## Architecture

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11+ / Flask |
| LLM | Ollama + Llama 3.1 8B (local, quantized ~5GB) |
| DOCX parsing | python-docx |
| Excel export | openpyxl |
| Frontend | Bootstrap 5, Chart.js, DataTables |
| Config | field_schema.yaml |

### System Components

```
Browser UI (localhost:5000)
    │
    ├── Upload endpoint (/upload)
    │       │
    │       ▼
    ├── Document Parser (python-docx)
    │       │ splits into per-patient text blocks
    │       ▼
    ├── Patient Detector
    │       │ identifies patients, returns count
    │       ▼
    ├── Extraction Engine
    │       │ for each patient × each schema group:
    │       │   → builds prompt from field_schema.yaml
    │       │   → calls Ollama REST API (localhost:11434)
    │       │   → parses JSON response (values + confidence)
    │       ▼
    ├── Review API (/patients, /patients/<id>, /patients/<id>/edit)
    │       │ serves extracted data, accepts edits
    │       ▼
    ├── Export Engine (/export)
    │       │ maps field keys → Excel columns via schema
    │       ▼
    └── Analytics API (/analytics)
            │ computes stats from in-memory data
            ▼
        Chart.js renders in browser
```

### Data Flow

1. **Upload**: User drags `.docx` file onto landing page
2. **Parse**: `python-docx` reads the document, splits on patient boundaries (NHS number pattern, name headers, or structural markers in the Word doc)
3. **Detect**: Returns patient count + list of patient identifiers (initials, NHS numbers)
4. **Extract**: For each patient, iterates through schema groups. Each group generates one LLM prompt. LLM returns JSON with field values and confidence (high/medium/low) per field.
5. **Store**: Results held in memory as dataclasses (see Data Model below). No database.
6. **Review**: Browser UI displays results in editable table, filtered by category tabs. Clinician corrects errors.
7. **Export**: On request, flattens all patient data into the 97-column Excel format using openpyxl, mapping fields to columns via `field_schema.yaml`.

---

## field_schema.yaml — Single Source of Truth

This file drives prompts, UI, and export. Structure:

```yaml
groups:
  - name: Demographics
    description: "Patient demographic information"
    fields:
      - key: dob
        excel_column: 1
        excel_header: "Demographics: \nDOB(a)"
        prompt_hint: "Date of birth. Format: DD/MM/YYYY"
        type: date
      - key: initials
        excel_column: 2
        excel_header: "Demographics: Initials(b)"
        prompt_hint: "Patient initials (e.g., AO, BK)"
        type: string
      - key: mrn
        excel_column: 3
        excel_header: "Demographics: MRN(c)"
        prompt_hint: "Medical Record Number (numeric)"
        type: string
      - key: nhs_number
        excel_column: 4
        excel_header: "Demographics: \nNHS number(d)"
        prompt_hint: "NHS number (10-digit numeric, may start with NNN)"
        type: string
      - key: gender
        excel_column: 5
        excel_header: "Demographics: \nGender(e)"
        prompt_hint: "Patient gender: Male or Female"
        type: string
      - key: previous_cancer
        excel_column: 6
        excel_header: "Demographics:\nPrevious cancer \n(y, n) \nif yes, where(f)"
        prompt_hint: "Previous cancer history: Yes or No"
        type: string
      - key: previous_cancer_site
        excel_column: 7
        excel_header: "Demographics: \nState site of previous cancer(f)"
        prompt_hint: "Site of previous cancer if applicable, or N/A"
        type: string

  - name: Endoscopy
    description: "Endoscopy procedure details"
    fields:
      - key: endoscopy_date
        excel_column: 8
        excel_header: "Endoscopy: date(f)"
        prompt_hint: "Date of endoscopy procedure. Format: DD/MM/YYYY"
        type: date
      - key: endoscopy_type
        excel_column: 9
        excel_header: "Endosopy type: flexi sig, incomplete colonoscopy, colonoscopy complete - if gets to ileocecal valve(f)"
        prompt_hint: "Type: flexi sig, incomplete colonoscopy, or colonoscopy complete (reaches ileocecal valve)"
        type: string
      - key: endoscopy_findings
        excel_column: 10
        excel_header: "Endoscopy: Findings(f)"
        prompt_hint: "Clinical findings from endoscopy as described in notes"
        type: text

  - name: Histology
    description: "Biopsy and histology results"
    fields:
      - key: biopsy_result
        excel_column: 11
        excel_header: "Histology: Biopsy result(g)"
        prompt_hint: "Histology biopsy result (e.g., ADENOCARCINOMA, NOT OTHERWISE SPECIFIED)"
        type: text
      - key: biopsy_date
        excel_column: 12
        excel_header: "Histology: Biopsy date(g)"
        prompt_hint: "Date of biopsy. Format: DD/MM/YYYY"
        type: date
      - key: mmr_status
        excel_column: 13
        excel_header: "Histology: \nMMR status(g/h)"
        prompt_hint: "Mismatch Repair status: Proficient or Deficient"
        type: string

  - name: Baseline MRI
    description: "Baseline MRI imaging results"
    fields:
      - key: baseline_mri_date
        excel_column: 14
        excel_header: "Baseline MRI: date(h)"
        prompt_hint: "Date of baseline MRI. Format: DD/MM/YYYY"
        type: date
      - key: baseline_mri_t
        excel_column: 15
        excel_header: "Baseline MRI: mrT(h)"
        prompt_hint: "MRI tumour staging (mrT): T1, T2, T3, T3a/b/c/d, T4, T4a/b"
        type: string
      - key: baseline_mri_n
        excel_column: 16
        excel_header: "Baseline MRI: mrN(h)"
        prompt_hint: "MRI nodal staging (mrN): N0, N1, N2"
        type: string
      - key: baseline_mri_emvi
        excel_column: 17
        excel_header: "Baseline MRI: mrEMVI(h)"
        prompt_hint: "Extramural vascular invasion on MRI: Positive or Negative"
        type: string
      - key: baseline_mri_crm
        excel_column: 18
        excel_header: "Baseline MRI: mrCRM(h)"
        prompt_hint: "Circumferential resection margin on MRI: Involved, Threatened, or Clear (with distance in mm if stated)"
        type: string
      - key: baseline_mri_psw
        excel_column: 19
        excel_header: "Baseline MRI: mrPSW(h)"
        prompt_hint: "Peritoneal sidewall involvement on MRI"
        type: string

  - name: Baseline CT
    description: "Baseline CT imaging results"
    fields:
      - key: baseline_ct_date
        excel_column: 20
        excel_header: "Baseline CT: Date(h)"
        prompt_hint: "Date of baseline CT. Format: DD/MM/YYYY"
        type: date
      - key: baseline_ct_t
        excel_column: 21
        excel_header: "Baseline CT: T(h)"
        prompt_hint: "CT tumour staging (T)"
        type: string
      - key: baseline_ct_n
        excel_column: 22
        excel_header: "Baseline CT: N(h)"
        prompt_hint: "CT nodal staging (N)"
        type: string
      - key: baseline_ct_emvi
        excel_column: 23
        excel_header: "Baseline CT: EMVI(h)"
        prompt_hint: "Extramural vascular invasion on CT"
        type: string
      - key: baseline_ct_m
        excel_column: 24
        excel_header: "Baseline CT: M(h)"
        prompt_hint: "Metastasis staging (M): M0 or M1 (with site if stated)"
        type: string
      - key: baseline_ct_incidental
        excel_column: 25
        excel_header: "Baseline CT: Incidental findings requiring follow up? Y/N(h)"
        prompt_hint: "Incidental findings on CT requiring follow-up: Yes or No"
        type: string
      - key: baseline_ct_incidental_detail
        excel_column: 26
        excel_header: "Baseline CT: Detail incidental finding(h)"
        prompt_hint: "Description of incidental finding if applicable"
        type: text

  - name: MDT
    description: "MDT meeting decisions and treatment planning"
    fields:
      - key: first_mdt_date
        excel_column: 27
        excel_header: "1st MDT: date(i)"
        prompt_hint: "Date of first MDT meeting. Format: DD/MM/YYYY"
        type: date
      - key: first_mdt_treatment
        excel_column: 28
        excel_header: "1st MDT: Treatment approach"
        prompt_hint: "Treatment approach: TNT, downstaging chemotherapy, downstaging nCRT, downstaging short-course RT, Papillon +/- EBRT, or straight to surgery"
        type: string
      - key: mdt_6week_date
        excel_column: 55
        excel_header: "MDT (after 6 week: Date"
        prompt_hint: "Date of MDT meeting after 6-week assessment. Format: DD/MM/YYYY"
        type: date
      - key: mdt_6week_decision
        excel_column: 56
        excel_header: "MDT (after 6 week: Decision"
        prompt_hint: "MDT decision after 6-week assessment"
        type: text
      - key: mdt_12week_date
        excel_column: 66
        excel_header: "MDT (after 12 week): Date"
        prompt_hint: "Date of MDT meeting after 12-week assessment. Format: DD/MM/YYYY"
        type: date
      - key: mdt_12week_decision
        excel_column: 67
        excel_header: "MDT (after 12 week): Decision"
        prompt_hint: "MDT decision after 12-week assessment"
        type: text

  - name: Chemotherapy
    description: "Chemotherapy treatment details"
    fields:
      - key: chemo_goals
        excel_column: 29
        excel_header: "Chemotherapy: Treatment goals (curative, palliative)"
        prompt_hint: "Treatment goals: curative or palliative"
        type: string
      - key: chemo_drugs
        excel_column: 30
        excel_header: "Chemotherapy: Drugs"
        prompt_hint: "Chemotherapy drug names (e.g., FOLFOX, CAPOX, capecitabine)"
        type: string
      - key: chemo_cycles
        excel_column: 31
        excel_header: "Chemotherapy: Cycles"
        prompt_hint: "Number of chemotherapy cycles"
        type: string
      - key: chemo_dates
        excel_column: 32
        excel_header: "Chemotherapy: Dates"
        prompt_hint: "Start and end dates of chemotherapy"
        type: string
      - key: chemo_breaks
        excel_column: 33
        excel_header: "Chemotherapy: Breaks"
        prompt_hint: "Any breaks in chemotherapy treatment and reasons"
        type: text

  - name: Immunotherapy
    description: "Immunotherapy treatment details"
    fields:
      - key: immuno_dates
        excel_column: 34
        excel_header: "Immunotherapy: Dates"
        prompt_hint: "Dates of immunotherapy treatment"
        type: string
      - key: immuno_drug
        excel_column: 35
        excel_header: "Immunotherapy"
        prompt_hint: "Immunotherapy drug name (e.g., pembrolizumab, nivolumab)"
        type: string

  - name: Radiotherapy
    description: "Radiotherapy treatment details"
    fields:
      - key: radio_total_dose
        excel_column: 36
        excel_header: "Radiotheapy: Total dose"
        prompt_hint: "Total radiotherapy dose in Gy"
        type: string
      - key: radio_boost
        excel_column: 37
        excel_header: "Radiotheapy: Boost"
        prompt_hint: "Radiotherapy boost details"
        type: string
      - key: radio_dates
        excel_column: 38
        excel_header: "Radiotherapy: Dates"
        prompt_hint: "Start and end dates of radiotherapy"
        type: string
      - key: radio_concomitant_chemo
        excel_column: 39
        excel_header: "Radiotheapy: Concomittant chemotherapy"
        prompt_hint: "Concurrent chemotherapy given with radiotherapy: drug name or None"
        type: string

  - name: CEA and Clinical
    description: "CEA markers and clinical examination"
    fields:
      - key: cea_date
        excel_column: 40
        excel_header: "CEA: Date"
        prompt_hint: "Date of CEA blood test. Format: DD/MM/YYYY"
        type: date
      - key: cea_value
        excel_column: 41
        excel_header: "CEA: Value"
        prompt_hint: "CEA value (numeric, in ng/mL or ug/L)"
        type: string
      - key: dre_date
        excel_column: 42
        excel_header: "CEA: DRE date"
        prompt_hint: "Date of Digital Rectal Examination. Format: DD/MM/YYYY"
        type: date
      - key: dre_finding
        excel_column: 43
        excel_header: "CEA: DRE finding"
        prompt_hint: "Findings from Digital Rectal Examination"
        type: text

  - name: Surgery
    description: "Surgical intervention details"
    fields:
      - key: defunctioned
        excel_column: 44
        excel_header: "Surgery: Defunctioned?"
        prompt_hint: "Was patient defunctioned (stoma formed)? Yes or No"
        type: string
      - key: surgery_date
        excel_column: 45
        excel_header: "Surgery: Date of surgery"
        prompt_hint: "Date of surgery. Format: DD/MM/YYYY"
        type: date
      - key: surgery_intent
        excel_column: 46
        excel_header: "Surgery: Intent, pre-neoadjuvant therapy"
        prompt_hint: "Surgical intent and relationship to neoadjuvant therapy"
        type: text

  - name: Second MRI
    description: "Second MRI assessment results"
    fields:
      - key: second_mri_date
        excel_column: 47
        excel_header: "2nd MRI: Date"
        prompt_hint: "Date of second MRI. Format: DD/MM/YYYY"
        type: date
      - key: second_mri_pathway
        excel_column: 48
        excel_header: "2nd MRI: Patient pathway status"
        prompt_hint: "Patient pathway status at time of second MRI"
        type: string
      - key: second_mri_t
        excel_column: 49
        excel_header: "2nd MRI: mrT"
        prompt_hint: "MRI tumour staging on second scan (mrT)"
        type: string
      - key: second_mri_n
        excel_column: 50
        excel_header: "2nd MRI: mrN"
        prompt_hint: "MRI nodal staging on second scan (mrN)"
        type: string
      - key: second_mri_emvi
        excel_column: 51
        excel_header: "2nd MRI: mrEMVI"
        prompt_hint: "Extramural vascular invasion on second MRI"
        type: string
      - key: second_mri_crm
        excel_column: 52
        excel_header: "2nd MRI: mrCRM"
        prompt_hint: "Circumferential resection margin on second MRI"
        type: string
      - key: second_mri_psw
        excel_column: 53
        excel_header: "2nd MRI: mrPSW"
        prompt_hint: "Peritoneal sidewall involvement on second MRI"
        type: string
      - key: second_mri_trg
        excel_column: 54
        excel_header: "2nd MRI: mrTRG score"
        prompt_hint: "Tumour Regression Grade on second MRI (1-5)"
        type: string

  - name: 12-Week MRI
    description: "12-week MRI follow-up results"
    fields:
      - key: week12_mri_date
        excel_column: 57
        excel_header: "12 week MRI: Date"
        prompt_hint: "Date of 12-week MRI. Format: DD/MM/YYYY"
        type: date
      - key: week12_mri_t
        excel_column: 58
        excel_header: "12 week MRI: mrT"
        prompt_hint: "MRI tumour staging at 12 weeks (mrT)"
        type: string
      - key: week12_mri_n
        excel_column: 59
        excel_header: "12 week MRI: mrN"
        prompt_hint: "MRI nodal staging at 12 weeks (mrN)"
        type: string
      - key: week12_mri_emvi
        excel_column: 60
        excel_header: "12 week MRI: mrEMVI"
        prompt_hint: "Extramural vascular invasion at 12 weeks"
        type: string
      - key: week12_mri_crm
        excel_column: 61
        excel_header: "12 week MRI: mrCRM"
        prompt_hint: "Circumferential resection margin at 12 weeks"
        type: string
      - key: week12_mri_psw
        excel_column: 62
        excel_header: "12 week MRI: mrPSW"
        prompt_hint: "Peritoneal sidewall involvement at 12 weeks"
        type: string
      - key: week12_mri_trg
        excel_column: 63
        excel_header: "12 week MRI: mrTRG score"
        prompt_hint: "Tumour Regression Grade at 12 weeks (1-5)"
        type: string

  - name: Follow-up Flex Sig
    description: "Follow-up flexible sigmoidoscopy"
    fields:
      - key: flexsig_date
        excel_column: 64
        excel_header: "Flex sig: Date"
        prompt_hint: "Date of follow-up flexible sigmoidoscopy. Format: DD/MM/YYYY"
        type: date
      - key: flexsig_findings
        excel_column: 65
        excel_header: "Flex sig: Fidnings"
        prompt_hint: "Findings from follow-up flexible sigmoidoscopy"
        type: text

  - name: Watch and Wait
    description: "Watch and wait surveillance programme"
    fields:
      - key: ww_entered_date
        excel_column: 68
        excel_header: "Watch and wait: Entered watch + wait, date of MDT ?"
        prompt_hint: "Date of MDT where watch and wait was decided. Format: DD/MM/YYYY"
        type: date
      - key: ww_reason
        excel_column: 69
        excel_header: "Watch and wait: Why did they enter wait (with what intent)"
        prompt_hint: "Reason for entering watch and wait (e.g., complete clinical response)"
        type: text
      - key: ww_frequency
        excel_column: 70
        excel_header: "Watch and wait: Frequency?"
        prompt_hint: "Frequency of watch and wait surveillance (e.g., 3-monthly, 6-monthly)"
        type: string
      - key: ww_progression_date
        excel_column: 71
        excel_header: "Watch and wait: Date of \nprogression"
        prompt_hint: "Date of disease progression if applicable. Format: DD/MM/YYYY"
        type: date
      - key: ww_progression_site
        excel_column: 72
        excel_header: "Watch and wait: Site of \nprogression"
        prompt_hint: "Site of disease progression (e.g., local, liver, lung)"
        type: string
      - key: ww_death_date
        excel_column: 73
        excel_header: "Watch and wait: Date of death"
        prompt_hint: "Date of death if applicable. Format: DD/MM/YYYY"
        type: date

  - name: Watch and Wait Dates
    description: "Longitudinal watch and wait surveillance dates (MRI and flexisigmoidoscopy)"
    fields:
      - key: ww_start_date
        excel_column: 74
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Date entered watch and wait"
        prompt_hint: "Date entered watch and wait programme. Format: DD/MM/YYYY"
        type: date
      - key: ww_flexi_1_date
        excel_column: 75
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Flexisigmoidoscopy date"
        prompt_hint: "1st flexisigmoidoscopy date in watch and wait. Format: DD/MM/YYYY"
        type: date
      - key: ww_flexi_1_due
        excel_column: 76
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Due date next"
        prompt_hint: "Due date for next flexisigmoidoscopy after 1st"
        type: date
      - key: ww_flexi_2_date
        excel_column: 77
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Flexisigmoidoscopy date"
        prompt_hint: "2nd flexisigmoidoscopy date. Format: DD/MM/YYYY"
        type: date
      - key: ww_flexi_2_due
        excel_column: 78
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Due date next"
        prompt_hint: "Due date for next flexisigmoidoscopy after 2nd"
        type: date
      - key: ww_flexi_3_date
        excel_column: 79
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Flexisigmoidoscopy date"
        prompt_hint: "3rd flexisigmoidoscopy date. Format: DD/MM/YYYY"
        type: date
      - key: ww_flexi_3_due
        excel_column: 80
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Due date next"
        prompt_hint: "Due date for next flexisigmoidoscopy after 3rd"
        type: date
      - key: ww_flexi_4_date
        excel_column: 81
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Flexisigmoidoscopy date"
        prompt_hint: "4th flexisigmoidoscopy date. Format: DD/MM/YYYY"
        type: date
      - key: ww_flexi_4_due
        excel_column: 82
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Due date next"
        prompt_hint: "Due date for next flexisigmoidoscopy after 4th"
        type: date
      - key: ww_mri_1_date
        excel_column: 83
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: MRI Date"
        prompt_hint: "1st MRI date in watch and wait. Format: DD/MM/YYYY"
        type: date
      - key: ww_mri_1_due
        excel_column: 84
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Due date next"
        prompt_hint: "Due date for next MRI after 1st"
        type: date
      - key: ww_mri_2_date
        excel_column: 85
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: MRI Date"
        prompt_hint: "2nd MRI date in watch and wait. Format: DD/MM/YYYY"
        type: date
      - key: ww_mri_2_due
        excel_column: 86
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Due date next"
        prompt_hint: "Due date for next MRI after 2nd"
        type: date
      - key: ww_mri_3_date
        excel_column: 87
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: MRI Date"
        prompt_hint: "3rd MRI date in watch and wait. Format: DD/MM/YYYY"
        type: date
      - key: ww_mri_3_due
        excel_column: 88
        excel_header: "MRI and flexisigmoidoscopy watch and wait dates: Due date next"
        prompt_hint: "Due date for next MRI after 3rd"
        type: date
```

Note: Excel columns 89-97 are unnamed/empty in the ground truth template and are reserved for future use.

### How the schema drives each component:

- **Prompt generation**: For each group, build: "Extract the following fields from this patient text: {field.key}: {field.prompt_hint} for each field in group. Return JSON."
- **LLM response parsing**: Validate returned keys match `field.key` values in the group
- **UI table**: Category tabs = group names. Table rows = fields in selected group. Column headers from `field.prompt_hint` or a display name.
- **Excel export**: For each field, write value to `field.excel_column` using `field.excel_header` as the header row.

---

## Data Model

In-memory Python dataclasses — no database.

```python
@dataclass
class FieldResult:
    value: str | None          # Extracted value, or None if not found
    confidence: str            # "high", "medium", or "low"
    edited: bool = False       # True if clinician manually changed the value
    original_value: str | None = None  # Pre-edit value (for audit trail)

@dataclass
class PatientBlock:
    id: str                    # e.g., "patient_001"
    initials: str              # e.g., "AO"
    nhs_number: str            # e.g., "9990000001"
    raw_text: str              # Full source text from the Word document
    extractions: dict[str, dict[str, FieldResult]]
    # Structure: { "Demographics": { "dob": FieldResult, ... }, "Endoscopy": { ... }, ... }

@dataclass
class ExtractionSession:
    file_name: str
    upload_time: str
    patients: list[PatientBlock]
    status: str                # "uploading", "parsing", "extracting", "complete"
    progress: dict             # {"current_patient": 12, "total": 50, "current_group": "Baseline MRI"}
```

The `ExtractionSession` is held as a module-level singleton during the Flask app lifetime. One session at a time (no concurrent uploads).

---

## API Contracts

### POST `/upload`
- **Request**: `multipart/form-data` with `.docx` file
- **Response**: `{"status": "ok", "patients_detected": 50, "patient_list": [{"id": "patient_001", "initials": "AO", "nhs_number": "9990000001"}, ...]}`

### POST `/extract`
- **Request**: `{}` (triggers extraction of the uploaded session)
- **Response**: `{"status": "started"}`

### GET `/progress` (SSE endpoint)
- **Response**: Server-Sent Events stream
- **Events**: `{"current_patient": 12, "total": 50, "current_group": "Baseline MRI", "completed_patients": [{"id": "patient_001", "confidence_summary": {"high": 5, "medium": 1, "low": 1}}]}`

### GET `/patients`
- **Response**: `{"patients": [{"id": "patient_001", "initials": "AO", "nhs_number": "9990000001", "gender": "Male", "cancer_type": "Colorectal", "confidence_summary": {"high": 52, "medium": 18, "low": 10}}]}`
- **Query params**: `?cancer_type=Colorectal&search=AO`

### GET `/patients/<id>`
- **Response**: `{"id": "patient_001", "raw_text": "...", "extractions": {"Demographics": {"dob": {"value": "26/05/1970", "confidence": "high", "edited": false}, ...}, ...}}`

### PUT `/patients/<id>/fields`
- **Request**: `{"group": "Demographics", "field": "previous_cancer", "value": "Yes"}`
- **Response**: `{"status": "ok", "old_value": "No", "new_value": "Yes"}`
- Logs the edit to audit trail. Sets `edited: true` and preserves `original_value`.

### POST `/patients/<id>/re-extract`
- **Request**: `{"groups": ["Demographics", "Histology"]}` (optional — omit to re-run all groups)
- **Response**: `{"status": "started"}`
- Re-runs LLM extraction for the specified groups on a single patient. Overwrites previous extraction (but audit trail retains history).

### GET `/export`
- **Response**: `.xlsx` file download

### GET `/analytics`
- **Response**: `{"cancer_types": {"Colorectal": 48, "Other": 2}, "treatments": {...}, "staging": {...}, "confidence": {"high": 2731, "medium": 692, "low": 424}}`

---

## User Interface

### Pages

#### 1. Landing Page (`/`)
- Drag-and-drop upload zone for `.docx` files
- Privacy badge: "All processing happens locally"
- No login required

#### 2. Processing Page (`/process`)
- Shows after upload
- Displays: file name, size, detected patient count
- "Start Extraction" button
- Live progress view during extraction:
  - Overall progress bar (X / N patients — count is dynamic from parsing step)
  - Current patient: which category is being processed (badges light up)
  - Completed patients log with per-patient confidence summary
- Uses Server-Sent Events (SSE) via Flask's `Response(stream_with_context(...), mimetype='text/event-stream')` for live updates

#### 3. Review Dashboard (`/review`)
- **Left sidebar**: Patient list with:
  - Initials, gender, NHS number
  - Cancer type label
  - Confidence summary badges (% high/med/low)
  - Filterable by cancer type dropdown
  - Searchable by NHS number or initials
- **Category tabs**: Demographics | Endoscopy | Histology | Baseline MRI | Baseline CT | MDT | Chemotherapy | Radiotherapy | Surgery | Follow-up | Watch & Wait
- **Data table** (for selected patient + category):
  - Columns: Field name | Extracted value (editable) | Confidence badge
  - Confidence colour coding: green border + HIGH badge, amber + MED, red + LOW
  - Click any value cell to edit inline
- **Source text panel**: Bottom collapsible panel showing the raw document text for the selected patient, so clinicians can verify extractions against the source
- **Confidence filter**: Dropdown to show All / Low confidence only / Medium + Low

#### 4. Analytics Page (`/analytics`)
- Charts rendered with Chart.js:
  - Cancer type distribution (pie/bar)
  - Treatment approach distribution
  - Staging breakdown (T, N, M)
  - Confidence distribution across all patients
- Filterable by cancer type
- Nice-to-have, not core

#### 5. Export
- Button in nav bar, available from review page
- Downloads `.xlsx` file matching the 97-column ground truth format
- Includes all patients, all fields, respecting any manual edits

### UI Tech Choices
- **Bootstrap 5**: Dark theme, responsive grid, form components
- **DataTables**: Sortable, searchable tables (for patient list and field tables)
- **Chart.js**: Lightweight charting for analytics
- **Jinja2**: Server-side templates (Flask default), avoids SPA complexity

---

## LLM Integration

### Ollama Setup
- Ollama runs locally on `http://localhost:11434`
- Model: `llama3.1:8b` (Q4_K_M quantization, ~5GB)
- Install: `ollama pull llama3.1:8b`
- API endpoint: `POST http://localhost:11434/api/generate`
- Parameters: `temperature: 0`, `format: "json"`, `num_ctx: 8192` (increase to 16384 if patient text blocks are large)
- Check GPU usage: `ollama ps` (shows if model is loaded on GPU vs CPU)

### Prompt Strategy

For each patient × each schema group, generate a prompt:

```
You are a clinical data extraction assistant. Extract the following fields from the patient's MDT notes below.

For each field, provide:
- "value": the extracted value, or null if not mentioned
- "confidence": "high" if explicitly stated, "medium" if inferred from context, "low" if uncertain or ambiguous

Return ONLY valid JSON in this exact format:
{
  "dob": {"value": "26/05/1970", "confidence": "high"},
  "initials": {"value": "AO", "confidence": "high"},
  ...
}

Fields to extract:
- dob: Date of birth. Format: DD/MM/YYYY
- initials: Patient initials (e.g., AO, BK)
- mrn: Medical Record Number (numeric)
[... generated from field_schema.yaml group fields ...]

Patient MDT Notes:
---
[patient text block inserted here]
---
```

### Prompt Generation (pseudocode)

```python
def build_prompt(patient_text: str, group: SchemaGroup) -> str:
    field_list = "\n".join(
        f"- {f.key}: {f.prompt_hint}" for f in group.fields
    )
    json_example = ", ".join(
        f'"{f.key}": {{"value": "...", "confidence": "high|medium|low"}}'
        for f in group.fields
    )
    return PROMPT_TEMPLATE.format(
        field_list=field_list,
        json_example=json_example,
        patient_text=patient_text
    )
```

### Response Parsing

1. Extract JSON from LLM response (handle markdown code blocks, trailing text)
2. Validate all expected keys are present
3. For missing keys, set `{"value": null, "confidence": "low"}`
4. **Programmatic confidence override**: After LLM self-reports confidence, apply validation rules:
   - Date fields that fail DD/MM/YYYY parsing → override to "low"
   - Fields where LLM returned a value but said "low" → keep as "low" (flag for clinician)
   - Fields where value is null → force confidence to "low" regardless of LLM response
   - This hybrid approach (LLM self-assessment + programmatic validation) is more reliable than LLM confidence alone, especially on 8B models
5. If JSON parsing fails entirely, log error and set all fields to null/low for that group — do not crash

### Error Handling

- **Ollama not running**: Check connectivity at startup, show clear error on landing page
- **Malformed LLM response**: Retry once with a stricter prompt. If still fails, mark all fields as null/low confidence.
- **Timeout**: 60-second timeout per LLM call. On timeout, skip group, mark fields as null/low.

---

## Document Parsing

### Splitting Strategy

The Word document contains a variable number of patients (50 in the hackathon dataset) in a proforma format. The parser must:

1. Read the `.docx` with `python-docx`
2. Identify patient boundaries — likely by:
   - NHS number pattern (NNN XXX XXXX)
   - Repeating header structure in the proforma
   - Page breaks or section markers
3. Extract each patient's text block as a string
4. Return a list of `PatientBlock(id, identifier, raw_text)` objects

**Important**: The exact splitting logic depends on the document structure and must be tuned after inspecting the actual `.docx` file. During implementation, the first task is to download the hackathon dataset (`data/hackathon-mdt-outcome-proformas.docx` from the GitHub repo) and inspect its structure to determine patient boundaries. Common patterns in NHS MDT proformas:
- Each patient starts with a header row containing NHS number and demographics
- Patients may be separated by horizontal rules, page breaks, or section headers
- The proforma may use tables (one row per patient) or flowing paragraphs

The parser should expose a `/debug/raw-text` endpoint during development that shows the full extracted text, so boundary detection can be debugged visually.

### Fallback

If automatic splitting fails, offer a manual mode where the user can paste individual patient text blocks.

---

## Export

### Excel Generation

Using `openpyxl`:

1. Create workbook with sheet named "Prototype V1" (matching ground truth)
2. Write header row: for each field in schema (ordered by `excel_column`), write `excel_header`
3. For each patient, write one row: for each field, write the value (or empty if null) to the correct column
4. Apply basic formatting: date columns formatted as dates, text columns auto-width
5. Save and return as download

---

## Audit Trail

Log every action for clinical safety / DTAC traceability:

```json
{"timestamp": "2026-03-19T14:23:01", "action": "extraction", "patient_id": "NNN9990001", "group": "Demographics", "fields_extracted": 7, "confidence_summary": {"high": 5, "medium": 1, "low": 1}}
{"timestamp": "2026-03-19T14:25:12", "action": "manual_edit", "patient_id": "NNN9990001", "field": "previous_cancer", "old_value": "No", "new_value": "Yes", "edited_by": "clinician"}
{"timestamp": "2026-03-19T14:30:00", "action": "export", "patients_exported": 50, "format": "xlsx"}
```

Stored as a JSON-lines file at `logs/audit.jsonl` (single file, appended per session). Viewable from the UI via the Audit Trail button.

---

## Project Structure

```
clinical-ai/
├── app.py                  # Flask app entry point, routes, SSE endpoint
├── models.py               # Dataclasses: FieldResult, PatientBlock, ExtractionSession
├── audit.py                # Audit trail logger (writes to logs/audit.jsonl)
├── config/
│   └── field_schema.yaml   # Single source of truth for all fields
├── parser/
│   ├── __init__.py
│   └── docx_parser.py      # Word document parsing + patient splitting
├── extractor/
│   ├── __init__.py
│   ├── llm_client.py       # Ollama HTTP client
│   ├── prompt_builder.py   # Generates prompts from schema
│   └── response_parser.py  # Parses and validates LLM JSON responses
├── export/
│   ├── __init__.py
│   └── excel_writer.py     # Generates 97-column Excel output
├── static/
│   ├── css/
│   │   └── style.css       # Custom styles (dark theme overrides)
│   └── js/
│       └── app.js          # Frontend logic (upload, editing, filtering)
├── templates/
│   ├── base.html           # Base template (nav, Bootstrap, scripts)
│   ├── index.html          # Landing page (upload)
│   ├── process.html        # Processing/progress page
│   ├── review.html         # Review dashboard
│   └── analytics.html      # Analytics page
├── tests/
│   ├── test_schema.py      # Validates field_schema.yaml completeness and column uniqueness
│   └── test_export.py      # Round-trip test: mock data → Excel → read back → verify
├── data/
│   └── (uploaded files and exports stored here)
├── logs/
│   └── audit.jsonl         # Audit trail (append-only)
├── requirements.txt
└── README.md
```

---

## Dependencies (requirements.txt)

```
flask>=3.0
python-docx>=1.1
openpyxl>=3.1
pyyaml>=6.0
requests>=2.31
```

No other dependencies. Chart.js, Bootstrap, and DataTables loaded via CDN or bundled in static/.

---

## Troubleshooting Guide

### Ollama Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| "Cannot connect to Ollama" on startup | Ollama service not running | Run `ollama serve` in a terminal, or start Ollama app |
| "Model not found" error | Model not pulled | Run `ollama pull llama3.1:8b` |
| Extraction extremely slow (>2min per patient) | Insufficient RAM, model swapping to disk | Close other applications. Check `Task Manager` for RAM usage. Consider using `llama3.1:8b` with Q4_K_S (smaller quantization). |
| Ollama crashes mid-extraction | Out of memory | Reduce model size: `ollama pull llama3.2:3b` as fallback (less accurate but lighter) |
| LLM returns garbled/non-JSON output | Prompt too long for context window (default 8K) | Increase `num_ctx` in `llm_client.py` (e.g., 16384). Or reduce fields per group by splitting large groups. Check prompt + patient text total tokens. |
| Ollama running on CPU instead of GPU | CUDA not detected or GPU driver issue | Run `ollama ps` to check. Ensure NVIDIA drivers are installed. Restart Ollama after driver install. CPU inference is ~10x slower. |

### Document Parsing Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| "0 patients detected" | Patient boundary detection failed | Check the Word doc structure. The parser looks for NHS number patterns or repeating headers. May need to adjust regex in `docx_parser.py` |
| Patient text blocks are merged/split wrong | Different proforma format than expected | Inspect the raw text output (`/debug/raw-text` endpoint if enabled). Adjust splitting logic in `docx_parser.py` |
| "Cannot read .docx file" | Corrupted file or `.doc` (old format) | Ensure the file is `.docx` (Office 2007+). Convert `.doc` files in Word first. |
| Tables in Word doc not parsed | `python-docx` reads paragraphs and tables separately | Check `docx_parser.py` — it should iterate both `doc.paragraphs` and `doc.tables` |

### Excel Export Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| Columns don't match ground truth | Schema `excel_column` values misaligned | Compare `field_schema.yaml` column numbers against `hackathon-database-prototype.xlsx` headers. Fix column numbers in schema. |
| Dates show as numbers in Excel | openpyxl wrote raw datetime without format | Check `excel_writer.py` — date cells need `number_format = 'DD/MM/YYYY'` |
| Empty Excel file exported | No extraction data in memory | Ensure extraction completed before exporting. Check `/review` page has data. |
| "Permission denied" saving Excel | File is open in another program | Close the previous export file in Excel before re-exporting |

### Frontend Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| Progress bar stuck | SSE connection dropped | Refresh the page. Check Flask console for errors. |
| Edits not saving | JavaScript error or API failure | Open browser DevTools (F12) → Console tab. Check for errors. Verify Flask is still running. |
| Category tabs empty | Schema group has no extracted data for this patient | Check if the LLM returned null for all fields in that group. Re-run extraction for that patient if needed. |
| Page not loading | Flask crashed | Check the terminal running Flask for error traceback. Restart with `python app.py` |

### General

| Problem | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError` | Missing Python package | Run `pip install -r requirements.txt` |
| Port 5000 already in use | Another app on that port | Kill the other process or change port: `python app.py --port 5001` |
| Everything was working, now nothing loads | Ollama auto-updated or Python env changed | Check `ollama --version`, re-pull model. Check `pip list` matches requirements.txt. |
| `python` command not found (Windows) | Python not on PATH, or aliased as `py` | Use `py app.py` instead, or add Python to PATH via Windows Settings → Environment Variables. `py -m pip install -r requirements.txt` for packages. |

---

## DTAC & Clinical Safety Considerations

- **Data residency**: All data stays on localhost. No external API calls. Compliant by design.
- **Human-in-the-loop**: Clinician must review and can edit all extractions before export. The system is a tool, not a decision-maker.
- **Confidence scoring**: Red/amber/green flags draw attention to uncertain extractions.
- **Audit trail**: Every extraction and manual edit is logged with timestamps.
- **Not a medical device**: This tool assists data entry. It does not provide clinical decision support, diagnosis, or treatment recommendations. It is a data extraction aid.

---

## Future Enhancements (Out of Scope for Hackathon)

- SNOMED CT coding for tumour morphology/topography
- HL7 FHIR resource generation (Patient, Observation, Condition)
- Multi-user support with authentication
- Database backend for persistent storage across sessions
- Support for additional document formats (PDF, scanned images with OCR)
- Larger LLM models when hardware allows (70B for higher accuracy)
