# MDT Data Extractor

A locally-hosted web application that extracts structured patient data from NHS Multidisciplinary Team (MDT) outcome proforma Word documents and outputs it as a standardised Excel spreadsheet.

All processing happens on your machine. No data leaves the local environment.

## Features

- **DOCX Upload** — Drag-and-drop Word document upload with automatic patient detection
- **Local LLM Extraction** — Uses Ollama (Qwen, Llama) or Claude API for zero data leakage
- **Config-Driven** — `field_schema.yaml` defines all 88 fields across 16 clinical categories
- **Confidence System** — Green (structured verbatim), Orange (freeform verbatim), Red (inferred) colour coding with full provenance tracking
- **Field Provenance** — Every field links back to the exact source cell it came from
- **Coverage Tracking** — Toggle to see unused text with percentage coverage badge
- **G049 Clinical Reference** — RCPath G049 definitions (TNM, MMR, EMVI, CRM, TRG) injected into LLM prompts for clinical accuracy, with `[G049]` citation in reasoning
- **Self-Contained Excel** — Single `.xlsx` with 3 sheets (data + metadata + raw cells) enables full review on any machine without DOCX or LLM
- **Cross-Machine Workflow** — Extract on a powerful PC, review/edit on a laptop
- **Human-in-the-Loop** — Clinicians review, edit, and re-export before clinical use
- **Unique Patient IDs** — `{MDT_date}_{initials}_{gender}_{MRN/NHS}` format for reliable tracking
- **Parallel Extraction** — 1-3 concurrent LLM workers with live progress monitoring
- **Analytics Dashboard** — Charts for cancer types, treatments, and confidence distribution
- **Audit Trail** — Every extraction and manual edit is logged

## Prerequisites

- **Python 3.11+**
- **Ollama** — https://ollama.com (or Anthropic API key for Claude)

## Setup

### 1. Install Ollama and pull a model

```bash
# Download and install Ollama from https://ollama.com
# Then pull a model:
ollama pull qwen3:8b              # Recommended: fast, good quality
ollama pull qwen2.5:14b-instruct  # Higher quality, needs more RAM
ollama pull qwen3.5:4b            # Lightweight option
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the application

```bash
# Start Ollama
ollama serve

# In a separate terminal:
python app.py
```

Open http://localhost:5000 in your browser.

### Claude API (optional)

To use Claude instead of Ollama, set your API key:

```bash
set ANTHROPIC_API_KEY=sk-ant-...   # Windows
export ANTHROPIC_API_KEY=sk-ant-...  # Linux/Mac
python app.py
```

Switch between backends in the UI settings.

## Usage Workflow

### Extraction (powerful PC)
1. **Upload** — Drag your `.docx` file onto the landing page
2. **Configure** — Set patient limit and parallel workers (1-3)
3. **Extract** — Watch live progress with per-patient timers and group tracking
4. **Review** — Browse patients, check confidence colours, edit fields inline
5. **Export** — Download the self-contained Excel file

### Review (laptop, no DOCX needed)
1. **Import** — Upload the Excel file on any machine
2. **Preview** — Document previews regenerate from embedded raw cell data
3. **Review** — Full confidence colours, source highlighting, coverage toggle
4. **Edit & Re-export** — Make changes and export updated Excel

## Confidence System

| Colour | Basis | Meaning |
|--------|-------|---------|
| Green | `structured_verbatim` | Extracted by regex from a structured cell |
| Orange | `freeform_verbatim` | LLM extracted, value exists verbatim in source text |
| Red | `freeform_inferred` | LLM inferred — value not found verbatim in source |
| Grey | `edited` | Clinician manually overrode the value |

Every field tracks its `source_cell` (row/col), `source_snippet` (matched text), and `reason` (including `[G049]` citation when clinical reference was used).

## Project Structure

```
Clinical AI/
├── app.py                        # Flask app — routes, SSE progress, extraction
├── models.py                     # FieldResult, PatientBlock, ExtractionSession
├── audit.py                      # JSON audit trail
├── config/
│   ├── __init__.py               # Schema loaders
│   └── field_schema.yaml         # 88 fields, 16 groups (single source of truth)
├── parser/
│   └── docx_parser.py            # DOCX parsing, cell dedup, patient splitting
├── extractor/
│   ├── regex_extractor.py        # Regex pass + unique_id assignment
│   ├── llm_client.py             # Ollama / Claude API backend
│   ├── prompt_builder.py         # Prompt construction with G049 injection
│   ├── response_parser.py        # LLM JSON parsing + verbatim check
│   ├── clinical_context.py       # G049 RCPath definitions
│   ├── coverage.py               # Unused text tracking (span-union)
│   └── preview_renderer.py       # Pillow PNG rendering
├── export/
│   └── excel_writer.py           # 3-sheet Excel (data + metadata + raw cells)
├── static/
│   ├── css/style.css             # Dark theme
│   └── js/app.js                 # Frontend logic
├── templates/                    # Jinja2 (index, process, review, analytics)
├── tests/                        # 78 pytest tests
├── docs/                         # Design specs and implementation plans
└── G049-*.pdf                    # RCPath reference document
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11+ / Flask |
| LLM | Ollama (Qwen, Llama) or Claude API |
| DOCX Parsing | python-docx |
| Excel | openpyxl |
| Preview | Pillow |
| Frontend | Bootstrap 5 (dark theme), vanilla JS, Chart.js |
| Config | YAML |
| Testing | pytest |

## Clinical Safety

- **Data Residency** — All data stays on localhost. No external API calls (unless Claude API is opted in).
- **Human-in-the-Loop** — Clinician reviews all extractions before export.
- **Provenance** — Every field traces back to its source cell and extraction method.
- **G049 Citation** — LLM marks when clinical reference definitions drove a classification.
- **Audit Trail** — Every extraction and edit logged with timestamps.
- **Not a Medical Device** — This is a data extraction aid, not clinical decision support.

## Running Tests

```bash
python -m pytest tests/ -v    # 78 tests
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Cannot connect to Ollama" | Run `ollama serve` in a terminal |
| "Model not found" | Run `ollama pull qwen3:8b` |
| Extraction slow | Close other apps, check `ollama ps` for GPU. Try `qwen3.5:4b` for speed. |
| 0 patients detected | Check document format matches MDT proforma structure |
| Previews show old layout | Re-upload DOCX — previews are cached PNGs |
| Port 5000 in use | `python app.py --port 5001` |
