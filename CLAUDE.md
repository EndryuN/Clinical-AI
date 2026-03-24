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
extractor/prompt_builder.py    # Build system+user prompts (inject G049 context per group)
    ↓
extractor/llm_client.py        # Ollama or Claude API call
    ↓
extractor/response_parser.py   # Parse JSON, verbatim check against freeform cells (rows 4-7)
    ↓                            Sets freeform_verbatim or freeform_inferred
extractor/coverage.py          # Compute unused text spans + coverage percentage
    ↓
export/excel_writer.py         # 3-sheet Excel: Prototype V1 + Metadata + RawCells
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

### Unique Patient ID
Format: `{DDMMYYYY}_{initials}_{M/F/U}_{disambiguator}`
- Disambiguator: MRN (preferred) → NHS last 4 → zero-padded row index
- Assigned post-regex (needs gender from Demographics group)
- Collision suffix: `_b`, `_c`... within batch

### G049 Clinical Context
RCPath G049 definitions (TNM staging, MMR, EMVI, CRM, TRG) are injected into the LLM system prompt for specific groups. The LLM is instructed to prefix reason with `[G049]` when it uses these definitions.

| Group | Context |
|-------|---------|
| Histology | MMR |
| Baseline MRI | TNM T/N, EMVI, CRM |
| Baseline CT | TNM T/N/M, EMVI |
| Second MRI | TRG, EMVI, CRM |
| 12-Week MRI | TRG, EMVI, CRM |

### Self-Contained Excel (3 sheets)
- **Prototype V1** (visible): `unique_id` col 1, then 88 field columns (shifted +1). Cells colour-coded by confidence_basis.
- **Metadata** (hidden): Per-field provenance — `unique_id, field_key, confidence_basis, reason, source_cell_row, source_cell_col, source_snippet, edited, original_value, coverage_pct`. Columns read by header name (position-independent).
- **RawCells** (hidden): Full table cell content + coverage spans per patient. Enables preview regeneration on import without DOCX.

## File Map

| File | Purpose |
|------|---------|
| `app.py` | Flask app — all routes, SSE progress, extraction orchestration, import/export |
| `models.py` | `FieldResult`, `PatientBlock`, `ExtractionSession` dataclasses |
| `config/field_schema.yaml` | 88 fields across 16 groups — single source of truth |
| `config/__init__.py` | `get_all_fields()`, `get_groups()` schema loaders |
| `parser/docx_parser.py` | DOCX → PatientBlocks, cell dedup, gender/mdt_date extraction |
| `extractor/regex_extractor.py` | Regex pass, `build_unique_id`, `assign_unique_id` |
| `extractor/llm_client.py` | Ollama/Claude backend, model selection |
| `extractor/prompt_builder.py` | System + user prompt construction with G049 injection |
| `extractor/response_parser.py` | LLM JSON parsing, verbatim check, confidence_basis assignment |
| `extractor/clinical_context.py` | G049 RCPath definitions (TNM, MMR, EMVI, CRM, TRG) |
| `extractor/coverage.py` | Span-union algorithm, `compute_coverage()` |
| `extractor/preview_renderer.py` | Pillow-based PNG rendering with per-row variable columns |
| `export/excel_writer.py` | 3-sheet Excel output with confidence colours |
| `audit.py` | JSON audit trail logging |
| `templates/` | `base.html`, `index.html`, `process.html`, `review.html`, `analytics.html` |
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
| `/patients` | GET | List patients (filterable by cancer_type, search) |
| `/patients/<id>` | GET | Patient detail with extractions |
| `/patients/<id>/fields` | PUT | Edit a field (sets `confidence_basis="edited"`) |
| `/patient/<id>/preview` | GET | Preview image URL + coords + coverage data |
| `/export` | GET | Download Excel |
| `/import` | POST | Upload Excel for review (no DOCX needed) |
| `/backend` | GET/POST | Get/set LLM backend (ollama/claude) |
| `/schema` | GET | Return field schema as JSON |
| `/analytics` | GET | Analytics dashboard |
| `/status` | GET | Current session status |

## Constants to Know

- `_FREEFORM_ROWS = {4, 5, 6, 7}` — used for verbatim check scope and coverage calculation
- `_HEADER_ROWS = {0, 2, 4, 6}` — section header rows in the table (styled differently in preview)
- `OFFSET = 1` — in Excel, `unique_id` is col 1; schema fields start at `excel_column + 1`
- Metadata row 1 = `["SOURCE_FILE", filename]`, row 2 = named headers, data from row 3
- Preview PNGs saved to `static/previews/{timestamp}/`
- `source_snippet` capped at 200 chars

## Testing

```bash
python -m pytest tests/ -v          # 78 tests
```

Test files: `test_models.py`, `test_parser.py`, `test_regex_extractor.py`, `test_response_parser.py`, `test_coverage.py`, `test_export.py`, `test_preview_renderer.py`, `test_prompt_builder.py`, `test_schema.py`, `test_clinical_context.py`, `test_llm_client.py`

## Common Pitfalls

- `_col_first()` in `_import_excel()` uses `is not None`, not falsy check — column index 0 is valid but falsy
- `FieldResult.confidence` is a `@property`, not a stored field — don't assign to it directly
- Preview PNGs are cached — re-upload DOCX after parser changes to see new layout
- Word merged cells may not share `_tc` elements — text-based adjacent dedup is the fallback
- Coverage only counts freeform cells (rows 4-7); `coverage_pct = None` means no freeform text (not 0%)
