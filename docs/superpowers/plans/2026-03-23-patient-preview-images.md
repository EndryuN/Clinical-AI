# Patient Preview Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the right source panel on the review page with a Pillow-rendered PNG of each patient's MDT table, with confidence-coloured highlights drawn on a canvas overlay when a field row is clicked.

**Architecture:** `extractor/preview_renderer.py` renders each patient's `raw_cells` to a PNG + JSON coord map at upload time. A new Flask route `/patient/<id>/preview` serves the image URL and coord map. The review page replaces `renderSourceTable`/`renderDocPreview` with an `<img>`+`<canvas>` stack; `highlightSource()` is rewritten to draw rectangles on canvas using annotation-marker-to-row mapping.

**Tech Stack:** Pillow (new), existing Flask/JS/python-docx stack.

---

## File Structure

| File | Change | Responsibility |
|------|--------|---------------|
| `extractor/preview_renderer.py` | **Create** | Pillow rendering + coord map |
| `tests/test_preview_renderer.py` | **Create** | Unit tests for renderer |
| `requirements.txt` | **Modify** | Add `Pillow>=10.0` |
| `app.py` | **Modify** | Call renderer post-parse; add `/patient/<id>/preview` route |
| `static/js/app.js` | **Modify** | Add `MARKER_TO_ROWS`; rewrite `highlightSource`; update `loadPatient`; remove `renderSourceTable`/`renderDocPreview` |
| `templates/review.html` | **Modify** | Replace source panel with `<img>`+`<canvas>`; remove doc-preview div |

---

## Task 1: Preview Renderer Module

**Files:**
- Create: `extractor/preview_renderer.py`
- Create: `tests/test_preview_renderer.py`
- Modify: `requirements.txt`

### Background

`PatientBlock.raw_cells` is a list of `{"row": int, "col": int, "text": str}` dicts (8 rows × 3 cols for the standard MDT table). The renderer draws this as a styled table PNG and saves a coord map `{"{row},{col}": {"x","y","w","h"}}` alongside it.

The document table structure is:
- Row 0: header (Patient Details / Cancer Target Dates) — blue background
- Row 1: demographics (Hospital/NHS number, name, DOB, gender) — light grey
- Row 2: staging/diagnosis header
- Row 3: staging/diagnosis content
- Row 4: clinical details header
- Row 5: clinical details content
- Row 6: MDT outcome header
- Row 7: MDT outcome content

Header rows (0, 2, 4, 6) get a blue-tinted background and bold text; content rows get white/grey.

- [ ] **Step 1: Add Pillow to requirements.txt**

```
Pillow>=10.0
```

Run: `pip install Pillow`
Expected: Pillow installs successfully.

- [ ] **Step 2: Write failing tests**

Create `tests/test_preview_renderer.py`:

```python
# tests/test_preview_renderer.py
import json
import pytest
from PIL import Image

from extractor.preview_renderer import render_patient_preview
from models import PatientBlock


def _patient_with_full_cells():
    """8×3 table with realistic content."""
    texts = {
        (0, 0): 'Patient Details(a)(b)(c)(d)(e)',
        (0, 1): 'Patient Details(a)(b)(c)(d)(e)',
        (0, 2): 'Cancer Target Dates',
        (1, 0): 'Hospital Number: H001\nNHS Number: 9990000001\nJohn Smith\nMale\nDOB: 01/01/1960',
        (1, 1): 'Hospital Number: H001\nNHS Number: 9990000001\nJohn Smith\nMale\nDOB: 01/01/1960',
        (1, 2): '',
        (2, 0): 'Staging & Diagnosis(g)',
        (2, 1): '',
        (2, 2): '',
        (3, 0): 'Diagnosis: Rectal adenocarcinoma\nT3N1M0',
        (3, 1): 'Diagnosis: Rectal adenocarcinoma\nT3N1M0',
        (3, 2): '',
        (4, 0): 'Clinical Details(f)',
        (4, 1): '',
        (4, 2): '',
        (5, 0): 'Colonoscopy: Polyp at 10cm. Biopsy taken.',
        (5, 1): 'Colonoscopy: Polyp at 10cm. Biopsy taken.',
        (5, 2): '',
        (6, 0): 'MDT Outcome(h)',
        (6, 1): '',
        (6, 2): '',
        (7, 0): 'Outcome: Anterior resection. MMR proficient.',
        (7, 1): 'Outcome: Anterior resection. MMR proficient.',
        (7, 2): '',
    }
    cells = [{'row': r, 'col': c, 'text': texts.get((r, c), '')} for r in range(8) for c in range(3)]
    return PatientBlock(id='H001', initials='JS', nhs_number='9990000001', raw_cells=cells)


def test_render_creates_png(tmp_path):
    render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    assert (tmp_path / 'H001.png').exists()


def test_render_creates_json(tmp_path):
    render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    assert (tmp_path / 'H001.json').exists()


def test_coord_map_covers_all_cells(tmp_path):
    coords = render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    for r in range(8):
        for c in range(3):
            assert f'{r},{c}' in coords, f'Missing coord for row={r} col={c}'


def test_coord_map_json_matches_return_value(tmp_path):
    coords = render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    with open(tmp_path / 'H001.json') as f:
        saved = json.load(f)
    assert coords == saved


def test_image_width_is_800(tmp_path):
    render_patient_preview(_patient_with_full_cells(), str(tmp_path))
    img = Image.open(tmp_path / 'H001.png')
    assert img.width == 800


def test_render_empty_cells_doesnt_crash(tmp_path):
    cells = [{'row': r, 'col': c, 'text': ''} for r in range(8) for c in range(3)]
    patient = PatientBlock(id='EMPTY', raw_cells=cells)
    render_patient_preview(patient, str(tmp_path))
    assert (tmp_path / 'EMPTY.png').exists()


def test_render_returns_empty_dict_for_no_cells(tmp_path):
    patient = PatientBlock(id='NOCELLS', raw_cells=[])
    result = render_patient_preview(patient, str(tmp_path))
    assert result == {}
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
pytest tests/test_preview_renderer.py -v
```

Expected: `ModuleNotFoundError: No module named 'extractor.preview_renderer'`

- [ ] **Step 4: Implement `extractor/preview_renderer.py`**

```python
# extractor/preview_renderer.py
"""
Render a PatientBlock's raw_cells table to a PNG image using Pillow.
Saves {patient_id}.png and {patient_id}.json (cell coordinate map) to out_dir.
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

from models import PatientBlock

# Layout constants
IMG_WIDTH = 800
COL_WIDTHS = [480, 160, 160]  # 60% / 20% / 20%
HEADER_ROW_HEIGHT = 36        # rows 0, 2, 4, 6 (section headers)
CONTENT_ROW_HEIGHT = 72       # rows 1, 3, 5, 7 (data content — 72px gives 4 lines at 11px + padding)
CELL_PADDING = 6

# Header rows by table row index
_HEADER_ROWS = {0, 2, 4, 6}

# Background colours (RGB)
_BG = {
    0: (217, 225, 242),   # row 0 — blue section header
    2: (217, 225, 242),   # row 2 — blue section header
    4: (217, 225, 242),   # row 4 — blue section header
    6: (217, 225, 242),   # row 6 — blue section header
    1: (242, 242, 242),   # row 1 — light grey demographics
}
_DEFAULT_BG = (255, 255, 255)
_BORDER_COLOUR = (180, 180, 180)
_TEXT_COLOUR = (26, 26, 26)


def _font(size: int = 11) -> ImageFont.FreeTypeFont:
    """Return a PIL font at the requested size. Falls back gracefully."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Pillow < 10: load_default() takes no size argument
        return ImageFont.load_default()


def _wrap(text: str, font, max_px: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Wrap text into lines that fit within max_px pixels wide."""
    if not text:
        return []
    words = text.replace('\n', ' \n ').split(' ')
    lines: list[str] = []
    current = ''
    for word in words:
        if word == '\n':
            lines.append(current)
            current = ''
            continue
        test = (current + ' ' + word).strip() if current else word
        w = draw.textlength(test, font=font)
        if w <= max_px:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ['']


def render_patient_preview(patient: PatientBlock, out_dir: str) -> dict:
    """
    Render patient's raw_cells table to a PNG + JSON coord map.

    Returns the coordinate map dict {"{row},{col}": {"x","y","w","h"}}.
    Returns {} if patient has no raw_cells (e.g. imported from Excel).
    """
    if not patient.raw_cells:
        return {}

    # Build row→col→text lookup
    row_map: dict[int, dict[int, str]] = {}
    for cell in patient.raw_cells:
        r, c = cell['row'], cell['col']
        row_map.setdefault(r, {})[c] = cell.get('text', '') or ''

    num_rows = max(row_map) + 1

    # Per-row heights
    row_heights = [
        HEADER_ROW_HEIGHT if r in _HEADER_ROWS else CONTENT_ROW_HEIGHT
        for r in range(num_rows)
    ]
    total_height = sum(row_heights)

    img = Image.new('RGB', (IMG_WIDTH, total_height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    font_normal = _font(11)
    font_bold = _font(12)

    coords: dict[str, dict] = {}
    y = 0

    for r in range(num_rows):
        h = row_heights[r]
        is_header = r in _HEADER_ROWS
        bg = _BG.get(r, _DEFAULT_BG)
        x = 0

        for c, col_w in enumerate(COL_WIDTHS):
            # Draw cell
            draw.rectangle([x, y, x + col_w - 1, y + h - 1], fill=bg, outline=_BORDER_COLOUR)
            coords[f'{r},{c}'] = {'x': x, 'y': y, 'w': col_w, 'h': h}

            text = row_map.get(r, {}).get(c, '').strip()
            if text:
                font = font_bold if is_header else font_normal
                max_w = col_w - CELL_PADDING * 2
                lines = _wrap(text, font, max_w, draw)
                # Cap at 4 lines; ellipsize last if truncated
                if len(lines) > 4:
                    lines = lines[:4]
                    lines[-1] = lines[-1][:-1] + '…' if lines[-1] else '…'
                ty = y + CELL_PADDING
                line_h = draw.textbbox((0, 0), 'Ag', font=font)[3] + 2
                for line in lines:
                    draw.text((x + CELL_PADDING, ty), line, font=font, fill=_TEXT_COLOUR)
                    ty += line_h

            x += col_w
        y += h

    png_path = os.path.join(out_dir, f'{patient.id}.png')
    json_path = os.path.join(out_dir, f'{patient.id}.json')
    img.save(png_path, 'PNG')
    with open(json_path, 'w') as f:
        json.dump(coords, f)

    return coords
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_preview_renderer.py -v
```

Expected: 7 tests pass.

- [ ] **Step 6: Commit**

```bash
git add extractor/preview_renderer.py tests/test_preview_renderer.py requirements.txt
git commit -m "feat: add Pillow preview renderer for patient MDT tables"
```

---

## Task 2: Flask Integration

**Files:**
- Modify: `app.py` (upload route ~line 93, imports ~line 18)

### Background

The upload route parses the DOCX at line 93: `patients = parse_docx(file_path)`. The timestamp prefix of the uploaded filename (`session.file_name`) is used as the preview directory name — e.g. `"1742123456_report.docx"` → timestamp `"1742123456"`. This convention is already established and documented at line 63 of `app.py`.

The new route `/patient/<patient_id>/preview` reads the pre-generated JSON coord map and returns `{"image_url": "...", "coords": {...}}`.

- [ ] **Step 1: Add import at top of `app.py`**

After line 21 (`from extractor.prompt_builder import ...`), add:

```python
from extractor.preview_renderer import render_patient_preview
```

- [ ] **Step 2: Add preview rendering call inside the upload route**

In the `.docx` branch (after `session.status = 'parsed'` at ~line 95), add:

```python
            # Render patient preview images (non-fatal if Pillow unavailable)
            # log_event is already used throughout app.py with signature (event_name, **kwargs)
            try:
                ts = safe_name.split('_')[0]
                preview_dir = os.path.join('static', 'previews', ts)
                os.makedirs(preview_dir, exist_ok=True)
                for p in patients:
                    render_patient_preview(p, preview_dir)
            except Exception as preview_err:
                log_event('preview_render_error', error=str(preview_err))
```

- [ ] **Step 3: Add the preview route**

Add after the existing `/patients/<patient_id>` route (~line 466):

```python
@app.route('/patient/<patient_id>/preview')
def patient_preview(patient_id):
    """Return rendered image URL and cell coordinate map for the patient."""
    patient = next((p for p in session.patients if p.id == patient_id), None)
    if not patient:
        return jsonify({"error": "not found"}), 404
    if not session.file_name:
        return jsonify({"error": "no file"}), 404
    ts = session.file_name.split('_')[0]
    json_path = os.path.join('static', 'previews', ts, f'{patient_id}.json')
    if not os.path.exists(json_path):
        return jsonify({"error": "preview not available"}), 404
    with open(json_path) as f:
        coords = json.load(f)
    return jsonify({
        "image_url": f"/static/previews/{ts}/{patient_id}.png",
        "coords": coords,
    })
```

Note: `json` is already imported in `app.py` (check top of file; if not, add `import json`).

- [ ] **Step 4: Verify manually**

Start the Flask app, upload the test DOCX, then visit:
`http://localhost:5000/patient/<first_patient_id>/preview`

Expected: JSON with `image_url` and `coords` dict with 24 keys (`0,0` through `7,2`).

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: render patient previews on upload, add /patient/<id>/preview route"
```

---

## Task 3: Review Page — HTML + JS

**Files:**
- Modify: `templates/review.html`
- Modify: `static/js/app.js`

### Background

**Current layout** (`review.html`):
- Left column (50%): field table (flex:1) + doc-preview div (fixed 260px height)
- Right column (flex:1): `#source-panel` containing `#source-table` (HTML cell divs)

**New layout**:
- Left column (50%): field table only (full height — remove doc-preview)
- Right column (flex:1): `#source-panel` containing `<img id="preview-img">` + `<canvas id="preview-canvas">` overlay

**Current JS functions being replaced/removed:**
- `renderSourceTable(rawCells)` — **remove** (lines 432–476)
- `renderDocPreview(rawCells)` — **remove** (lines 478–516)
- `highlightSource(fr)` — **rewrite** (lines 518–566) — was DOM-based, now canvas-based
- `loadPatient(patientId)` — **modify** (lines 388–430) — remove raw_cells calls, add preview fetch

**New JS constant** `MARKER_TO_ROWS` maps annotation markers to table row indices.

- [ ] **Step 1: Update `templates/review.html`**

Replace the entire `<!-- Field Table + Source Panel side by side -->` section (lines 49–91) with:

```html
        <!-- Field Table + Source Panel side by side -->
        <div class="d-flex flex-grow-1" style="min-height:0;">

            <!-- Left: Field Table (full height) -->
            <div class="overflow-auto p-3" style="flex:0 0 50%; min-width:0; min-height:0;">
                <table class="table table-dark table-sm table-hover">
                    <thead>
                        <tr>
                            <th style="width:30%">Field</th>
                            <th style="width:45%">Value</th>
                            <th style="width:25%" class="text-center">Confidence</th>
                        </tr>
                    </thead>
                    <tbody id="field-table-body">
                        <tr><td colspan="3" class="text-muted text-center py-4">Select a patient from the sidebar</td></tr>
                    </tbody>
                </table>
            </div>

            <!-- Right: Patient Document Preview (image + canvas highlight overlay) -->
            <div id="source-panel" class="border-start border-secondary overflow-auto p-3" style="flex:1; min-width:0;">
                <div class="text-muted small text-uppercase mb-1" style="font-size:10px; letter-spacing:0.5px;">Source Document</div>
                <div id="source-warning" class="d-none alert alert-danger py-1 small mt-1 mb-2">
                    Value not found in source document — possible hallucination
                </div>
                <div id="preview-container" style="position:relative; display:inline-block; width:100%;">
                    <img id="preview-img" src="" alt="" style="display:none; width:100%; border:1px solid #333; border-radius:4px;">
                    <canvas id="preview-canvas" style="position:absolute; top:0; left:0; pointer-events:none; width:100%; height:100%;"></canvas>
                </div>
                <span id="preview-placeholder" class="text-muted small">Select a patient to view source document</span>
            </div>

        </div>
```

- [ ] **Step 2: Add `MARKER_TO_ROWS` constant to `app.js`**

At the top of the review page functions section (after `let allPatientExtractions = {};` around line 329), add:

```javascript
// Maps LLM source_snippet annotation markers to MDT table row indices
const MARKER_TO_ROWS = {
    '(a)': [1], '(b)': [1], '(c)': [1], '(d)': [1], '(e)': [1],
    '(f)': [4, 5],
    '(g)': [2, 3],
    '(h)': [6, 7],
    '(i)': [0],
};
```

- [ ] **Step 3: Update `loadPatient()` in `app.js`**

In `loadPatient()` (starts ~line 388), replace the calls to `renderSourceTable` and `renderDocPreview` with a preview fetch. The `data` object from `/patients/${patientId}` no longer needs `raw_cells` on the client side.

Find these lines:
```javascript
            renderSourceTable(data.raw_cells || []);
            renderDocPreview(data.raw_cells || []);
            window._currentRawCells = data.raw_cells || [];
```

Replace with:
```javascript
            // Load rendered preview image and coord map
            window._previewCoords = null;
            const previewImg = document.getElementById('preview-img');
            const previewPlaceholder = document.getElementById('preview-placeholder');
            fetch(`/patient/${patientId}/preview`)
                .then(r => r.json())
                .then(preview => {
                    if (preview.image_url && previewImg) {
                        window._previewCoords = preview.coords;
                        previewImg.onload = function() {
                            const canvas = document.getElementById('preview-canvas');
                            if (canvas) {
                                canvas.width = previewImg.clientWidth;
                                canvas.height = previewImg.clientHeight;
                            }
                        };
                        previewImg.onerror = function() {
                            previewImg.style.display = 'none';
                            if (previewPlaceholder) previewPlaceholder.style.display = '';
                        };
                        previewImg.src = preview.image_url;
                        previewImg.style.display = 'block';
                        if (previewPlaceholder) previewPlaceholder.style.display = 'none';
                    }
                })
                .catch(() => {});
```

- [ ] **Step 4: Rewrite `highlightSource()` in `app.js`**

Replace the entire `highlightSource(fr)` function (lines 518–566) with:

```javascript
function highlightSource(fr) {
    const canvas = document.getElementById('preview-canvas');
    const img = document.getElementById('preview-img');
    const warning = document.getElementById('source-warning');

    if (warning) warning.classList.add('d-none');
    if (!canvas || !img || img.naturalWidth === 0) return;

    // Sync canvas pixel dimensions to current rendered image size
    canvas.width = img.clientWidth;
    canvas.height = img.clientHeight;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!fr || fr.value === null || fr.value === undefined) return;

    const rows = MARKER_TO_ROWS[fr.source_snippet];
    if (!rows || !window._previewCoords) {
        if (fr.value !== null && fr.value !== '' && warning) warning.classList.remove('d-none');
        return;
    }

    const scaleX = img.clientWidth / img.naturalWidth;
    const scaleY = img.clientHeight / img.naturalHeight;

    const conf = fr.confidence || 'low';
    const colours = {
        high:   { fill: 'rgba(25,135,84,0.25)',  stroke: '#198754' },
        medium: { fill: 'rgba(249,115,22,0.20)',  stroke: '#f97316' },
        low:    { fill: 'rgba(220,53,69,0.25)',   stroke: '#dc3545' },
    };
    const colour = colours[conf] || colours.low;

    ctx.fillStyle = colour.fill;
    ctx.strokeStyle = colour.stroke;
    ctx.lineWidth = 2;

    for (const row of rows) {
        for (let col = 0; col < 3; col++) {
            const cell = window._previewCoords[`${row},${col}`];
            if (!cell) continue;
            const x = cell.x * scaleX;
            const y = cell.y * scaleY;
            const w = cell.w * scaleX;
            const h = cell.h * scaleY;
            ctx.fillRect(x, y, w, h);
            ctx.strokeRect(x, y, w, h);
        }
    }
}
```

- [ ] **Step 5: Remove `renderSourceTable` and `renderDocPreview` from `app.js`**

Delete the two functions entirely:
- `renderSourceTable(rawCells)` (lines 432–476)
- `renderDocPreview(rawCells)` (lines 478–516)

These are no longer called anywhere.

- [ ] **Step 6: Smoke test in browser**

1. Start Flask: `python app.py`
2. Upload the test DOCX
3. Navigate to `/review`
4. Click a patient — right panel should show the rendered PNG
5. Click a field row — canvas should draw a coloured highlight over the matching table rows
6. Click a field with `source_snippet = "(h)"` — rows 6–7 (MDT Outcome) should highlight

- [ ] **Step 7: Commit**

```bash
git add templates/review.html static/js/app.js
git commit -m "feat: replace source panel with rendered patient preview image and canvas highlighting"
```

---

## End-to-End Verification

- [ ] Full upload → extract → review flow: each patient shows preview image
- [ ] High confidence field: green highlight on correct rows
- [ ] Medium confidence field: orange highlight
- [ ] Low confidence field: red highlight
- [ ] Field with `source_snippet = null` (regex-extracted with no annotation): warning banner shown
- [ ] Patient imported from Excel (no preview file): placeholder text shown, no JS error
- [ ] Window resize: canvas re-syncs on next field click (correct because canvas is resized inside `highlightSource`)
