# MDT Data Extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally-hosted Flask web app that extracts structured patient data from NHS MDT Word documents using a local LLM and exports to a 97-column Excel spreadsheet.

**Architecture:** Config-driven pipeline — `field_schema.yaml` drives prompt generation, UI rendering, and Excel export. Flask backend with Jinja2 templates. Ollama (Llama 3.1 8B) for local LLM inference. No database — in-memory dataclasses.

**Tech Stack:** Python 3.11+, Flask, python-docx, openpyxl, PyYAML, requests, Bootstrap 5, Chart.js, DataTables

**Spec:** `docs/superpowers/specs/2026-03-19-mdt-extractor-design.md`

---

## File Map

| File | Responsibility |
|------|---------------|
| `config/__init__.py` | Schema loader utility — `load_schema()`, `get_groups()`, `get_all_fields()` |
| `config/field_schema.yaml` | All 88 field definitions across 16 groups — drives everything |
| `models.py` | `FieldResult`, `PatientBlock`, `ExtractionSession` dataclasses |
| `audit.py` | Append-only JSON-lines logger for clinical safety trail |
| `parser/__init__.py` | Package init |
| `parser/docx_parser.py` | Read `.docx`, split into per-patient text blocks |
| `extractor/__init__.py` | Package init |
| `extractor/llm_client.py` | HTTP client for Ollama REST API |
| `extractor/prompt_builder.py` | Build prompts from schema groups |
| `extractor/response_parser.py` | Parse LLM JSON, validate, apply confidence overrides |
| `export/__init__.py` | Package init |
| `export/excel_writer.py` | Generate 97-column Excel from patient data + schema |
| `app.py` | Flask routes, SSE endpoint, session management |
| `static/css/style.css` | Dark theme overrides for Bootstrap |
| `static/js/app.js` | Upload, progress tracking, inline editing, filtering |
| `templates/base.html` | Base layout with nav, Bootstrap, scripts |
| `templates/index.html` | Landing page with drag-and-drop upload |
| `templates/process.html` | Processing page with live progress |
| `templates/review.html` | Review dashboard with sidebar, tabs, editable table |
| `templates/analytics.html` | Charts page |
| `tests/test_schema.py` | Schema completeness and column uniqueness validation |
| `tests/test_export.py` | Round-trip Excel export test |
| `requirements.txt` | Python dependencies |

---

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `parser/__init__.py`
- Create: `extractor/__init__.py`
- Create: `export/__init__.py`

- [ ] **Step 1: Create project directories**

```bash
cd "C:/Users/ipode/Desktop/Clinical AI"
mkdir -p config parser extractor export static/css static/js templates tests data logs
```

- [ ] **Step 2: Create .gitignore**

```
__pycache__/
*.pyc
data/
logs/
.superpowers/
*.egg-info/
dist/
build/
```

- [ ] **Step 3: Create requirements.txt**

```
flask>=3.0
python-docx>=1.1
openpyxl>=3.1
pyyaml>=6.0
requests>=2.31
pytest>=8.0
```

- [ ] **Step 4: Create package init files**

Create empty `__init__.py` in `parser/`, `extractor/`, `export/`.

- [ ] **Step 5: Install dependencies**

```bash
pip install -r requirements.txt
```

- [ ] **Step 6: Initialize git and commit**

```bash
git init
git add .gitignore requirements.txt parser/__init__.py extractor/__init__.py export/__init__.py
git commit -m "chore: scaffold project structure and dependencies"
```

---

### Task 2: Field Schema (field_schema.yaml)

**Files:**
- Create: `config/field_schema.yaml`
- Create: `tests/test_schema.py`

This is the single source of truth. Every downstream task depends on it.

- [ ] **Step 1: Write the schema validation test**

```python
# tests/test_schema.py
import yaml
import os

def load_schema():
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'field_schema.yaml')
    with open(schema_path, 'r') as f:
        return yaml.safe_load(f)

def test_schema_loads():
    schema = load_schema()
    assert 'groups' in schema
    assert len(schema['groups']) >= 14

def test_all_fields_have_required_keys():
    schema = load_schema()
    for group in schema['groups']:
        assert 'name' in group
        assert 'description' in group
        assert 'fields' in group
        for field in group['fields']:
            assert 'key' in field, f"Missing key in group {group['name']}"
            assert 'excel_column' in field, f"Missing excel_column for {field.get('key')} in {group['name']}"
            assert 'excel_header' in field, f"Missing excel_header for {field['key']} in {group['name']}"
            assert 'prompt_hint' in field, f"Missing prompt_hint for {field['key']} in {group['name']}"
            assert 'type' in field, f"Missing type for {field['key']} in {group['name']}"

def test_excel_columns_are_unique():
    schema = load_schema()
    columns = []
    for group in schema['groups']:
        for field in group['fields']:
            columns.append(field['excel_column'])
    assert len(columns) == len(set(columns)), f"Duplicate excel_column values found"

def test_field_keys_are_unique():
    schema = load_schema()
    keys = []
    for group in schema['groups']:
        for field in group['fields']:
            keys.append(field['key'])
    assert len(keys) == len(set(keys)), f"Duplicate field keys found"

def test_columns_cover_range_1_to_88():
    schema = load_schema()
    columns = set()
    for group in schema['groups']:
        for field in group['fields']:
            columns.add(field['excel_column'])
    # We expect columns 1-88 but some may be intentionally skipped
    # At minimum, check we have 80+ fields
    assert len(columns) >= 80, f"Only {len(columns)} unique columns defined"

def test_field_types_are_valid():
    schema = load_schema()
    valid_types = {'string', 'date', 'text'}
    for group in schema['groups']:
        for field in group['fields']:
            assert field['type'] in valid_types, f"Invalid type '{field['type']}' for {field['key']}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_schema.py -v
```
Expected: FAIL — `config/field_schema.yaml` does not exist yet.

- [ ] **Step 3: Write the complete field_schema.yaml**

Copy the full schema from the design spec (all 88 fields, 16 groups, columns 1-88). The spec at `docs/superpowers/specs/2026-03-19-mdt-extractor-design.md` lines 85-590 contains the complete YAML to use verbatim.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_schema.py -v
```
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add config/field_schema.yaml tests/test_schema.py
git commit -m "feat: add complete field schema (88 fields, 16 groups)"
```

---

### Task 3: Data Models

**Files:**
- Create: `models.py`

- [ ] **Step 1: Write models.py**

```python
# models.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class FieldResult:
    value: Optional[str] = None
    confidence: str = "low"
    edited: bool = False
    original_value: Optional[str] = None

@dataclass
class PatientBlock:
    id: str
    initials: str = ""
    nhs_number: str = ""
    raw_text: str = ""
    extractions: dict = field(default_factory=dict)
    # Structure: {"Demographics": {"dob": FieldResult, ...}, ...}

@dataclass
class ExtractionSession:
    file_name: str = ""
    upload_time: str = ""
    patients: list = field(default_factory=list)
    status: str = "idle"  # idle, uploading, parsing, extracting, complete
    progress: dict = field(default_factory=lambda: {
        "current_patient": 0,
        "total": 0,
        "current_group": ""
    })
```

- [ ] **Step 2: Verify import works**

```bash
python -c "from models import FieldResult, PatientBlock, ExtractionSession; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add models.py
git commit -m "feat: add data model dataclasses"
```

---

### Task 4: Audit Logger

**Files:**
- Create: `audit.py`

- [ ] **Step 1: Write audit.py**

```python
# audit.py
import json
import os
from datetime import datetime

LOG_PATH = os.path.join(os.path.dirname(__file__), 'logs', 'audit.jsonl')

def _ensure_log_dir():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

def log_event(action: str, **kwargs):
    _ensure_log_dir()
    entry = {
        "timestamp": datetime.now().isoformat(timespec='seconds'),
        "action": action,
        **kwargs
    }
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')

def read_log() -> list[dict]:
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, 'r', encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]
```

- [ ] **Step 2: Verify it works**

```bash
python -c "
from audit import log_event, read_log
log_event('test', detail='hello')
print(read_log())
"
```
Expected: prints list with one entry.

- [ ] **Step 3: Clean up test log and commit**

```bash
rm -f logs/audit.jsonl
git add audit.py
git commit -m "feat: add audit trail logger"
```

---

### Task 5: Schema Loader Utility

**Files:**
- Create: `config/__init__.py`

We need a reusable function to load and access the schema, since multiple modules depend on it.

- [ ] **Step 1: Write config/__init__.py**

```python
# config/__init__.py
import os
import yaml

_schema = None

def load_schema() -> dict:
    global _schema
    if _schema is None:
        schema_path = os.path.join(os.path.dirname(__file__), 'field_schema.yaml')
        with open(schema_path, 'r', encoding='utf-8') as f:
            _schema = yaml.safe_load(f)
    return _schema

def get_groups() -> list[dict]:
    return load_schema()['groups']

def get_all_fields() -> list[dict]:
    fields = []
    for group in get_groups():
        for field in group['fields']:
            fields.append({**field, 'group_name': group['name']})
    return fields
```

- [ ] **Step 2: Verify**

```bash
python -c "
from config import get_groups, get_all_fields
print(f'{len(get_groups())} groups, {len(get_all_fields())} fields')
"
```
Expected: `16 groups, 88 fields`

- [ ] **Step 3: Commit**

```bash
git add config/__init__.py
git commit -m "feat: add schema loader utility"
```

---

### Task 6: Document Parser

**Files:**
- Create: `parser/docx_parser.py`

**Important**: The exact patient-splitting logic depends on the structure of the Word document. The implementation must first inspect the document to determine boundaries. The steps below provide a reasonable starting implementation that can be tuned.

- [ ] **Step 1: Download the hackathon dataset**

Download `hackathon-mdt-outcome-proformas.docx` from the GitHub repo and save to `data/`.

```bash
curl -L -o data/hackathon-mdt-outcome-proformas.docx \
  "https://github.com/dsikar/clinical-ai-hackathon/raw/main/data/hackathon-mdt-outcome-proformas.docx"
```

- [ ] **Step 2: Inspect the document structure**

```python
# Run interactively to understand the document format
from docx import Document
doc = Document('data/hackathon-mdt-outcome-proformas.docx')

# Check paragraphs
for i, para in enumerate(doc.paragraphs[:50]):
    if para.text.strip():
        print(f"P{i}: [{para.style.name}] {para.text[:100]}")

# Check tables
print(f"\nTables: {len(doc.tables)}")
for i, table in enumerate(doc.tables[:3]):
    print(f"Table {i}: {len(table.rows)} rows x {len(table.columns)} cols")
    for j, row in enumerate(table.rows[:3]):
        print(f"  Row {j}: {[cell.text[:30] for cell in row.cells]}")
```

Use the output to determine patient boundaries. Adjust the splitting logic in the next step accordingly.

- [ ] **Step 3: Write docx_parser.py**

```python
# parser/docx_parser.py
import re
from docx import Document
from models import PatientBlock

def parse_docx(file_path: str) -> list[PatientBlock]:
    """Parse a .docx file and split into per-patient text blocks."""
    doc = Document(file_path)
    full_text = _extract_full_text(doc)
    return _split_into_patients(full_text)

def _extract_full_text(doc: Document) -> str:
    """Extract all text from paragraphs and tables."""
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            row_text = ' | '.join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                parts.append(row_text)
    return '\n'.join(parts)

def _split_into_patients(text: str) -> list[PatientBlock]:
    """Split full text into individual patient blocks.

    Strategy: Look for NHS number patterns (NNN or 10-digit numbers) or
    recurring structural markers to identify patient boundaries.
    This will need tuning based on actual document inspection (Step 2).
    """
    # Pattern: NHS numbers starting with NNN or 999
    # Adjust this regex after inspecting the actual document
    nhs_pattern = re.compile(r'(?:NHS\s*(?:number|no\.?)?:?\s*)?(\d{10}|NNN\s*\d{3}\s*\d{4})', re.IGNORECASE)

    # Split on patient headers — adjust based on document inspection
    # This is a starting implementation; refine after Step 2
    sections = re.split(r'(?=(?:Patient|Mr|Mrs|Ms|Miss)\s+[A-Z])', text)

    patients = []
    for i, section in enumerate(sections):
        section = section.strip()
        if not section or len(section) < 50:  # skip tiny fragments
            continue

        # Try to extract identifiers
        nhs_match = nhs_pattern.search(section)
        nhs_number = nhs_match.group(1).replace(' ', '') if nhs_match else f"unknown_{i}"

        # Try to extract initials from the first line
        initials_match = re.search(r'\b([A-Z]{2})\b', section[:100])
        initials = initials_match.group(1) if initials_match else f"P{i}"

        patient = PatientBlock(
            id=f"patient_{i:03d}",
            initials=initials,
            nhs_number=nhs_number,
            raw_text=section
        )
        patients.append(patient)

    return patients

def get_raw_text(file_path: str) -> str:
    """Return full document text for debugging."""
    doc = Document(file_path)
    return _extract_full_text(doc)
```

- [ ] **Step 4: Test with actual document**

```bash
python -c "
from parser.docx_parser import parse_docx
patients = parse_docx('data/hackathon-mdt-outcome-proformas.docx')
print(f'Detected {len(patients)} patients')
for p in patients[:5]:
    print(f'  {p.id}: {p.initials} ({p.nhs_number}) - {len(p.raw_text)} chars')
"
```

If the count is wrong (not ~50), go back to Step 2 output and adjust the splitting regex in `_split_into_patients`. Common adjustments:
- Change the split pattern to match actual document headers
- Use table rows instead of paragraph splits if document uses tables
- Look for page break markers

- [ ] **Step 5: Commit**

```bash
git add parser/docx_parser.py data/hackathon-mdt-outcome-proformas.docx
git commit -m "feat: add document parser with patient splitting"
```

---

### Task 7: Prompt Builder

**Files:**
- Create: `extractor/prompt_builder.py`

- [ ] **Step 1: Write prompt_builder.py**

```python
# extractor/prompt_builder.py
from config import get_groups

PROMPT_TEMPLATE = """You are a clinical data extraction assistant. Extract the following fields from the patient's MDT notes below.

For each field, provide:
- "value": the extracted value, or null if not mentioned in the text
- "confidence": "high" if explicitly stated in the text, "medium" if inferred from context, "low" if uncertain or ambiguous

Return ONLY valid JSON in this exact format:
{{
{json_example}
}}

Fields to extract:
{field_list}

Patient MDT Notes:
---
{patient_text}
---"""

def build_prompt(patient_text: str, group: dict) -> str:
    """Build an extraction prompt for a specific schema group."""
    field_list = "\n".join(
        f"- {f['key']}: {f['prompt_hint']}" for f in group['fields']
    )
    json_example = ",\n".join(
        f'  "{f["key"]}": {{"value": "...", "confidence": "high|medium|low"}}'
        for f in group['fields']
    )
    return PROMPT_TEMPLATE.format(
        field_list=field_list,
        json_example=json_example,
        patient_text=patient_text
    )

def build_all_prompts(patient_text: str) -> list[tuple[dict, str]]:
    """Build prompts for all schema groups. Returns list of (group, prompt) tuples."""
    return [(group, build_prompt(patient_text, group)) for group in get_groups()]
```

- [ ] **Step 2: Verify prompt generation**

```bash
python -c "
from extractor.prompt_builder import build_prompt
from config import get_groups
groups = get_groups()
prompt = build_prompt('Mr AO, DOB 26/05/1970, Male.', groups[0])
print(prompt[:500])
print(f'---\nPrompt length: {len(prompt)} chars')
"
```
Expected: A well-formed prompt with Demographics fields listed and the patient text included.

- [ ] **Step 3: Commit**

```bash
git add extractor/prompt_builder.py
git commit -m "feat: add prompt builder from schema groups"
```

---

### Task 8: LLM Client

**Files:**
- Create: `extractor/llm_client.py`

- [ ] **Step 1: Write llm_client.py**

```python
# extractor/llm_client.py
import requests
import json

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.1:8b"
TIMEOUT = 120  # seconds

def check_ollama() -> bool:
    """Check if Ollama is running and model is available."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        models = [m['name'] for m in resp.json().get('models', [])]
        return any(MODEL.split(':')[0] in m for m in models)
    except requests.ConnectionError:
        return False

def generate(prompt: str) -> str:
    """Send a prompt to Ollama and return the full response text."""
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 8192
        }
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json().get('response', '')
    except requests.ConnectionError:
        raise ConnectionError("Cannot connect to Ollama. Is it running? Start with: ollama serve")
    except requests.Timeout:
        raise TimeoutError(f"Ollama request timed out after {TIMEOUT}s")
```

- [ ] **Step 2: Test connectivity (requires Ollama running)**

```bash
python -c "
from extractor.llm_client import check_ollama
print('Ollama available:', check_ollama())
"
```
Expected: `True` if Ollama is running with the model pulled, `False` otherwise.

- [ ] **Step 3: Commit**

```bash
git add extractor/llm_client.py
git commit -m "feat: add Ollama LLM client"
```

---

### Task 9: Response Parser

**Files:**
- Create: `extractor/response_parser.py`

- [ ] **Step 1: Write response_parser.py**

```python
# extractor/response_parser.py
import json
import re
from models import FieldResult

def parse_llm_response(raw_response: str, group: dict) -> dict[str, FieldResult]:
    """Parse LLM JSON response into FieldResult objects with confidence overrides."""
    expected_keys = [f['key'] for f in group['fields']]
    field_types = {f['key']: f['type'] for f in group['fields']}

    # Try to extract JSON from response
    data = _extract_json(raw_response)
    if data is None:
        # Total failure — return all nulls
        return {key: FieldResult(value=None, confidence="low") for key in expected_keys}

    results = {}
    for key in expected_keys:
        if key in data and isinstance(data[key], dict):
            value = data[key].get('value')
            confidence = data[key].get('confidence', 'low')
            # Normalize confidence
            confidence = confidence.lower() if isinstance(confidence, str) else 'low'
            if confidence not in ('high', 'medium', 'low'):
                confidence = 'low'
        else:
            value = None
            confidence = 'low'

        # Convert value to string or None
        if value is not None:
            value = str(value).strip()
            if value.lower() in ('null', 'none', 'n/a', ''):
                value = None

        # Programmatic confidence overrides
        confidence = _apply_confidence_overrides(value, confidence, field_types.get(key, 'string'))

        results[key] = FieldResult(value=value, confidence=confidence)

    return results

def _extract_json(raw: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown code blocks."""
    raw = raw.strip()

    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None

def _apply_confidence_overrides(value, confidence: str, field_type: str) -> str:
    """Apply programmatic confidence rules on top of LLM self-assessment."""
    # Null values are always low confidence
    if value is None:
        return 'low'

    # Date validation
    if field_type == 'date':
        if not re.match(r'\d{1,2}/\d{1,2}/\d{4}', value):
            return 'low'

    return confidence
```

- [ ] **Step 2: Test with mock response**

```bash
python -c "
from extractor.response_parser import parse_llm_response
mock_group = {'fields': [
    {'key': 'dob', 'type': 'date', 'prompt_hint': '', 'excel_column': 1, 'excel_header': ''},
    {'key': 'gender', 'type': 'string', 'prompt_hint': '', 'excel_column': 5, 'excel_header': ''}
]}
mock_response = '{\"dob\": {\"value\": \"26/05/1970\", \"confidence\": \"high\"}, \"gender\": {\"value\": \"Male\", \"confidence\": \"high\"}}'
results = parse_llm_response(mock_response, mock_group)
for k, v in results.items():
    print(f'{k}: {v.value} ({v.confidence})')
"
```
Expected: `dob: 26/05/1970 (high)` and `gender: Male (high)`.

- [ ] **Step 3: Commit**

```bash
git add extractor/response_parser.py
git commit -m "feat: add LLM response parser with confidence overrides"
```

---

### Task 10: Excel Writer

**Files:**
- Create: `export/excel_writer.py`
- Create: `tests/test_export.py`

- [ ] **Step 1: Write the export test**

```python
# tests/test_export.py
import os
import tempfile
from openpyxl import load_workbook
from models import PatientBlock, FieldResult
from export.excel_writer import write_excel

def test_excel_round_trip():
    """Write mock patient data to Excel and verify it reads back correctly."""
    patient = PatientBlock(
        id="patient_001",
        initials="AO",
        nhs_number="9990000001",
        raw_text="test",
        extractions={
            "Demographics": {
                "dob": FieldResult(value="26/05/1970", confidence="high"),
                "initials": FieldResult(value="AO", confidence="high"),
                "mrn": FieldResult(value="9990001", confidence="high"),
                "nhs_number": FieldResult(value="9990000001", confidence="high"),
                "gender": FieldResult(value="Male", confidence="high"),
                "previous_cancer": FieldResult(value="No", confidence="medium"),
                "previous_cancer_site": FieldResult(value="N/A", confidence="low"),
            }
        }
    )

    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        output_path = f.name

    try:
        write_excel([patient], output_path)

        wb = load_workbook(output_path)
        ws = wb.active

        # Check sheet name
        assert ws.title == "Prototype V1"

        # Check header row exists
        assert ws.cell(row=1, column=1).value is not None

        # Check patient data in row 2
        assert ws.cell(row=2, column=2).value == "AO"  # initials, col 2
        assert ws.cell(row=2, column=5).value == "Male"  # gender, col 5

        wb.close()
    finally:
        os.unlink(output_path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_export.py -v
```
Expected: FAIL — `export.excel_writer` does not exist.

- [ ] **Step 3: Write excel_writer.py**

```python
# export/excel_writer.py
from openpyxl import Workbook
from openpyxl.styles import numbers
from config import get_groups, get_all_fields

def write_excel(patients: list, output_path: str):
    """Write patient extraction data to a 97-column Excel file."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Prototype V1"

    all_fields = get_all_fields()

    # Write header row
    for field in all_fields:
        col = field['excel_column']
        ws.cell(row=1, column=col, value=field['excel_header'])

    # Write patient data rows
    for row_idx, patient in enumerate(patients, start=2):
        for group_name, fields in patient.extractions.items():
            for field_key, field_result in fields.items():
                # Find the excel_column for this field
                col = _get_column(all_fields, field_key)
                if col and field_result.value is not None:
                    cell = ws.cell(row=row_idx, column=col, value=field_result.value)
                    # Format date cells
                    field_def = _get_field_def(all_fields, field_key)
                    if field_def and field_def['type'] == 'date':
                        cell.number_format = 'DD/MM/YYYY'

    wb.save(output_path)

def _get_column(all_fields: list, key: str) -> int | None:
    for f in all_fields:
        if f['key'] == key:
            return f['excel_column']
    return None

def _get_field_def(all_fields: list, key: str) -> dict | None:
    for f in all_fields:
        if f['key'] == key:
            return f
    return None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_export.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add export/excel_writer.py tests/test_export.py
git commit -m "feat: add Excel writer with round-trip test"
```

---

### Task 11: Flask App — Core Routes

**Files:**
- Create: `app.py`
- Create: `templates/base.html`
- Create: `templates/index.html`

- [ ] **Step 1: Write base template**

```html
<!-- templates/base.html -->
<!DOCTYPE html>
<html lang="en" data-bs-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}MDT Extractor{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.datatables.net/1.13.8/css/dataTables.bootstrap5.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
    {% block head %}{% endblock %}
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark border-bottom border-secondary">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">&#x1f3e5; MDT Extractor</a>
            <div class="navbar-nav ms-auto">
                {% if session_active %}
                <a class="nav-link" href="/review">Review</a>
                <a class="nav-link" href="/analytics-page">Analytics</a>
                <a class="btn btn-success btn-sm ms-2" href="/export">Export Excel</a>
                {% endif %}
            </div>
        </div>
    </nav>
    <div class="container-fluid mt-3">
        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.8/js/jquery.dataTables.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.8/js/dataTables.bootstrap5.min.js"></script>
    <script src="{{ url_for('static', filename='js/app.js') }}"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 2: Write landing page template**

```html
<!-- templates/index.html -->
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center mt-5">
    <div class="col-md-6 text-center">
        <h1 class="mb-2">MDT Data Extractor</h1>
        <p class="text-muted mb-4">Upload your MDT outcome proforma to extract structured patient data</p>

        <div id="upload-zone" class="border border-secondary border-2 rounded-3 p-5"
             style="border-style: dashed !important; cursor: pointer;">
            <div class="fs-1 mb-3">&#x1f4c4;</div>
            <p class="text-primary fw-bold mb-1">Drag &amp; drop your .docx file here</p>
            <p class="text-muted small">or click to browse</p>
            <input type="file" id="file-input" accept=".docx" class="d-none">
        </div>

        <p class="text-muted small mt-3">&#x1f512; All processing happens locally &mdash; no data leaves your machine</p>

        {% if error %}
        <div class="alert alert-danger mt-3">{{ error }}</div>
        {% endif %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Write app.py with upload and core routes**

```python
# app.py
import os
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, send_file, stream_with_context
from models import ExtractionSession, PatientBlock, FieldResult
from parser.docx_parser import parse_docx, get_raw_text
from extractor.llm_client import check_ollama, generate
from extractor.prompt_builder import build_all_prompts
from extractor.response_parser import parse_llm_response
from export.excel_writer import write_excel
from config import get_groups, get_all_fields
from audit import log_event
import json

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Global session (one at a time)
session = ExtractionSession()

@app.route('/')
def index():
    ollama_ok = check_ollama()
    return render_template('index.html',
                         session_active=(session.status == 'complete'),
                         ollama_ok=ollama_ok)

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if not file.filename.endswith('.docx'):
        return jsonify({"error": "Only .docx files are supported"}), 400

    # Save file
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(file_path)

    # Parse and detect patients
    session.file_name = file.filename
    session.upload_time = datetime.now().isoformat()
    session.status = 'parsing'

    try:
        patients = parse_docx(file_path)
        session.patients = patients
        session.status = 'parsed'
        session.progress['total'] = len(patients)

        log_event('upload', file_name=file.filename, patients_detected=len(patients))

        return jsonify({
            "status": "ok",
            "patients_detected": len(patients),
            "patient_list": [
                {"id": p.id, "initials": p.initials, "nhs_number": p.nhs_number}
                for p in patients
            ]
        })
    except Exception as e:
        session.status = 'idle'
        return jsonify({"error": str(e)}), 500

@app.route('/extract', methods=['POST'])
def extract():
    if session.status not in ('parsed', 'complete'):
        return jsonify({"error": "No document uploaded or already extracting"}), 400

    session.status = 'extracting'

    # Run extraction in background thread
    thread = threading.Thread(target=_run_extraction)
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})

def _run_extraction():
    groups = get_groups()
    completed_patients = []

    for i, patient in enumerate(session.patients):
        session.progress['current_patient'] = i + 1

        for group in groups:
            session.progress['current_group'] = group['name']

            try:
                from extractor.prompt_builder import build_prompt
                prompt = build_prompt(patient.raw_text, group)
                raw_response = generate(prompt)
                results = parse_llm_response(raw_response, group)

                # Retry once if all fields are null (likely malformed response)
                all_null = all(fr.value is None for fr in results.values())
                if all_null and len(group['fields']) > 0:
                    raw_response = generate(prompt)
                    results = parse_llm_response(raw_response, group)

                patient.extractions[group['name']] = results

                conf_summary = {"high": 0, "medium": 0, "low": 0}
                for fr in results.values():
                    conf_summary[fr.confidence] += 1

                log_event('extraction',
                         patient_id=patient.nhs_number,
                         group=group['name'],
                         fields_extracted=len(results),
                         confidence_summary=conf_summary)
            except Exception as e:
                patient.extractions[group['name']] = {
                    f['key']: FieldResult(value=None, confidence='low')
                    for f in group['fields']
                }
                log_event('extraction_error',
                         patient_id=patient.nhs_number,
                         group=group['name'],
                         error=str(e))

        # Track completed patient for SSE progress
        completed_patients.append({
            "id": patient.id,
            "initials": patient.initials,
            "confidence_summary": _confidence_summary(patient)
        })
        session.progress['completed_patients'] = completed_patients

    session.status = 'complete'

@app.route('/progress')
def progress():
    def event_stream():
        import time
        last_patient = 0
        while session.status == 'extracting':
            if session.progress['current_patient'] != last_patient:
                last_patient = session.progress['current_patient']
                event_data = {
                    "current_patient": session.progress['current_patient'],
                    "total": session.progress['total'],
                    "current_group": session.progress['current_group'],
                    "completed_patients": session.progress.get('completed_patients', [])
                }
                yield f"data: {json.dumps(event_data)}\n\n"
            time.sleep(1)
        # Final event
        yield f"data: {json.dumps({'status': 'complete', 'total': session.progress['total']})}\n\n"

    return Response(stream_with_context(event_stream()), mimetype='text/event-stream')

@app.route('/patients')
def get_patients():
    cancer_type = request.args.get('cancer_type', '')
    search = request.args.get('search', '').lower()

    result = []
    for p in session.patients:
        # Get cancer type from first MDT treatment if available
        ct = _get_cancer_type(p)

        if cancer_type and ct != cancer_type:
            continue
        if search and search not in p.initials.lower() and search not in p.nhs_number:
            continue

        conf = _confidence_summary(p)
        result.append({
            "id": p.id,
            "initials": p.initials,
            "nhs_number": p.nhs_number,
            "gender": _get_field_value(p, "Demographics", "gender"),
            "cancer_type": ct,
            "confidence_summary": conf
        })

    return jsonify({"patients": result})

@app.route('/patients/<patient_id>')
def get_patient(patient_id):
    patient = _find_patient(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    extractions = {}
    for group_name, fields in patient.extractions.items():
        extractions[group_name] = {
            key: {"value": fr.value, "confidence": fr.confidence, "edited": fr.edited}
            for key, fr in fields.items()
        }

    return jsonify({
        "id": patient.id,
        "initials": patient.initials,
        "nhs_number": patient.nhs_number,
        "raw_text": patient.raw_text,
        "extractions": extractions
    })

@app.route('/patients/<patient_id>/fields', methods=['PUT'])
def edit_field(patient_id):
    patient = _find_patient(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    data = request.json
    group = data.get('group')
    field_key = data.get('field')
    new_value = data.get('value')

    if group not in patient.extractions or field_key not in patient.extractions[group]:
        return jsonify({"error": "Field not found"}), 404

    fr = patient.extractions[group][field_key]
    old_value = fr.value

    if not fr.edited:
        fr.original_value = old_value
    fr.value = new_value
    fr.edited = True

    log_event('manual_edit',
             patient_id=patient.nhs_number,
             group=group, field=field_key,
             old_value=old_value, new_value=new_value)

    return jsonify({"status": "ok", "old_value": old_value, "new_value": new_value})

@app.route('/patients/<patient_id>/re-extract', methods=['POST'])
def re_extract(patient_id):
    patient = _find_patient(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    data = request.json or {}
    target_groups = data.get('groups', [g['name'] for g in get_groups()])

    def _do_re_extract():
        for group in get_groups():
            if group['name'] in target_groups:
                try:
                    from extractor.prompt_builder import build_prompt
                    prompt = build_prompt(patient.raw_text, group)
                    raw_response = generate(prompt)
                    results = parse_llm_response(raw_response, group)
                    patient.extractions[group['name']] = results
                except Exception:
                    pass

    thread = threading.Thread(target=_do_re_extract)
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})

@app.route('/export')
def export():
    if session.status != 'complete' or not session.patients:
        return jsonify({"error": "No data to export"}), 400

    output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'export.xlsx')
    write_excel(session.patients, output_path)

    log_event('export', patients_exported=len(session.patients), format='xlsx')

    return send_file(output_path,
                    download_name='mdt_extraction.xlsx',
                    as_attachment=True)

@app.route('/analytics')
def analytics_data():
    if not session.patients:
        return jsonify({})

    cancer_types = {}
    treatments = {}
    confidence = {"high": 0, "medium": 0, "low": 0}

    for p in session.patients:
        ct = _get_cancer_type(p)
        cancer_types[ct] = cancer_types.get(ct, 0) + 1

        treat = _get_field_value(p, "MDT", "first_mdt_treatment")
        if treat:
            treatments[treat] = treatments.get(treat, 0) + 1

        for fields in p.extractions.values():
            for fr in fields.values():
                confidence[fr.confidence] += 1

    return jsonify({
        "cancer_types": cancer_types,
        "treatments": treatments,
        "confidence": confidence
    })

@app.route('/audit')
def audit_trail():
    from audit import read_log
    return jsonify(read_log())

@app.route('/debug/raw-text')
def debug_raw_text():
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], session.file_name) if session.file_name else None
    if not file_path or not os.path.exists(file_path):
        return "No file uploaded", 404
    return f"<pre>{get_raw_text(file_path)}</pre>"

# Helper functions
def _find_patient(patient_id: str):
    for p in session.patients:
        if p.id == patient_id:
            return p
    return None

def _get_field_value(patient, group_name, field_key):
    if group_name in patient.extractions and field_key in patient.extractions[group_name]:
        return patient.extractions[group_name][field_key].value
    return None

def _get_cancer_type(patient):
    # Derive from biopsy result or default to "Colorectal" for this dataset
    biopsy = _get_field_value(patient, "Histology", "biopsy_result")
    if biopsy and "adenocarcinoma" in biopsy.lower():
        return "Colorectal"
    return "Unknown"

def _confidence_summary(patient):
    summary = {"high": 0, "medium": 0, "low": 0}
    for fields in patient.extractions.values():
        for fr in fields.values():
            summary[fr.confidence] += 1
    return summary

if __name__ == '__main__':
    import sys
    port = 5000
    if '--port' in sys.argv:
        port = int(sys.argv[sys.argv.index('--port') + 1])
    app.run(debug=True, port=port, threaded=True)
```

- [ ] **Step 4: Create empty static files**

Create `static/css/style.css` (empty for now) and `static/js/app.js` (empty for now).

- [ ] **Step 5: Test Flask starts**

```bash
python app.py
```
Expected: Flask starts on http://localhost:5000 and the landing page loads in browser.

- [ ] **Step 6: Commit**

```bash
git add app.py templates/base.html templates/index.html static/css/style.css static/js/app.js
git commit -m "feat: add Flask app with core routes and landing page"
```

---

### Task 12: Processing Page (Upload + Progress)

**Files:**
- Create: `templates/process.html`
- Modify: `static/js/app.js`

- [ ] **Step 1: Write process.html**

```html
<!-- templates/process.html -->
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center mt-4">
    <div class="col-md-8">
        <div id="parse-result" class="mb-4">
            <h4>Document Parsed</h4>
            <p>File: <span class="text-primary" id="file-name"></span></p>
            <p>Detected <span class="text-warning fw-bold" id="patient-count"></span> patients</p>
            <button id="start-btn" class="btn btn-success btn-lg mt-2" onclick="startExtraction()">
                &#x25b6; Start Extraction
            </button>
        </div>

        <div id="progress-section" class="d-none">
            <h4>Extracting...</h4>
            <div class="mb-3">
                <div class="d-flex justify-content-between text-muted small mb-1">
                    <span>Overall Progress</span>
                    <span id="progress-text">0 / 0 patients</span>
                </div>
                <div class="progress" style="height: 12px;">
                    <div id="progress-bar" class="progress-bar bg-success" style="width: 0%"></div>
                </div>
            </div>

            <div class="card bg-dark border-secondary mb-3">
                <div class="card-body">
                    <p class="mb-2">Now processing: <span class="text-primary fw-bold" id="current-patient"></span></p>
                    <div id="group-badges"></div>
                </div>
            </div>

            <div id="completed-log" class="small text-muted" style="max-height: 200px; overflow-y: auto;"></div>
        </div>

        <div id="complete-section" class="d-none text-center">
            <div class="fs-1 text-success mb-3">&#x2713;</div>
            <h4>Extraction Complete</h4>
            <p class="text-muted" id="complete-summary"></p>
            <div class="d-flex gap-3 justify-content-center mt-3">
                <a href="/review" class="btn btn-primary">Review Patients</a>
                <a href="/export" class="btn btn-success">Export Excel</a>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Write app.js with upload and SSE progress**

```javascript
// static/js/app.js

// ===== Upload Zone =====
document.addEventListener('DOMContentLoaded', function() {
    const zone = document.getElementById('upload-zone');
    const input = document.getElementById('file-input');

    if (!zone || !input) return;

    zone.addEventListener('click', () => input.click());
    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('border-primary');
    });
    zone.addEventListener('dragleave', () => {
        zone.classList.remove('border-primary');
    });
    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('border-primary');
        if (e.dataTransfer.files.length) {
            uploadFile(e.dataTransfer.files[0]);
        }
    });
    input.addEventListener('change', () => {
        if (input.files.length) {
            uploadFile(input.files[0]);
        }
    });
});

function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    fetch('/upload', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                alert(data.error);
                return;
            }
            // Store data and redirect to process page
            sessionStorage.setItem('upload_result', JSON.stringify(data));
            sessionStorage.setItem('file_name', file.name);
            window.location.href = '/process';
        })
        .catch(err => alert('Upload failed: ' + err));
}

// ===== Process Page =====
function initProcessPage() {
    const data = JSON.parse(sessionStorage.getItem('upload_result') || 'null');
    const fileName = sessionStorage.getItem('file_name');
    if (!data) return;

    document.getElementById('file-name').textContent = fileName;
    document.getElementById('patient-count').textContent = data.patients_detected;
}

function startExtraction() {
    document.getElementById('start-btn').classList.add('d-none');
    document.getElementById('progress-section').classList.remove('d-none');

    fetch('/extract', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' })
        .then(r => r.json())
        .then(() => listenProgress());
}

function listenProgress() {
    const source = new EventSource('/progress');
    source.onmessage = function(event) {
        const data = JSON.parse(event.data);

        if (data.status === 'complete') {
            source.close();
            document.getElementById('progress-section').classList.add('d-none');
            document.getElementById('complete-section').classList.remove('d-none');
            document.getElementById('complete-summary').textContent =
                `${data.total} patients processed`;
            return;
        }

        const pct = (data.current_patient / data.total * 100).toFixed(0);
        document.getElementById('progress-bar').style.width = pct + '%';
        document.getElementById('progress-text').textContent =
            `${data.current_patient} / ${data.total} patients`;
        document.getElementById('current-patient').textContent =
            `Patient ${data.current_patient} — ${data.current_group}`;

        // Render completed patients log
        if (data.completed_patients) {
            const log = document.getElementById('completed-log');
            log.innerHTML = data.completed_patients.slice().reverse().map(p => {
                const c = p.confidence_summary;
                return `<div class="text-muted py-1">&#x2713; ${p.initials} · ` +
                    `<span class="text-success">${c.high} high</span> · ` +
                    `<span class="text-warning">${c.medium} med</span> · ` +
                    `<span class="text-danger">${c.low} low</span></div>`;
            }).join('');
        }
    };
}

// Auto-init process page
if (document.getElementById('parse-result')) {
    initProcessPage();
}

// ===== Review Page Functions =====
let currentPatientId = null;
let currentGroup = null;

function loadPatients(filters = {}) {
    let url = '/patients?';
    if (filters.cancer_type) url += `cancer_type=${filters.cancer_type}&`;
    if (filters.search) url += `search=${filters.search}&`;

    fetch(url)
        .then(r => r.json())
        .then(data => renderPatientList(data.patients));
}

function renderPatientList(patients) {
    const list = document.getElementById('patient-list');
    if (!list) return;

    list.innerHTML = patients.map(p => `
        <div class="patient-item p-2 rounded mb-1 ${p.id === currentPatientId ? 'active border-start border-primary border-3' : ''}"
             onclick="selectPatient('${p.id}')" style="cursor:pointer">
            <div class="fw-bold small">${p.initials} — ${p.gender || ''}</div>
            <div class="text-muted" style="font-size:11px">${p.nhs_number} · ${p.cancer_type}</div>
            <div class="mt-1">
                <span class="badge bg-success" style="font-size:10px">${p.confidence_summary.high} high</span>
                <span class="badge bg-warning text-dark" style="font-size:10px">${p.confidence_summary.medium} med</span>
                <span class="badge bg-danger" style="font-size:10px">${p.confidence_summary.low} low</span>
            </div>
        </div>
    `).join('');
}

function selectPatient(patientId) {
    currentPatientId = patientId;

    fetch(`/patients/${patientId}`)
        .then(r => r.json())
        .then(data => {
            // Update source text panel
            document.getElementById('source-text').textContent = data.raw_text;

            // Set first group as active if none selected
            const groups = Object.keys(data.extractions);
            if (!currentGroup || !groups.includes(currentGroup)) {
                currentGroup = groups[0];
            }

            renderGroupTabs(groups);
            renderFieldTable(data.extractions[currentGroup], currentGroup);
            loadPatients();  // refresh to highlight active
        });
}

function renderGroupTabs(groups) {
    const tabs = document.getElementById('group-tabs');
    if (!tabs) return;

    tabs.innerHTML = groups.map(g => `
        <li class="nav-item">
            <a class="nav-link ${g === currentGroup ? 'active' : ''}" href="#"
               onclick="switchGroup('${g}'); return false;">${g}</a>
        </li>
    `).join('');
}

function switchGroup(group) {
    currentGroup = group;
    selectPatient(currentPatientId);
}

function renderFieldTable(fields, groupName) {
    const tbody = document.getElementById('field-table-body');
    if (!tbody) return;

    const allowedConf = confidenceFilter ? confidenceFilter.split(',') : null;

    tbody.innerHTML = Object.entries(fields)
        .filter(([key, fr]) => !allowedConf || allowedConf.includes(fr.confidence))
        .map(([key, fr]) => {
        const confClass = fr.confidence === 'high' ? 'success' :
                         fr.confidence === 'medium' ? 'warning' : 'danger';
        const confText = fr.confidence.toUpperCase();
        return `
        <tr>
            <td class="text-muted">${key}</td>
            <td>
                <input type="text" class="form-control form-control-sm bg-dark text-light border-${confClass}"
                       value="${fr.value || ''}"
                       onchange="editField('${groupName}', '${key}', this.value)">
            </td>
            <td class="text-center">
                <span class="badge bg-${confClass}">${confText}</span>
                ${fr.edited ? '<span class="badge bg-info ms-1">EDITED</span>' : ''}
            </td>
        </tr>`;
    }).join('');
}

let confidenceFilter = '';

function filterConfidence(filter) {
    confidenceFilter = filter;
    if (currentPatientId) selectPatient(currentPatientId);
}

function editField(group, field, newValue) {
    fetch(`/patients/${currentPatientId}/fields`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ group, field, value: newValue })
    }).then(r => r.json());
}
```

- [ ] **Step 3: Add the /process route to app.py**

Add this route to `app.py`:

```python
@app.route('/process')
def process_page():
    return render_template('process.html', session_active=(session.status == 'complete'))
```

- [ ] **Step 4: Test the upload → process flow**

1. Run `python app.py`
2. Open http://localhost:5000
3. Upload the test `.docx` file
4. Verify redirect to `/process` with correct patient count

- [ ] **Step 5: Commit**

```bash
git add templates/process.html static/js/app.js
git commit -m "feat: add processing page with upload and SSE progress"
```

---

### Task 13: Review Dashboard

**Files:**
- Create: `templates/review.html`
- Modify: `app.py` (add /review route)

- [ ] **Step 1: Write review.html**

```html
<!-- templates/review.html -->
{% extends "base.html" %}
{% block content %}
<div class="row" style="height: calc(100vh - 80px);">
    <!-- Patient Sidebar -->
    <div class="col-md-2 border-end border-secondary overflow-auto p-2">
        <div class="mb-2">
            <input type="text" class="form-control form-control-sm bg-dark text-light"
                   placeholder="Search patient..." onkeyup="loadPatients({search: this.value})">
        </div>
        <div class="mb-2">
            <select class="form-select form-select-sm bg-dark text-light"
                    onchange="loadPatients({cancer_type: this.value})">
                <option value="">All Cancer Types</option>
                <option value="Colorectal">Colorectal</option>
            </select>
        </div>
        <div id="patient-list"></div>
    </div>

    <!-- Main Content -->
    <div class="col-md-10 d-flex flex-column">
        <!-- Group Tabs + Confidence Filter -->
        <div class="d-flex align-items-center border-bottom border-secondary">
            <ul class="nav nav-tabs flex-grow-1 border-0" id="group-tabs"></ul>
            <div class="px-3">
                <select class="form-select form-select-sm bg-dark text-light" style="width:auto"
                        onchange="filterConfidence(this.value)">
                    <option value="">All Confidence</option>
                    <option value="low">Low Only</option>
                    <option value="medium,low">Medium + Low</option>
                </select>
            </div>
        </div>

        <!-- Field Table -->
        <div class="flex-grow-1 overflow-auto p-3">
            <table class="table table-dark table-sm">
                <thead>
                    <tr>
                        <th style="width:30%">Field</th>
                        <th style="width:50%">Value</th>
                        <th style="width:20%" class="text-center">Confidence</th>
                    </tr>
                </thead>
                <tbody id="field-table-body">
                    <tr><td colspan="3" class="text-muted text-center">Select a patient</td></tr>
                </tbody>
            </table>
        </div>

        <!-- Source Text Panel -->
        <div class="border-top border-secondary p-3" style="max-height: 150px; overflow-y: auto;">
            <div class="text-muted small text-uppercase mb-1">Source Text</div>
            <pre id="source-text" class="text-muted small mb-0" style="white-space: pre-wrap;">Select a patient to view source text</pre>
        </div>
    </div>
</div>
{% endblock %}
{% block scripts %}
<script>
    document.addEventListener('DOMContentLoaded', () => loadPatients());
</script>
{% endblock %}
```

- [ ] **Step 2: Add /review route to app.py**

```python
@app.route('/review')
def review_page():
    return render_template('review.html', session_active=(session.status == 'complete'))
```

- [ ] **Step 3: Test the review page**

1. Run the full flow: upload → extract (with Ollama running) → go to /review
2. Verify: patient list loads, clicking a patient shows their data, category tabs switch, inline editing works

- [ ] **Step 4: Commit**

```bash
git add templates/review.html
git commit -m "feat: add review dashboard with patient sidebar, tabs, and inline editing"
```

---

### Task 14: Dark Theme CSS

**Files:**
- Modify: `static/css/style.css`

- [ ] **Step 1: Write style.css**

```css
/* static/css/style.css */
body {
    background-color: #0d1117;
    color: #c9d1d9;
}

.patient-item {
    background: transparent;
    transition: background 0.15s;
}
.patient-item:hover {
    background: #161b22;
}
.patient-item.active {
    background: rgba(31, 111, 235, 0.1);
}

#upload-zone {
    background: #161b22;
    transition: border-color 0.2s;
}
#upload-zone:hover {
    border-color: #58a6ff !important;
}

.nav-tabs .nav-link {
    color: #8b949e;
    border: none;
    padding: 8px 16px;
    font-size: 13px;
}
.nav-tabs .nav-link.active {
    color: #58a6ff;
    border-bottom: 2px solid #58a6ff;
    background: transparent;
}

.table-dark {
    --bs-table-bg: transparent;
}

pre {
    font-size: 12px;
    line-height: 1.6;
}

.progress {
    background-color: #21262d;
}
```

- [ ] **Step 2: Verify visual appearance**

Open http://localhost:5000 and confirm the dark theme looks correct.

- [ ] **Step 3: Commit**

```bash
git add static/css/style.css
git commit -m "feat: add dark theme CSS"
```

---

### Task 15: Analytics Page

**Files:**
- Create: `templates/analytics.html`
- Modify: `app.py` (add /analytics-page route)

- [ ] **Step 1: Write analytics.html**

```html
<!-- templates/analytics.html -->
{% extends "base.html" %}
{% block head %}
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
{% endblock %}
{% block content %}
<div class="row mt-3">
    <div class="col-md-4">
        <div class="card bg-dark border-secondary">
            <div class="card-body">
                <h6 class="card-title text-muted">Cancer Type Distribution</h6>
                <canvas id="cancer-chart"></canvas>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card bg-dark border-secondary">
            <div class="card-body">
                <h6 class="card-title text-muted">Treatment Approaches</h6>
                <canvas id="treatment-chart"></canvas>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card bg-dark border-secondary">
            <div class="card-body">
                <h6 class="card-title text-muted">Extraction Confidence</h6>
                <canvas id="confidence-chart"></canvas>
            </div>
        </div>
    </div>
</div>
{% endblock %}
{% block scripts %}
<script>
fetch('/analytics')
    .then(r => r.json())
    .then(data => {
        // Cancer types
        new Chart(document.getElementById('cancer-chart'), {
            type: 'doughnut',
            data: {
                labels: Object.keys(data.cancer_types || {}),
                datasets: [{
                    data: Object.values(data.cancer_types || {}),
                    backgroundColor: ['#58a6ff', '#3fb950', '#d29922', '#f85149']
                }]
            },
            options: { plugins: { legend: { labels: { color: '#8b949e' }}}}
        });

        // Treatments
        new Chart(document.getElementById('treatment-chart'), {
            type: 'bar',
            data: {
                labels: Object.keys(data.treatments || {}),
                datasets: [{
                    data: Object.values(data.treatments || {}),
                    backgroundColor: '#58a6ff'
                }]
            },
            options: {
                plugins: { legend: { display: false }},
                scales: {
                    x: { ticks: { color: '#8b949e' }},
                    y: { ticks: { color: '#8b949e' }}
                }
            }
        });

        // Confidence
        const conf = data.confidence || {};
        new Chart(document.getElementById('confidence-chart'), {
            type: 'doughnut',
            data: {
                labels: ['High', 'Medium', 'Low'],
                datasets: [{
                    data: [conf.high || 0, conf.medium || 0, conf.low || 0],
                    backgroundColor: ['#238636', '#9e6a03', '#da3633']
                }]
            },
            options: { plugins: { legend: { labels: { color: '#8b949e' }}}}
        });
    });
</script>
{% endblock %}
```

- [ ] **Step 2: Add /analytics-page route to app.py**

```python
@app.route('/analytics-page')
def analytics_page():
    return render_template('analytics.html', session_active=(session.status == 'complete'))
```

Update the nav link in `base.html` to point to `/analytics-page` instead of `/analytics`.

- [ ] **Step 3: Commit**

```bash
git add templates/analytics.html
git commit -m "feat: add analytics page with Chart.js visualizations"
```

---

### Task 16: End-to-End Integration Test

No new files — this is a manual verification of the full pipeline.

- [ ] **Step 1: Ensure Ollama is running**

```bash
ollama serve &
ollama pull llama3.1:8b
```

- [ ] **Step 2: Run the full pipeline**

```bash
python app.py
```

1. Open http://localhost:5000
2. Upload `data/hackathon-mdt-outcome-proformas.docx`
3. Verify patient count is ~50
4. Click "Start Extraction" — watch progress
5. Go to /review — browse patients, switch category tabs, edit a field
6. Go to /analytics-page — verify charts render
7. Click "Export Excel" — open the downloaded file and compare columns against `hackathon-database-prototype.xlsx`

- [ ] **Step 3: Fix any issues found during integration**

Common issues to watch for:
- Parser splits patients incorrectly → adjust regex in `docx_parser.py`
- LLM returns wrong format → adjust prompt in `prompt_builder.py`
- Excel columns misaligned → check `field_schema.yaml` column numbers
- SSE disconnects → add reconnection logic in `app.js`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete end-to-end MDT extraction pipeline"
```

---

### Task 17: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README.md**

Cover: what it does, setup instructions (Python, Ollama, model pull, pip install, run), screenshots/workflow description, architecture overview, troubleshooting (reference the spec's troubleshooting guide), DTAC considerations.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and usage instructions"
```
