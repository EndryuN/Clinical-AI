# Patient Preview Images — Design Spec

**Goal:** Replace the right source panel on the review page with a rendered image of the patient's MDT table, with field-level highlighting driven by the LLM's `source_snippet` annotation marker.

**Architecture:** Pillow renders each patient's `raw_cells` to a PNG at upload time. A JSON sidecar stores per-cell pixel bounding boxes. On the review page, an `<img>` + `<canvas>` overlay replaces the current HTML source table. Clicking a field draws a highlight rectangle on the canvas over the matching table rows.

**Tech Stack:** Pillow (new dependency), existing Flask/JS stack.

---

## 1. Rendering (`extractor/preview_renderer.py`)

A new module with one public function:

```python
def render_patient_preview(patient: PatientBlock, out_dir: str) -> dict:
    """
    Render patient's raw_cells table to PNG and return cell coordinate map.

    Saves:
      {out_dir}/{patient.id}.png   — rendered table image
      {out_dir}/{patient.id}.json  — {"{row},{col}": {"x","y","w","h"}} map

    Returns the coordinate map dict.
    """
```

**Rendering spec:**
- Canvas: white background, 800px wide, height computed from row count
- Row heights: header rows (row 0) 36px, content rows 60px (to accommodate wrapped text)
- Column widths: proportional — col 0: 60%, col 1: 20%, col 2: 20%
- Cell borders: 1px `#cccccc` lines
- Header row 0 background: `#d9e1f2` (light blue, matching Word default table header)
- Row 1 background (demographics): `#f2f2f2`
- All other rows: white
- Text: 11px, black, `#1a1a1a`, Pillow default font (no external font dependency)
- Cell text padding: 4px inset from cell edges, wraps within cell width
- Long text is truncated with `…` if it exceeds 4 lines per cell

**Coordinate map format:**
```json
{
  "0,0": {"x": 0, "y": 0, "w": 480, "h": 36},
  "1,0": {"x": 0, "y": 36, "w": 480, "h": 60},
  ...
}
```

---

## 2. Storage

Preview images are stored under Flask's `static/` directory so they can be served directly:

```
static/previews/{session_file_timestamp}/{patient_id}.png
static/previews/{session_file_timestamp}/{patient_id}.json
```

`session_file_timestamp` is the numeric prefix already prepended to uploaded filenames (e.g. `1742123456`). This ties previews to a specific upload and avoids collisions on re-upload.

The `static/previews/` directory is created if absent. Old preview directories are not cleaned up automatically (acceptable for a local clinical tool).

---

## 3. Integration in `app.py`

After `parse_docx()` succeeds in the `/upload` route:

```python
from extractor.preview_renderer import render_patient_preview
import os

preview_dir = os.path.join('static', 'previews', session_file_timestamp)
os.makedirs(preview_dir, exist_ok=True)
for patient in patients:
    render_patient_preview(patient, preview_dir)
```

New route:

```python
@app.route('/patient/<patient_id>/preview')
def patient_preview(patient_id):
    """Return image URL and cell coordinate map for the patient."""
    patient = _get_patient(patient_id)
    if not patient:
        return jsonify({"error": "not found"}), 404
    ts = session.file_name.split('_')[0]  # extract timestamp prefix
    base = f"/static/previews/{ts}/{patient_id}"
    json_path = os.path.join('static', 'previews', ts, f"{patient_id}.json")
    if not os.path.exists(json_path):
        return jsonify({"error": "preview not available"}), 404
    with open(json_path) as f:
        coords = json.load(f)
    return jsonify({"image_url": f"{base}.png", "coords": coords})
```

---

## 4. Annotation marker → table row mapping

The LLM returns `source_snippet` as one of `(a)`–`(i)`. Map to table rows (0-indexed):

| Marker | Section | Rows |
|--------|---------|------|
| `(a)` DOB | Demographics | 1 |
| `(b)` Name | Demographics | 1 |
| `(c)` NHS Number | Demographics | 1 |
| `(d)` Hospital Number | Demographics | 1 |
| `(e)` Gender | Demographics | 1 |
| `(f)` Clinical Details | Clinical Details | 4, 5 |
| `(g)` Staging & Diagnosis | Staging/Histology | 2, 3 |
| `(h)` MDT Outcome | MDT Outcome | 6, 7 |
| `(i)` MDT Date | Header | 0 |
| `null` | Unknown | — (no highlight) |

This mapping lives as a constant in `app.js`.

---

## 5. Review page changes

### `templates/review.html`

Replace the right source panel div:

```html
<!-- Right: Patient Document Preview -->
<div id="source-panel" class="border-start border-secondary overflow-auto p-3" style="flex:1; min-width:0;">
    <div class="text-muted small text-uppercase mb-1">Source Document</div>
    <div id="source-warning" class="d-none alert alert-danger py-1 small mt-1 mb-2">
        Value not found in source document — possible hallucination
    </div>
    <div id="preview-container" style="position:relative; display:inline-block;">
        <img id="preview-img" src="" alt="" style="display:none; max-width:100%; border:1px solid #333;">
        <canvas id="preview-canvas" style="position:absolute; top:0; left:0; pointer-events:none;"></canvas>
    </div>
    <span id="preview-placeholder" class="text-muted small">Select a patient to view source document</span>
</div>
```

### `static/js/app.js`

**On patient load** (`loadPatient()`): fetch `/patient/{id}/preview`, store coords in `window._previewCoords`, set `<img>` src, size canvas to match image natural dimensions on load.

**`highlightSource(fr)` rewrite:**
```javascript
function highlightSource(fr) {
    const canvas = document.getElementById('preview-canvas');
    const img = document.getElementById('preview-img');
    if (!canvas || !img || !window._previewCoords) return;

    const scaleX = img.clientWidth / img.naturalWidth;
    const scaleY = img.clientHeight / img.naturalHeight;
    const ctx = canvas.getContext('2d');
    canvas.width = img.clientWidth;
    canvas.height = img.clientHeight;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const rows = MARKER_TO_ROWS[fr.source_snippet] || [];
    if (rows.length === 0) {
        showSourceWarning(true);
        return;
    }
    showSourceWarning(false);

    ctx.fillStyle = 'rgba(59, 130, 246, 0.25)';
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;

    // Highlight all cells in the matching rows
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

**`MARKER_TO_ROWS` constant** defined at module level in `app.js`:
```javascript
const MARKER_TO_ROWS = {
    '(a)': [1], '(b)': [1], '(c)': [1], '(d)': [1], '(e)': [1],
    '(f)': [4, 5],
    '(g)': [2, 3],
    '(h)': [6, 7],
    '(i)': [0],
};
```

The existing `renderSourceTable()` and `renderDocPreview()` functions are removed. The bottom-left "Document Preview" panel in the layout is also removed (the image in the right panel serves this purpose).

---

## 6. Error handling

- If `render_patient_preview` fails for a patient (e.g. empty `raw_cells`), log the error and continue — other patients are unaffected
- If `/patient/<id>/preview` returns 404 (preview file missing), show placeholder text; do not break the review page
- If the image fails to load in the browser, `img.onerror` hides the image and shows the placeholder

---

## 7. Testing

- `tests/test_preview_renderer.py`:
  - `test_render_creates_png`: output PNG exists and is a valid image
  - `test_render_creates_json`: coord map has correct number of keys (rows × cols)
  - `test_coord_map_covers_all_cells`: every `{row},{col}` key present
  - `test_render_empty_cells_doesnt_crash`: patient with all-empty cells completes without error
  - `test_image_dimensions`: PNG width is 800px

---

## Out of scope

- Cleaning up old preview directories
- Rendering MDT header paragraphs (the paragraph before each table, e.g. "Colorectal MDT 07/03/2025") — these are already in `raw_text` and visible via the LLM extraction
- Multi-page patients (all patients fit in one table)
- Zoom / pan on the preview image
