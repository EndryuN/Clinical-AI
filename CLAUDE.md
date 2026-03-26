# CLAUDE.md — MDT Data Extractor

## What This Project Does

Locally-hosted Flask app that extracts structured patient data from NHS MDT (Multidisciplinary Team Meeting) Word documents (.docx) into a standardised Excel spreadsheet. All processing is local — no patient data leaves the machine.

**Workflow:** Upload DOCX → Parse patients → Regex extract structured fields → LLM extract freeform fields → Clinician reviews → Export Excel → (Import Excel on another machine with full review capability)

## Quick Start

```bash
ollama serve                    # Start Ollama in one terminal
ollama pull qwen3:8b            # Pull a model
pip install -r requirements.txt
python app.py                   # http://localhost:5000
```

## Architecture

```
Upload .docx
    ↓
parser/docx_parser.py          # Split into PatientBlocks, extract raw_cells
    ↓                            (deduplicates merged Word table cells)
extractor/regex_extractor.py   # Regex pass: Demographics from structured rows 0-3
    ↓                            Sets confidence_basis = structured_verbatim
extractor/prompt_builder.py    # Per-group prompt files (config/prompts/), only relevant
    ↓                            text sections sent to LLM (not full patient text)
extractor/llm_client.py        # Ollama (format:"json") or Claude API call
    ↓
extractor/response_parser.py   # Parse JSON, verbatim check against freeform cells (rows 4-7)
    ↓                            Sets freeform_verbatim or freeform_inferred
extractor/coverage.py          # Compute unused text spans + coverage percentage
    ↓                            Tracks all content rows, not just freeform
extractor/html_preview.py      # HTML source document preview — selectable text,
    ↓                            group colouring via CSS, per-character coverage spans,
    ↓                            field highlighting via DOM
export/excel_writer.py         # 3-sheet Excel: Prototype V1 + Metadata + RawCells
export/consultation_writer.py  # Consultation Excel for doctor review — field types,
                                 allowed values, per-patient data; import back to configure
```

## Key Concepts

### Patient Table Structure (Word Document)
Each patient is one table with 8 rows x 3 columns:
- **Rows 0-3** (structured): Patient Details, Demographics, Staging headers + data
- **Rows 4-7** (freeform): Clinical Details, MDT Outcome — free text

Annotation markers in the document: `(a)`=DOB, `(b)`=Name, `(c)`=NHS, `(d)`=MRN, `(e)`=Gender, `(f)`=Clinical Details, `(g)`=Staging/Histology, `(h)`=MDT Outcome, `(i)`=MDT date.

### Confidence Basis (colour system)
| Basis | Colour | Meaning |
|-------|--------|---------|
| `structured_verbatim` | Green | Regex match from structured cell (rows 0-3) |
| `freeform_verbatim` | Orange | LLM extracted, value exists verbatim in freeform text (rows 4-7) |
| `freeform_inferred` | Red | LLM inferred — not found verbatim in source |
| `edited` | Grey | Clinician manually changed the value |
| `absent` | — | Field not in document |

Backward compat: `FieldResult.confidence` property maps basis → `high/medium/low/none`.

### Group Colours (matching Hackathon Database Prototype.xlsx)
| Colour | Hex | Groups |
|--------|-----|--------|
| Grey | `#F2F2F2` | Demographics, MDT, Second MRI, MDT 6-Week, 12-Week MRI, Follow-up Flex Sig, MDT 12-Week |
| Peach | `#FCD5B4` | Endoscopy |
| Light Blue | `#D6E4F0` | Baseline MRI, Baseline CT, Surgery, Watch and Wait Dates |
| Green | `#E2EFDA` | Histology, Chemotherapy, Immunotherapy, Radiotherapy, CEA and Clinical, Watch and Wait |

### Unique Patient ID
Format: `{DDMMYYYY}_{initials}_{M/F/U}_{disambiguator}`
- Disambiguator: MRN (preferred) → NHS last 4 → zero-padded row index
- Assigned post-regex (needs gender from Demographics group)
- Collision suffix: `_b`, `_c`... within batch

### Prompt System
Per-group prompt files live in `config/prompts/`:
- `system_base.txt` — base system instructions (shared by all groups)
- `endoscopy.txt`, `baseline_ct.txt`, `surgery.txt`, `watch_and_wait.txt` — group-specific instructions + clinical reference + few-shot examples

Only the relevant text sections are sent to the LLM (matched by annotation markers), not the full patient text. This reduces prompt size by 50-63%.

An abbreviation dictionary (CRT, TNT, SCRT, etc.) is injected into all LLM prompts via `extractor/clinical_context.py`.

### Field Overrides System
- `config/field_overrides.yaml` — per-field type and allowed-value overrides
- Settings page (`/settings`) — view/edit field types and allowed values in-app
- Consultation Excel export/import (`/export/consultation`, `/import/consultation`) — generate Excel for doctor review, import back to configure LLM prompts with allowed values

### G049 Clinical Context
RCPath G049 definitions (TNM staging, MMR, EMVI, CRM, TRG) are injected into the LLM system prompt for specific groups. The LLM is instructed to prefix reason with `[G049]` when it uses these definitions.

| Group | Context |
|-------|---------|
| Histology | MMR |
| Baseline MRI | TNM T/N, EMVI, CRM |
| Baseline CT | TNM T/N/M, EMVI |
| Second MRI | TRG, EMVI, CRM |
| 12-Week MRI | TRG, EMVI, CRM |

### Model-Aware Ollama Parameters
- `format: "json"` — enforces JSON output from Ollama
- `think: false` — only sent for qwen3+/qwen3.5+ models (breaks JSON format on qwen2.5)
- `num_ctx: 16384` for 14B+ models, `8192` for smaller
- `temperature: 0.1` + `seed: 42` for reproducibility

### Self-Contained Excel (3 sheets)
- **Prototype V1** (visible): `unique_id` col 1, then 88 field columns (shifted +1). Cells colour-coded by confidence_basis.
- **Metadata** (hidden): Per-field provenance — `unique_id, field_key, confidence_basis, reason, source_cell_row, source_cell_col, source_snippet, edited, original_value, coverage_pct`. Columns read by header name (position-independent).
- **RawCells** (hidden): Full table cell content + coverage spans per patient. Enables preview regeneration on import without DOCX.

### HTML Source Document Preview
Replaced PNG-based preview with interactive HTML preview (`extractor/html_preview.py`):
- Selectable text (not a flat image)
- Group colouring via CSS borders
- Per-character coverage spans (green=used, amber=unused)
- Field source highlighting via DOM on field click
- Drop zone for linking source .docx to imported sessions

### Benchmarking
Benchmark results saved per model to `data/benchmarks.xlsx` — tracks initials, high/medium/low counts, seconds per patient.

## File Map

| File | Purpose |
|------|---------|
| `app.py` | Flask app — all routes, SSE progress, extraction orchestration, import/export |
| `models.py` | `FieldResult`, `PatientBlock`, `ExtractionSession` dataclasses |
| `config/field_schema.yaml` | 88 fields across 18 groups — single source of truth |
| `config/field_overrides.yaml` | Per-field type and allowed-value overrides |
| `config/__init__.py` | `get_all_fields()`, `get_groups()`, `get_field_override()` schema loaders |
| `config/prompts/system_base.txt` | Base system prompt shared by all groups |
| `config/prompts/endoscopy.txt` | Endoscopy group prompt + few-shot example |
| `config/prompts/baseline_ct.txt` | Baseline CT group prompt + few-shot example |
| `config/prompts/surgery.txt` | Surgery group prompt + few-shot example |
| `config/prompts/watch_and_wait.txt` | Watch and Wait group prompt + few-shot example |
| `parser/docx_parser.py` | DOCX → PatientBlocks, cell dedup, gender/mdt_date extraction |
| `extractor/regex_extractor.py` | Regex pass, `build_unique_id`, `assign_unique_id` |
| `extractor/llm_client.py` | Ollama/Claude backend, model selection, model-aware params |
| `extractor/prompt_builder.py` | Per-group prompt construction, relevant-section extraction |
| `extractor/response_parser.py` | LLM JSON parsing, verbatim check, confidence_basis assignment |
| `extractor/clinical_context.py` | G049 RCPath definitions + abbreviation dictionary |
| `extractor/coverage.py` | Span-union algorithm, `compute_coverage()`, tracks all content rows |
| `extractor/html_preview.py` | HTML source document preview with selectable text + coverage spans |
| `export/excel_writer.py` | 3-sheet Excel output with confidence colours |
| `export/consultation_writer.py` | Consultation Excel export/import for doctor review |
| `audit.py` | JSON audit trail logging |
| `templates/` | `base.html`, `index.html`, `process.html`, `review.html`, `analytics.html`, `settings.html` |
| `static/js/app.js` | Frontend: upload, progress SSE, review UI, coverage toggle, field editing |
| `static/css/style.css` | Dark theme |

## Key Routes (app.py)

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Landing page (upload) |
| `/upload` | POST | Upload DOCX, parse patients |
| `/extract` | POST | Start extraction (params: `limit`, `concurrency`) |
| `/progress` | GET | SSE stream for live extraction progress |
| `/stop` | POST | Stop extraction gracefully |
| `/process` | GET | Process page |
| `/patients` | GET | List patients (filterable by cancer_type, search) |
| `/patients/<id>` | GET | Patient detail with extractions |
| `/patients/<id>/fields` | PUT | Edit a field (sets `confidence_basis="edited"`) |
| `/patients/<id>/re-extract` | POST | Re-extract a single patient |
| `/patient/<id>/preview` | GET | HTML preview + coverage data |
| `/export` | GET | Download Excel |
| `/export/consultation` | GET | Download consultation Excel for doctor review |
| `/import/consultation` | POST | Import consultation Excel (updates field overrides) |
| `/review` | GET | Review page |
| `/settings` | GET | Settings page — view/edit field types and allowed values |
| `/settings/overrides` | GET/POST | Get/set field overrides |
| `/backend` | GET/POST | Get/set LLM backend (ollama/claude) |
| `/schema` | GET | Return field schema as JSON |
| `/analytics` | GET | Analytics dashboard data |
| `/analytics-page` | GET | Analytics page |
| `/analytics/column/<field_key>` | GET | Per-column analytics |
| `/link-source` | POST | Link source .docx to imported session |
| `/status` | GET | Current session status |
| `/audit` | GET | Audit log page |

## Constants to Know

- `_FREEFORM_ROWS = {4, 5, 6, 7}` — used for verbatim check scope and coverage calculation
- `_HEADER_ROWS = {0, 2, 4, 6}` — section header rows in the table (styled differently in preview)
- `OFFSET = 1` — in Excel, `unique_id` is col 1; schema fields start at `excel_column + 1`
- Metadata row 1 = `["SOURCE_FILE", filename]`, row 2 = named headers, data from row 3
- `source_snippet` capped at 200 chars
- Review UI shows `excel_header` descriptions (human-readable) instead of raw field keys

## Schema: 18 Groups

Demographics, Endoscopy, Histology, Baseline MRI, Baseline CT, MDT, Chemotherapy, Immunotherapy, Radiotherapy, CEA and Clinical, Surgery, Second MRI, MDT 6-Week, 12-Week MRI, Follow-up Flex Sig, MDT 12-Week, Watch and Wait, Watch and Wait Dates

Groups with `llm_required: true` (always sent to LLM even for structured-only fields): Endoscopy, Baseline CT, Surgery, Watch and Wait.

## Testing

```bash
python -m pytest tests/ -v          # 78 tests
```

Test files: `test_models.py`, `test_parser.py`, `test_regex_extractor.py`, `test_response_parser.py`, `test_coverage.py`, `test_export.py`, `test_preview_renderer.py`, `test_prompt_builder.py`, `test_schema.py`, `test_clinical_context.py`, `test_llm_client.py`

## Common Pitfalls

- `_col_first()` in `_import_excel()` uses `is not None`, not falsy check — column index 0 is valid but falsy
- `FieldResult.confidence` is a `@property`, not a stored field — don't assign to it directly
- Word merged cells may not share `_tc` elements — text-based adjacent dedup is the fallback
- Coverage tracks all content rows, not just freeform; `coverage_pct = None` means no freeform text (not 0%)
- `think: false` must NOT be sent to qwen2.5 — breaks JSON format enforcement
- Initials extraction must skip patterns like '62 DAY TARGET' — not patient names

## Design Context

**Personality:** Clinical, Trustworthy, Efficient. GitHub/Linear aesthetic.
**Theme:** Dark default with light mode toggle (persisted in localStorage). CSS uses `var(--app-*)` custom properties.
**Colour rules:** Green/orange/red are reserved for confidence levels only. No decorative colour. Group tab colours use stronger slate grey/blue/green/amber for dark UI visibility.
**Principles:** Data density over whitespace. Colour means something. Progressive disclosure. Source transparency. Zero-friction review.
**Full design spec:** See `.impeccable.md` for complete design guidelines.
