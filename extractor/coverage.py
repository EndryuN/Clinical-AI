"""Compute coverage map and percentage for a patient's text.

Coverage tracks which parts of the source text were used by extracted fields:
- verbatim: text matched by source_snippets
- unused: text not matched by any extracted field

Tracks ALL content cells (not just freeform) so the overlay can highlight
unused text across the entire document preview.
"""
from models import PatientBlock

# Section header rows — excluded from coverage (they're just labels)
_HEADER_ROWS = {0, 2, 4, 6}


def _merge_spans(spans: list[dict]) -> list[dict]:
    """Flatten spans into non-overlapping regions. Verbatim takes priority over unused."""
    if not spans:
        return []

    # Find the total range
    max_end = max(s["end"] for s in spans)

    # Build a character-level map: each position is "verbatim" or "unused"
    # Verbatim wins over unused when they overlap
    char_type = ["unused"] * max_end
    for span in spans:
        if span.get("type") == "verbatim" or span.get("used"):
            for i in range(span["start"], min(span["end"], max_end)):
                char_type[i] = "verbatim"

    # Collapse runs into spans
    if not char_type:
        return []

    result = []
    cur_type = char_type[0]
    cur_start = 0
    for i in range(1, len(char_type)):
        if char_type[i] != cur_type:
            is_used = cur_type == "verbatim"
            result.append({"start": cur_start, "end": i, "used": is_used, "type": cur_type})
            cur_type = char_type[i]
            cur_start = i
    # Final span
    is_used = cur_type == "verbatim"
    result.append({"start": cur_start, "end": len(char_type), "used": is_used, "type": cur_type})

    return result


def compute_coverage(patient: PatientBlock) -> None:
    """Compute coverage_map and coverage stats for a patient.

    Sets patient.coverage_map, patient.coverage_pct, and
    patient.coverage_stats in-place.
    """
    if not patient.raw_cells:
        return

    # Track ALL content cells (skip section headers which are just labels)
    content_cells = [c for c in patient.raw_cells
                     if c["row"] not in _HEADER_ROWS and c.get("text", "").strip()]

    if not content_cells:
        patient.coverage_pct = None
        return

    total_chars = sum(len(c.get("text", "")) for c in content_cells)
    if total_chars == 0:
        patient.coverage_pct = None
        return

    # Initialise all content cell spans as unused
    coverage_map: dict[str, list[dict]] = {}
    for cell in content_cells:
        key = f"{cell['row']},{cell['col']}"
        text_len = len(cell.get("text", ""))
        if text_len > 0:
            coverage_map[key] = [{"start": 0, "end": text_len, "used": False, "type": "unused"}]

    # Mark spans from extracted source_snippets
    inferred_count = 0

    for group_name, fields in patient.extractions.items():
        for field_key, fr in fields.items():
            if fr.value is None:
                continue

            if fr.confidence_basis == "freeform_inferred":
                inferred_count += 1
                continue

            if not fr.source_snippet or not fr.source_cell:
                continue

            cell_key = f"{fr.source_cell['row']},{fr.source_cell['col']}"
            if cell_key not in coverage_map:
                continue

            # Find the matching cell text
            cell_text = ""
            for cell in content_cells:
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
                coverage_map[cell_key].append({
                    "start": idx, "end": end,
                    "used": True, "type": "verbatim",
                })
                start = idx + 1

    # Merge spans per cell
    for key in coverage_map:
        coverage_map[key] = _merge_spans(coverage_map[key])

    patient.coverage_map = coverage_map

    # Compute stats
    total_verbatim = 0
    total_unused = 0
    for spans in coverage_map.values():
        for span in spans:
            length = span["end"] - span["start"]
            if span.get("type") == "verbatim":
                total_verbatim += length
            else:
                total_unused += length

    verbatim_pct = round(total_verbatim / total_chars * 100, 1) if total_chars > 0 else 0.0
    unused_pct = round(total_unused / total_chars * 100, 1) if total_chars > 0 else 0.0
    patient.coverage_pct = verbatim_pct

    patient.coverage_stats = {
        "verbatim_pct": verbatim_pct,
        "inferred_fields": inferred_count,
        "unused_pct": unused_pct,
        "total_chars": total_chars,
    }
