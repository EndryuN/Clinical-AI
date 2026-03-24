# Confidence, Provenance & Self-Contained Excel Design

**Date:** 2026-03-23
**Status:** Draft v3 — pending user approval

---

## Overview

Redesign the confidence system, field provenance tracking, unused-text coverage, and Excel export so that a single `.xlsx` file produced on a powerful extraction machine (home PC with LLM) can be loaded on any other machine (laptop, no DOCX, no LLM) with full review functionality: previews, confidence colours, source highlighting, field-to-source links, unused-text toggle, editing, and re-export. Every extracted field must remain traceable back to the exact cell it came from through the entire pipeline and round-trip.

---

## 1. Unique Patient Identifier

**Problem:** NHS numbers and MRNs can be absent. The current fallback `PATIENT_NNN` is not human-readable or collision-resistant across batches.

**Format:**
```
{MDT_date}_{initials}_{gender_initial}_{disambiguator}
```

**MDT date encoding:** Normalised to `DDMMYYYY` (no separators, no slashes) at assignment time. If MDT date is absent → `00000000`.

**Gender encoding:** `M` / `F` / `U` (unknown if absent or unrecognised).

**Fallback chain for disambiguator:**
1. MRN available → use full MRN
2. MRN absent, NHS available → use last 4 digits of NHS number
3. Neither available → use zero-padded row index (`001`, `002`, …)

**Examples:**
```
07032025_AO_M_9990001     ← MRN available
07032025_BK_F_1234        ← NHS last 4
00000000_CJ_U_003         ← no MDT date, no MRN/NHS
```

**Assignment timing:** `unique_id` is assigned **after** regex extraction completes, not at parse time, because gender comes from the Demographics regex group. `PatientBlock.unique_id` starts as `""` and is populated by `regex_extractor.py` once the Demographics group is complete.

**Collision handling (within-batch only):** If two patients in the same batch produce the same `unique_id`, append `_b` to the second and `_c` to the third (max 26 per batch). Uniqueness is only guaranteed within a single uploaded document; cross-batch deduplication is out of scope.

**Preview file naming:** Preview PNGs and coordinate JSONs are saved as `{patient.unique_id}.png` / `{patient.unique_id}.json`. After migration, the `/patient/<patient_id>/preview` route accepts `unique_id` as the URL segment. Legacy `patient.id` is kept as an attribute for internal lookups during transition but is not used for file storage or routing.

---

## 2. Confidence System Rework

### 2.1 Confidence Basis Enum

`FieldResult` gains a `confidence_basis` field. The old `confidence` string field is **kept as a computed property** that maps back to `high/medium/low/none` for backward API compatibility (analytics routes, summary helpers).

| Basis | Colour | Meaning |
|---|---|---|
| `structured_verbatim` | 🟢 Green | Extracted by regex from a structured cell (rows 0–3: demographics, staging headers). Value exists verbatim in source. |
| `freeform_verbatim` | 🟠 Orange | From a freeform cell (rows 4–7: clinical details, MDT outcome). Value **exists verbatim** in freeform source text (LLM located it; did not invent it). |
| `freeform_inferred` | 🔴 Red | LLM inferred or reformatted. Value does **not** exist verbatim in any freeform cell text, or format was changed (e.g. date normalisation, abbreviation expansion). |
| `edited` | ⚪ Grey | Clinician manually overrode. Set by the edit endpoint, not by extraction. |
| `absent` | — | Field not present in document. `value = None`. No colour fill. |

**Computed `confidence` property mapping (for API backward compat):**
```
structured_verbatim  → "high"
freeform_verbatim    → "medium"
freeform_inferred    → "low"
edited               → "medium"   (conservative — human edit acknowledged but not verified)
absent               → "none"
```

### 2.2 Verbatim Check

After LLM returns a value for a field, determine `confidence_basis` as follows:

1. **Use `source_snippet` first** (the raw matched text stored by the extractor). If `source_snippet` is set and is a substring of any freeform cell (rows 4–7) text → `freeform_verbatim`.
2. **Fall back to normalised value** only when `source_snippet` is absent. Check whether the normalised value (case-insensitive, stripped) is a substring of any freeform cell (rows 4–7) text → `freeform_verbatim`.
3. If neither match → `freeform_inferred`.

**Scope is freeform cells only (rows 4–7).** Structured cells (rows 0–3) are never searched in the verbatim check — a coincidental match there does not earn `freeform_verbatim`.

Regex extractions from rows 0–3 → always `structured_verbatim` (no check needed).
Regex extractions from rows 4–7 → always `freeform_verbatim` (regex means verbatim by definition).

### 2.3 Backward Mapping from Old Confidence

When importing a legacy Excel (Metadata sheet has a `confidence` column but no `confidence_basis` column):
- `high` → `structured_verbatim`
- `medium` → `freeform_verbatim`
- `low` → `freeform_inferred`
- `none` → `absent`

---

## 3. Updated FieldResult Model

```python
@dataclass
class FieldResult:
    value: Optional[str] = None
    confidence_basis: str = "absent"       # structured_verbatim | freeform_verbatim | freeform_inferred | edited | absent
    reason: str = ""                        # 1-sentence explanation
    edited: bool = False                    # True if clinician changed
    original_value: Optional[str] = None   # Pre-edit value
    source_cell: Optional[dict] = None     # {"row": int, "col": int} — links field to source document cell
    source_snippet: Optional[str] = None   # Exact text that was matched (max 200 chars, truncated with …)

    @property
    def confidence(self) -> str:
        """Backward-compatible confidence string for analytics and API responses."""
        mapping = {
            "structured_verbatim": "high",
            "freeform_verbatim": "medium",
            "freeform_inferred": "low",
            "edited": "medium",
            "absent": "none",
        }
        return mapping.get(self.confidence_basis, "none")
```

---

## 4. Updated PatientBlock Model

```python
@dataclass
class PatientBlock:
    id: str                           # Legacy MRN-based ID (kept for routing compatibility)
    unique_id: str = ""               # {MDT_date}_{initials}_{gender}_{disambiguator} — set post-regex
    initials: str = ""
    nhs_number: str = ""
    gender: str = ""
    mdt_date: str = ""
    raw_text: str = ""
    extractions: dict = field(default_factory=dict)
    raw_cells: list = field(default_factory=list)    # [{"row": int, "col": int, "text": str}] — full table
    coverage_map: dict = field(default_factory=dict) # {"{row},{col}": [{"start": int, "end": int, "used": bool}]}
    coverage_pct: Optional[float] = None             # Percentage of freeform text covered by extracted fields
```

---

## 5. Field-to-Source Links

Every `FieldResult` with a non-absent value **must** have a populated `source_cell` that points to the exact cell in the patient table it came from. This is the traceable link that powers preview highlighting.

**Preservation through the full pipeline:**

| Stage | Requirement |
|---|---|
| Regex extraction | `source_cell` set from the row/col where the regex match was found |
| LLM extraction | `source_cell` resolved by searching `raw_cells` for the cell whose text contains the matched `source_snippet` (case-insensitive substring search, freeform cells rows 4–7 only). If no cell match is found, `source_cell = None`. Hard-coded row indices are never used. |
| Excel export | `source_cell_row` and `source_cell_col` written as separate integer columns in Metadata sheet |
| Excel import | `source_cell` reconstructed as `{"row": source_cell_row, "col": source_cell_col}` from Metadata sheet |
| Preview highlighting | `source_cell` → lookup in `{unique_id}.json` coordinate map → highlight cell rectangle in PNG |

**If `source_cell` cannot be determined** (e.g. LLM inferred a value with no textual anchor), it is set to `None`. The field still gets `freeform_inferred` basis. In the review UI, fields with `source_cell = None` show a "No source" indicator instead of a highlighted cell.

**The field-to-source link must survive the Excel round-trip.** After import on any machine, clicking a field in the review panel must still highlight the correct source cell in the regenerated preview image.

---

## 6. Coverage Map & Unused Text

### 6.1 Computation

After all extraction (regex + LLM) completes for a patient:

1. For each `raw_cell`, initialise spans covering the full text length as `used: false`
2. For each `FieldResult` with a `source_snippet`, find all substring matches within that cell's text and mark those character ranges as `used: true`
3. Merge overlapping spans using a span-union algorithm before storing (prevents double-rendering in the UI overlay)

Result stored in `PatientBlock.coverage_map`:
```json
{
  "5,0": [
    {"start": 0, "end": 42, "used": true},
    {"start": 43, "end": 118, "used": false},
    {"start": 119, "end": 200, "used": true}
  ]
}
```

### 6.2 Coverage Percentage

```
coverage_pct = total_used_chars / total_chars_across_freeform_cells × 100
```

Only freeform cells (rows 4–7) are counted. Structured cells (rows 0–3) are excluded.

If all freeform cells are empty → `coverage_pct = None` (not 0%, to distinguish "nothing to cover" from "nothing was covered").

### 6.3 UI Toggle

A toggle button in the review panel labelled **"Show unused text"**. When active:
- Unused text spans are underlined/highlighted (amber) in the preview image overlay via SVG
- Used spans are shown normally
- A badge next to the toggle shows `73% covered` (hidden if `coverage_pct = None`)
- If the patient was loaded from a legacy Excel (no coverage data) → toggle is disabled with tooltip "Coverage data not available"

Toggle state is per-patient and held in JS memory only (not persisted).

---

## 7. Self-Contained Excel Format

### 7.1 Sheet Structure

| Sheet | Visibility | Purpose |
|---|---|---|
| **Prototype V1** | Visible | Patient data — one row per patient, all 88 field columns |
| **Metadata** | Hidden | Per-field provenance and confidence |
| **RawCells** | Hidden | Full table cell content + coverage spans per patient |

### 7.2 Prototype V1 Sheet

Column 0 = `unique_id` (new, prepended before existing field columns). Existing field columns shift right by 1.

Cell colour coding:
- 🟢 Green fill — `structured_verbatim`
- 🟠 Orange fill + italic text — `freeform_verbatim`
- 🔴 Red fill — `freeform_inferred`
- ⚪ No fill — `absent`
- Grey fill — `edited` (original value stored in Metadata sheet and accessible via cell comment)

**Edited cells:** Grey fill on current value. The original pre-edit value is written as a cell comment (openpyxl `Comment` object) so it is visible on hover in Excel. Full edit history is in the Metadata sheet.

### 7.3 Metadata Sheet

Row 1: `SOURCE_FILE | {filename}`
Row 2: **Named column headers** (import reads by header name, not position)

| Column Header | Content |
|---|---|
| `unique_id` | Patient unique identifier |
| `field_key` | Field key (e.g. `dob`, `mrn`, `mmr_status`) |
| `confidence_basis` | One of the 5 basis values |
| `reason` | Explanation string |
| `source_cell_row` | Integer row index (blank if no source cell) |
| `source_cell_col` | Integer col index (blank if no source cell) |
| `source_snippet` | Exact matched text, max 200 chars (truncated with `…`) |
| `edited` | `true` / `false` |
| `original_value` | Pre-edit value if edited, else blank |
| `coverage_pct` | Patient-level coverage % (repeated per field row for convenience; blank if None) |

**Import reads columns by header name** (header row lookup first, then data rows). This is resilient to future column reordering and distinguishes legacy from new-format files.

**Legacy detection:** If row 2 contains a `confidence` column but no `confidence_basis` column → apply §2.3 backward mapping.

### 7.4 RawCells Sheet

Row 1: **Named column headers**

| Column Header | Content |
|---|---|
| `unique_id` | Patient unique identifier |
| `row` | Cell row index |
| `col` | Cell col index |
| `text` | Full cell text content |
| `coverage_json` | JSON string of merged span list `[{"start": int, "end": int, "used": bool}]` |

One row per cell per patient. Actual row count depends on document table shape (not assumed to be 8×3).

---

## 8. Excel Import (Laptop Round-Trip)

When loading a `.xlsx` on any machine (no DOCX, no LLM required):

1. **Detect format:** Check for `RawCells` sheet and `confidence_basis` column in Metadata → new format. Otherwise → legacy format.
2. **Read RawCells sheet** (new format only):
   - Rebuild `PatientBlock.raw_cells` as `[{"row", "col", "text"}]`
   - Rebuild `coverage_map` from `coverage_json` column
3. **Regenerate preview PNGs** from `raw_cells` using `preview_renderer.py`:
   - Preview renderer uses actual row count from `raw_cells`, not a fixed 8-row assumption
   - Saves `{unique_id}.png` + `{unique_id}.json` to `static/previews/{timestamp}/`
4. **Read Metadata sheet** by header name:
   - Restore `FieldResult` objects with `confidence_basis`, `reason`, `source_cell`, `source_snippet`, `edited`, `original_value`
5. **Read Prototype V1:**
   - Restore field values (cross-check: Metadata values take precedence if conflict)
   - Column 0 = `unique_id`
6. **Set session status** → `complete` (skip extraction, go straight to review)
7. **Field-to-source links:** `source_cell` from Metadata → maps to `{row},{col}` key in regenerated coordinate JSON → preview highlighting works immediately
8. **Coverage toggle:** functional for new-format files; disabled for legacy files

**Legacy import:** No RawCells sheet → `raw_cells = []`, previews not available, coverage toggle disabled. All other functionality (editing, re-export) works.

---

## 9. Affected Files

| File | Change |
|---|---|
| `models.py` | Add `unique_id`, `gender`, `mdt_date`, `coverage_map`, `coverage_pct` to `PatientBlock`; add `confidence_basis` + computed `confidence` property to `FieldResult`; keep legacy `confidence` field as property |
| `parser/docx_parser.py` | Extract `gender` and `mdt_date` into `PatientBlock` at parse time (for later `unique_id` assembly) |
| `extractor/regex_extractor.py` | Set `confidence_basis` based on source cell row (0–3 → `structured_verbatim`, 4–7 → `freeform_verbatim`); assign `unique_id` to `PatientBlock` after Demographics group completes |
| `extractor/response_parser.py` | Run verbatim check (freeform cells only, `source_snippet` first) after LLM response; set `freeform_verbatim` vs `freeform_inferred` |
| `extractor/coverage.py` | **New file** — compute `coverage_map` and `coverage_pct` per patient using span-union algorithm |
| `export/excel_writer.py` | Write RawCells sheet; write `unique_id` column (col 0); use `confidence_basis` for cell colours; write cell comments for edited originals; name all Metadata columns by header |
| `app.py` | (1) `_import_excel()` — read by header name, read RawCells, regenerate previews, restore coverage_map, handle legacy; (2) edit endpoint — set `confidence_basis = "edited"` on manual change; (3) `_confidence_summary()` and analytics routes — use computed `confidence` property (no change needed if property is correct); (4) preview route — use `unique_id` for file lookup |
| `extractor/preview_renderer.py` | Use `patient.unique_id` for file naming; use actual row count from `raw_cells` instead of fixed 8 |
| `templates/review.html` | Add coverage toggle button + percentage badge; wire up unused-text overlay; show "No source" indicator for fields with `source_cell = None` |
| `static/js/app.js` | Toggle logic: apply SVG span highlights from `coverage_map` over preview image; disable toggle + hide badge for legacy imports |

---

## 10. Out of Scope

- Re-extraction on the laptop (no LLM required — review/edit/export only)
- Multi-user collaboration or shared patient database
- PDF or other input formats
- Changes to the 88-field schema or group definitions
- Cross-batch patient deduplication
