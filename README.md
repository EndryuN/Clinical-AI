# MDT Data Extractor

A locally-hosted web application that extracts structured patient data from NHS Multidisciplinary Team (MDT) outcome proforma Word documents and outputs it as a standardised Excel spreadsheet.

All processing happens on your machine. No data leaves the local environment.

## Features

- **DOCX Upload** — Drag-and-drop Word document upload with automatic patient detection
- **Local LLM Extraction** — Uses Ollama (Llama 3.1 8B) running locally for zero data leakage
- **Config-Driven** — `field_schema.yaml` defines all 88 fields across 16 clinical categories
- **Confidence Scoring** — Each extracted field is rated HIGH/MEDIUM/LOW with colour-coded display
- **Human-in-the-Loop** — Clinicians review and edit extractions before export
- **Category Filtering** — Browse data by clinical category (Demographics, MRI, Treatment, etc.)
- **Cancer Type Filtering** — Filter patient list by cancer type
- **Excel Export** — Generates 97-column Excel matching the ground truth template
- **Analytics Dashboard** — Charts for cancer types, treatments, and confidence distribution
- **Audit Trail** — Every extraction and manual edit is logged for clinical safety

## Prerequisites

- **Python 3.11+**
- **Ollama** — https://ollama.com

## Setup

### 1. Install Ollama and pull the model

```bash
# Download and install Ollama from https://ollama.com
# Then pull the model (default is qwen2.5:14b-instruct):
ollama pull qwen2.5:14b-instruct

# Other recommended models for testing:
ollama pull qwen3:8b
ollama pull qwen3.5:4b
ollama pull llama3.1:8b
```

### 2. Install Python dependencies

```bash
cd "Clinical AI"
pip install -r requirements.txt
```

### 3. Place your data

Put your MDT outcome proforma `.docx` file in the `data/` directory (or upload via the web UI).

### 4. Run the application

```bash
# Make sure Ollama is running
ollama serve

# In a separate terminal:
python app.py
```

Open http://localhost:5000 in your browser.

## Usage Workflow

1. **Upload** — Drag your `.docx` file onto the landing page
2. **Parse** — System detects patients automatically (e.g., "50 patients found")
3. **Extract** — Click "Start Extraction" — watch live progress as each patient's data is extracted
4. **Review** — Browse patients in the sidebar, switch category tabs, edit any field inline
5. **Export** — Download the completed Excel spreadsheet

## Project Structure

```
Clinical AI/
├── app.py                  # Flask app — all routes and SSE
├── models.py               # Dataclasses: FieldResult, PatientBlock, ExtractionSession
├── audit.py                # Audit trail logger
├── config/
│   ├── __init__.py         # Schema loader utility
│   └── field_schema.yaml   # 88 fields, 16 groups — single source of truth
├── parser/
│   └── docx_parser.py      # Word document parsing + patient splitting
├── extractor/
│   ├── llm_client.py       # Ollama HTTP client
│   ├── prompt_builder.py   # Builds prompts from schema
│   └── response_parser.py  # Parses LLM JSON + confidence overrides
├── export/
│   └── excel_writer.py     # Generates 97-column Excel
├── static/
│   ├── css/style.css       # Dark theme
│   └── js/app.js           # Frontend logic
├── templates/              # Jinja2 templates (5 pages)
├── tests/                  # Schema validation + export round-trip tests
└── docs/                   # Design spec and implementation plan
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11+ / Flask |
| LLM | Ollama + Llama 3.1 8B (local) |
| DOCX Parsing | python-docx |
| Excel Export | openpyxl |
| Frontend | Bootstrap 5 (dark), Chart.js, DataTables |
| Config | YAML (field_schema.yaml) |

## DTAC & Clinical Safety

- **Data Residency** — All data stays on localhost. No external API calls.
- **Human-in-the-Loop** — Clinician reviews all extractions before export.
- **Confidence Flags** — RED/AMBER/GREEN visual indicators on every field.
- **Audit Trail** — Every extraction and edit logged with timestamps.
- **Not a Medical Device** — This is a data extraction aid, not clinical decision support.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Cannot connect to Ollama" | Run `ollama serve` in a terminal |
| "Model not found" | Run `ollama pull qwen2.5:14b-instruct` (or `qwen3:8b`, `qwen3.5:4b`) |
| Extraction very slow | Close other apps to free RAM. Check `ollama ps` for GPU usage. |
| 0 patients detected | Check document format. Use `/debug/raw-text` to inspect. |
| Port 5000 in use | Run `python app.py --port 5001` |
| ModuleNotFoundError | Run `pip install -r requirements.txt` |

## Running Tests

```bash
pytest tests/ -v
```
