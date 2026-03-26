"""Compute coverage: what percentage of source document words were extracted.

Coverage tracks ALL content cells in the document (not just freeform rows).
- Words matched by source_snippets from HIGH or MEDIUM confidence fields count as "used"
- LOW confidence (inferred) fields don't appear in source text, so don't count
- Everything else is "unused" — text that no field extracted from
"""
from models import PatientBlock

# Section header rows — excluded (they're just labels like "Patient Details", "Staging & Diagnosis(g)")
_HEADER_ROWS = {0, 2, 4, 6}


def _merge_spans(spans: list[dict]) -> list[dict]:
    """Flatten spans into non-overlapping regions. Used takes priority over unused."""
    if not spans:
        return []

    max_end = max(s["end"] for s in spans)
    if max_end <= 0:
        return []

    # Build character-level map: "used" wins over "unused" when they overlap
    char_used = [False] * max_end
    for span in spans:
        if span.get("used"):
            for i in range(span["start"], min(span["end"], max_end)):
                char_used[i] = True

    # Collapse runs into spans
    result = []
    cur_used = char_used[0]
    cur_start = 0
    for i in range(1, len(char_used)):
        if char_used[i] != cur_used:
            result.append({"start": cur_start, "end": i, "used": cur_used})
            cur_used = char_used[i]
            cur_start = i
    result.append({"start": cur_start, "end": len(char_used), "used": cur_used})

    return result


def compute_coverage(patient: PatientBlock) -> None:
    """Compute coverage_map and coverage stats for a patient.

    Counts all words across all content cells. Fields with source_snippets
    (structured_verbatim or freeform_verbatim) mark those character ranges as used.
    Freeform_inferred fields are counted separately — they don't appear in source.
    """
    if not patient.raw_cells:
        return

    # All content cells (skip section headers which are just labels)
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
            coverage_map[key] = [{"start": 0, "end": text_len, "used": False}]

    # Count inferred fields (low confidence — not in source text)
    inferred_count = 0

    # Mark used spans from source_snippets of HIGH and MEDIUM confidence fields
    for group_name, fields in patient.extractions.items():
        for field_key, fr in fields.items():
            if fr.value is None:
                continue

            # Low confidence = inferred by LLM, not in source → doesn't count as coverage
            if fr.confidence_basis == "freeform_inferred":
                inferred_count += 1
                continue

            # Need both source_snippet and source_cell to mark text as used
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

            # Find all occurrences of source_snippet in cell text and mark as used
            snippet_lower = fr.source_snippet.lower()
            text_lower = cell_text.lower()
            start = 0
            while True:
                idx = text_lower.find(snippet_lower, start)
                if idx == -1:
                    break
                end = idx + len(fr.source_snippet)
                coverage_map[cell_key].append({"start": idx, "end": end, "used": True})
                start = idx + 1

    # Merge spans per cell (flatten overlaps)
    for key in coverage_map:
        coverage_map[key] = _merge_spans(coverage_map[key])

    patient.coverage_map = coverage_map

    # Compute stats from merged spans
    total_used = 0
    total_unused = 0
    for spans in coverage_map.values():
        for span in spans:
            length = span["end"] - span["start"]
            if span["used"]:
                total_used += length
            else:
                total_unused += length

    used_pct = round(total_used / total_chars * 100, 1) if total_chars > 0 else 0.0
    unused_pct = round(total_unused / total_chars * 100, 1) if total_chars > 0 else 0.0
    patient.coverage_pct = used_pct

    patient.coverage_stats = {
        "used_pct": used_pct,         # % of source text matched by extracted fields (high+medium)
        "unused_pct": unused_pct,     # % of source text not matched by any field
        "inferred_fields": inferred_count,  # number of fields inferred (not in source)
        "total_chars": total_chars,
    }


def recompute_coverage_stats(patient: PatientBlock) -> None:
    """Recompute coverage_stats from an already-populated coverage_map.

    Used after Excel import where coverage_map spans are restored but
    coverage_stats was not persisted.
    """
    if not patient.coverage_map:
        return

    total_used = 0
    total_unused = 0
    for spans in patient.coverage_map.values():
        for span in spans:
            length = span["end"] - span["start"]
            if span.get("used"):
                total_used += length
            else:
                total_unused += length

    total_chars = total_used + total_unused
    if total_chars == 0:
        return

    # Count inferred fields
    inferred_count = 0
    for group_name, fields in patient.extractions.items():
        for field_key, fr in fields.items():
            if fr.value is not None and fr.confidence_basis == "freeform_inferred":
                inferred_count += 1

    used_pct = round(total_used / total_chars * 100, 1)
    unused_pct = round(total_unused / total_chars * 100, 1)

    patient.coverage_pct = used_pct
    patient.coverage_stats = {
        "used_pct": used_pct,
        "unused_pct": unused_pct,
        "inferred_fields": inferred_count,
        "total_chars": total_chars,
    }
