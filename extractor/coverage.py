"""Compute coverage map and percentage for a patient's freeform text."""
from models import PatientBlock

# Freeform rows: clinical details (4,5) and MDT outcome (6,7)
_FREEFORM_ROWS = {4, 5, 6, 7}


def _merge_spans(spans: list[dict]) -> list[dict]:
    """Sort spans, merge overlapping same-value spans, fill gaps as unused."""
    if not spans:
        return []

    # Sort by start position
    spans = sorted(spans, key=lambda s: s["start"])

    # First pass: merge overlapping spans with same 'used' value
    merged = [spans[0].copy()]
    for span in spans[1:]:
        last = merged[-1]
        if span["used"] == last["used"] and span["start"] <= last["end"]:
            last["end"] = max(last["end"], span["end"])
        else:
            merged.append(span.copy())

    # Second pass: fill gaps between spans as unused
    filled = []
    for i, span in enumerate(merged):
        if i > 0 and merged[i - 1]["end"] < span["start"]:
            filled.append({"start": merged[i - 1]["end"], "end": span["start"], "used": False})
        filled.append(span)

    return filled


def compute_coverage(patient: PatientBlock) -> None:
    """Compute coverage_map and coverage_pct for a patient.

    Marks character spans as used/unused in freeform cells based on
    which source_snippets were extracted. Sets patient.coverage_map
    and patient.coverage_pct in-place.
    """
    if not patient.raw_cells:
        return

    # Identify freeform cells dynamically from raw_cells
    freeform_cells = [c for c in patient.raw_cells if c["row"] in _FREEFORM_ROWS]

    if not freeform_cells:
        patient.coverage_pct = None
        return

    # Check if there's any text at all in freeform cells
    total_chars = sum(len(c.get("text", "")) for c in freeform_cells)
    if total_chars == 0:
        patient.coverage_pct = None
        return

    # Initialise all freeform cell spans as unused
    coverage_map: dict[str, list[dict]] = {}
    for cell in freeform_cells:
        key = f"{cell['row']},{cell['col']}"
        text_len = len(cell.get("text", ""))
        if text_len > 0:
            coverage_map[key] = [{"start": 0, "end": text_len, "used": False}]

    # Mark used spans from extracted source_snippets
    for group_name, fields in patient.extractions.items():
        for field_key, fr in fields.items():
            if not fr.source_snippet or not fr.source_cell:
                continue
            cell_key = f"{fr.source_cell['row']},{fr.source_cell['col']}"
            if cell_key not in coverage_map:
                continue

            # Find the matching cell text
            cell_text = ""
            for cell in freeform_cells:
                if cell["row"] == fr.source_cell["row"] and cell["col"] == fr.source_cell["col"]:
                    cell_text = cell.get("text", "")
                    break

            if not cell_text:
                continue

            # Find all occurrences of source_snippet in cell text
            snippet_lower = fr.source_snippet.lower()
            text_lower = cell_text.lower()
            start = 0
            while True:
                idx = text_lower.find(snippet_lower, start)
                if idx == -1:
                    break
                end = idx + len(fr.source_snippet)
                # Add a used span
                coverage_map[cell_key].append({"start": idx, "end": end, "used": True})
                start = idx + 1

    # Merge spans per cell
    for key in coverage_map:
        coverage_map[key] = _merge_spans(coverage_map[key])

    patient.coverage_map = coverage_map

    # Compute coverage percentage
    total_used = 0
    for spans in coverage_map.values():
        for span in spans:
            if span["used"]:
                total_used += span["end"] - span["start"]

    patient.coverage_pct = round(total_used / total_chars * 100, 1) if total_chars > 0 else 0.0
