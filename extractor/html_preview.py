"""Render a PatientBlock's raw_cells as HTML for the review panel.

Produces selectable text with data attributes for:
- Group colouring (data-group on extracted spans)
- Source cell identification (data-row, data-col on content divs)
- Coverage spans (data-used on character ranges)
- Field highlighting (CSS class toggle via JS)

The 6-section layout mirrors the PNG renderer:
1. Meeting Date
2. Patient Details | Cancer Target Dates
3. Staging & Diagnosis
4. Clinical Details
5. MDT Outcome
"""
import re
from html import escape


# Section header rows (blue headers, not content)
_HEADER_ROWS = {0, 2, 4, 6}


def _sanitize(text: str) -> str:
    """Replace Unicode characters that cause rendering issues."""
    return (text
            .replace('\u2013', '-')
            .replace('\u2014', '-')
            .replace('\u2018', "'")
            .replace('\u2019', "'")
            .replace('\u201c', '"')
            .replace('\u201d', '"')
            .replace('\u2026', '...')
            .replace('\u00a0', ' ')
            .replace('\u2022', '-')
            .replace('\ufffd', '?')
            )


def _build_coverage_html(text: str, spans: list) -> str:
    """Wrap text in <span> tags based on coverage spans.

    Used spans get class='cov-used', unused get class='cov-unused'.
    These classes are invisible by default, toggled via JS.
    """
    if not spans or not text:
        return escape(_sanitize(text))

    text = _sanitize(text)
    result = []
    last_end = 0

    for span in sorted(spans, key=lambda s: s['start']):
        start = max(span['start'], last_end)
        end = min(span['end'], len(text))
        if start > last_end:
            # Gap — treat as unused
            result.append(f'<span class="cov-unused">{escape(text[last_end:start])}</span>')
        if start < end:
            cls = 'cov-used' if span.get('used') else 'cov-unused'
            result.append(f'<span class="{cls}">{escape(text[start:end])}</span>')
        last_end = end

    if last_end < len(text):
        result.append(f'<span class="cov-unused">{escape(text[last_end:])}</span>')

    return ''.join(result)


def _build_extraction_map(patient) -> dict:
    """Build a map of source_cell → (group_name, field_key) for group colouring."""
    cell_to_group: dict[str, str] = {}
    for group_name, fields in patient.extractions.items():
        for field_key, fr in fields.items():
            if fr.source_cell and fr.value is not None:
                key = f"{fr.source_cell['row']},{fr.source_cell['col']}"
                cell_to_group[key] = group_name
    return cell_to_group


def render_html_preview(patient) -> str:
    """Render patient raw_cells as HTML with selectable text.

    Returns an HTML string to be injected into the review panel.
    """
    if not patient.raw_cells:
        return '<div class="preview-empty">No source data available</div>'

    # Build row→col→text lookup
    row_map: dict[int, dict[int, str]] = {}
    for cell in patient.raw_cells:
        r, c = cell['row'], cell['col']
        row_map.setdefault(r, {})[c] = cell.get('text', '') or ''

    def cell_text(r, c):
        return row_map.get(r, {}).get(c, '').strip()

    # Build extraction group map for colouring
    cell_groups = _build_extraction_map(patient)

    # Coverage map
    cov_map = patient.coverage_map or {}

    # Meeting date
    meeting_date = patient.mdt_date or ""
    meeting_text = f"MDT Meeting: {meeting_date}" if meeting_date else "MDT Meeting Date: —"

    # Section labels from headers
    patient_label = cell_text(0, 0) or "Patient Details"
    cancer_label = cell_text(0, 1) if cell_text(0, 1) and 'target' in cell_text(0, 1).lower() else "Cancer Target Dates"
    staging_label = cell_text(2, 0) or "Staging & Diagnosis(g)"
    clinical_label = cell_text(4, 0) or "Clinical Details(f):"
    mdt_label = cell_text(6, 0) or "MDT Outcome(h)"

    # Content
    details_text = cell_text(1, 0)
    cancer_text = cell_text(1, 1) or cell_text(0, 1)

    # Replace full name with initials in patient details
    if patient.initials and details_text:
        lines = details_text.split('\n')
        cleaned = []
        for line in lines:
            stripped = line.strip()
            if (stripped and ':' not in stripped
                    and not stripped[0].isdigit()
                    and stripped.lower() not in ('male', 'female')
                    and 'age' not in stripped.lower()):
                cleaned.append(patient.initials)
            else:
                cleaned.append(line)
        details_text = '\n'.join(cleaned)

    # Staging content (rows 2-3)
    staging_cells = []
    for c_idx in sorted(row_map.get(3, {}).keys()):
        t = cell_text(3, c_idx)
        if t:
            staging_cells.append((c_idx, t))

    # Clinical details (rows 4-5, skip header)
    clinical_parts = []
    for r in (4, 5):
        for c_idx in sorted(row_map.get(r, {}).keys()):
            t = cell_text(r, c_idx)
            if r == 4 and 'clinical' in t.lower() and 'details' in t.lower():
                continue
            if t:
                clinical_parts.append(t)
    clinical_text = '\n'.join(clinical_parts)

    # MDT outcome (rows 6-7, skip header)
    mdt_parts = []
    for r in (6, 7):
        for c_idx in sorted(row_map.get(r, {}).keys()):
            t = cell_text(r, c_idx)
            if r == 6 and 'mdt' in t.lower() and 'outcome' in t.lower():
                continue
            if t:
                mdt_parts.append(t)
    mdt_text = '\n'.join(mdt_parts)

    def _cell_html(row, col, text, full_width=False):
        """Render a single cell as HTML with data attributes and coverage."""
        key = f"{row},{col}"
        group = cell_groups.get(key, '')
        spans = cov_map.get(key, [])
        content = _build_coverage_html(text, spans) if spans else escape(_sanitize(text))
        group_attr = f' data-group="{escape(group)}"' if group else ''
        width_class = ' full-width' if full_width else ''
        return f'<div class="cell-content{width_class}" data-row="{row}" data-col="{col}"{group_attr}>{content}</div>'

    # Build HTML
    html_parts = []

    # Section 1: Meeting Date
    html_parts.append(f'''
    <div class="preview-section meeting-date">
        <div class="cell-content" data-row="-1" data-col="0">{escape(_sanitize(meeting_text))}</div>
    </div>''')

    # Section 2+3: Patient Details | Cancer Target Dates
    html_parts.append(f'''
    <div class="preview-section">
        <div class="section-header-row">
            <div class="section-header" data-row="0" data-col="0">{escape(_sanitize(patient_label))}</div>
            <div class="section-header" data-row="0" data-col="1">{escape(_sanitize(cancer_label))}</div>
        </div>
        <div class="section-row two-col">
            {_cell_html(1, 0, details_text)}
            {_cell_html(1, 1, cancer_text)}
        </div>
    </div>''')

    # Section 4: Staging & Diagnosis
    staging_content = ''
    if len(staging_cells) >= 2:
        staging_content = f'''<div class="section-row two-col">
            {_cell_html(3, staging_cells[0][0], staging_cells[0][1])}
            {_cell_html(3, staging_cells[1][0], staging_cells[1][1])}
        </div>'''
    elif len(staging_cells) == 1:
        staging_content = f'<div class="section-row">{_cell_html(3, staging_cells[0][0], staging_cells[0][1], full_width=True)}</div>'
    else:
        staging_content = '<div class="section-row"><div class="cell-content text-muted">—</div></div>'

    html_parts.append(f'''
    <div class="preview-section">
        <div class="section-header" data-row="2" data-col="0">{escape(_sanitize(staging_label))}</div>
        {staging_content}
    </div>''')

    # Section 5: Clinical Details
    html_parts.append(f'''
    <div class="preview-section">
        <div class="section-header" data-row="4" data-col="0">{escape(_sanitize(clinical_label))}</div>
        <div class="section-row">{_cell_html(5, 0, clinical_text, full_width=True)}</div>
    </div>''')

    # Section 6: MDT Outcome
    html_parts.append(f'''
    <div class="preview-section">
        <div class="section-header" data-row="6" data-col="0">{escape(_sanitize(mdt_label))}</div>
        <div class="section-row">{_cell_html(7, 0, mdt_text, full_width=True)}</div>
    </div>''')

    return f'<div class="preview-document">{"".join(html_parts)}</div>'
