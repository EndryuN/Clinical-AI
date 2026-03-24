# extractor/preview_renderer.py
"""
Render a PatientBlock's raw_cells into a 6-section preview image:

  1. Meeting Date       — full-width banner from patient.mdt_date
  2. Patient Details    — demographics (row 1 col 0)
  3. Cancer Target Dates — target dates (row 0 col 1 / row 1 col 1)
  4. Staging & Diagnosis(g) — rows 2-3 content
  5. Clinical Details(f)    — rows 4-5 freeform text
  6. MDT Outcome(h)         — rows 6-7 freeform text

Saves {patient_id}.png and {patient_id}.json (cell coordinate map) to out_dir.
The coord map uses original raw_cells row,col keys so source_cell highlighting works.
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

from models import PatientBlock

# Layout
IMG_WIDTH = 800
SECTION_HEADER_H = 28
CELL_PADDING = 6
SPLIT_LEFT = IMG_WIDTH * 55 // 100   # 55% for left column
SPLIT_RIGHT = IMG_WIDTH - SPLIT_LEFT  # 45% for right column

# Colours
_HEADER_BG = (55, 90, 130)       # dark blue section header
_HEADER_TEXT = (220, 230, 245)    # light text on header
_MEETING_BG = (35, 65, 100)      # darker blue meeting banner
_MEETING_TEXT = (180, 220, 255)
_CONTENT_BG = (30, 30, 35)       # dark content area (matches app dark theme)
_CONTENT_TEXT = (220, 220, 220)   # light grey text
_BORDER = (60, 65, 75)


def _font(size: int = 11) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _sanitize(text: str) -> str:
    """Replace Unicode characters that Pillow's default font can't render."""
    return (text
            .replace('\u2013', '-')   # en-dash → hyphen
            .replace('\u2014', '-')   # em-dash → hyphen
            .replace('\u2018', "'")   # left single quote
            .replace('\u2019', "'")   # right single quote
            .replace('\u201c', '"')   # left double quote
            .replace('\u201d', '"')   # right double quote
            .replace('\u2026', '...')  # ellipsis
            .replace('\u00a0', ' ')   # non-breaking space
            .replace('\u2022', '-')   # bullet
            .replace('\ufffd', '?')   # replacement character
            )


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
            if draw.textlength(word, font=font) > max_px:
                while word and draw.textlength(word + '…', font=font) > max_px:
                    word = word[:-1]
                word = word + '…'
            current = word
    if current:
        lines.append(current)
    return lines or ['']


def _draw_text_block(draw, x, y, w, h, text, font, color, padding=CELL_PADDING, max_lines=None,
                     coverage_spans=None):
    """Draw wrapped text inside a rectangle.

    If coverage_spans provided, colour each character: green=used, amber=unused.
    Returns list of drawn lines.
    """
    if not text:
        return []
    raw_text = text
    text = _sanitize(text)
    max_w = w - padding * 2
    lines = _wrap(text, font, max_w, draw)
    bb = draw.textbbox((0, 0), 'Ag', font=font)
    line_h = (bb[3] - bb[1]) + 2
    if max_lines is None:
        max_lines = max(1, (h - padding * 2) // line_h)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines[-1]:
            lines[-1] = lines[-1][:-1] + '…'

    # Build per-character used/unused map from coverage spans
    char_used = None
    if coverage_spans:
        char_used = [False] * len(raw_text)
        for span in coverage_spans:
            if span.get("used"):
                for ci in range(span["start"], min(span["end"], len(raw_text))):
                    char_used[ci] = True

    ty = y + padding
    char_offset = 0  # track position in original text
    for line in lines:
        if char_used and line:
            # Draw character by character with colour
            tx = x + padding
            for ch in line:
                # Find this char in the original text
                while char_offset < len(raw_text) and raw_text[char_offset] in ('\n', '\r'):
                    char_offset += 1
                is_used = char_used[char_offset] if char_offset < len(char_used) else False
                ch_color = (100, 200, 100) if is_used else (255, 160, 50)  # green / amber
                draw.text((tx, ty), ch, font=font, fill=ch_color)
                tx += draw.textlength(ch, font=font)
                char_offset += 1
            # Skip the space/newline between lines
            char_offset += 1
        else:
            draw.text((x + padding, ty), line, font=font, fill=color)
            char_offset += len(line) + 1
        ty += line_h
    return lines


def _content_height(text: str, width: int, font, draw, padding=CELL_PADDING, min_h=50, max_h=200):
    """Calculate needed height for text content."""
    if not text:
        return min_h
    text = _sanitize(text)
    max_w = width - padding * 2
    lines = _wrap(text, font, max_w, draw)
    bb = draw.textbbox((0, 0), 'Ag', font=font)
    line_h = (bb[3] - bb[1]) + 2
    needed = padding * 2 + len(lines) * line_h
    return max(min_h, min(needed, max_h))


def render_patient_preview(patient: PatientBlock, out_dir: str) -> dict:
    """Render 6-section preview. Returns coord map {"{row},{col}": {x,y,w,h}}."""
    if not patient.raw_cells:
        return {}

    # Build row→col→text lookup from raw_cells
    row_map: dict[int, dict[int, str]] = {}
    for cell in patient.raw_cells:
        r, c = cell['row'], cell['col']
        row_map.setdefault(r, {})[c] = cell.get('text', '') or ''

    # Helper to get cell text
    def cell(r, c):
        return row_map.get(r, {}).get(c, '').strip()

    # Extract section content from raw_cells (sanitize all text for Pillow rendering)
    # Section headers from row 0, 2, 4, 6
    patient_details_label = _sanitize(cell(0, 0) or "Patient Details")
    cancer_dates_label = _sanitize(cell(0, 1) if cell(0, 1) and 'target' in cell(0, 1).lower() else "Cancer Target Dates")
    staging_label = _sanitize(cell(2, 0) or "Staging & Diagnosis(g)")
    clinical_label = _sanitize(cell(4, 0) or "Clinical Details(f):")
    mdt_label = _sanitize(cell(6, 0) or "MDT Outcome(h)")

    # Section content from rows 1, 3, 5, 7
    patient_details_text = cell(1, 0)
    # Replace full name with initials for privacy in preview
    if patient.initials and patient_details_text:
        lines = patient_details_text.split('\n')
        cleaned = []
        for line in lines:
            stripped = line.strip()
            # Skip lines that are the patient name (no colon prefix, not a number, not DOB/gender)
            if (stripped and ':' not in stripped
                    and not stripped[0].isdigit()
                    and stripped.lower() not in ('male', 'female')
                    and 'age' not in stripped.lower()):
                cleaned.append(patient.initials)
            else:
                cleaned.append(line)
        patient_details_text = '\n'.join(cleaned)
    cancer_dates_text = cell(1, 1) or cell(0, 1)  # fallback to header col 1 if row 1 has no col 1

    # Staging: combine all cols from row 3
    staging_texts = []
    for c_idx in sorted(row_map.get(3, {}).keys()):
        t = cell(3, c_idx)
        if t:
            staging_texts.append((c_idx, t))

    # Clinical details: combine rows 4-5 text (skip header row 4)
    clinical_parts = []
    for r in (4, 5):
        for c_idx in sorted(row_map.get(r, {}).keys()):
            t = cell(r, c_idx)
            # Skip if it's just the section header label
            if r == 4 and 'clinical' in t.lower() and 'details' in t.lower():
                continue
            if t:
                clinical_parts.append(t)
    clinical_text = '\n'.join(clinical_parts)

    # MDT outcome: combine rows 6-7 text (skip header row 6)
    mdt_parts = []
    for r in (6, 7):
        for c_idx in sorted(row_map.get(r, {}).keys()):
            t = cell(r, c_idx)
            if r == 6 and 'mdt' in t.lower() and 'outcome' in t.lower():
                continue
            if t:
                mdt_parts.append(t)
    mdt_text = '\n'.join(mdt_parts)

    # Meeting date
    meeting_date = patient.mdt_date or ""
    meeting_text = f"MDT Meeting: {meeting_date}" if meeting_date else "MDT Meeting Date: —"

    # --- Calculate layout heights ---
    # Create temp image for text measurement
    tmp_img = Image.new('RGB', (IMG_WIDTH, 10))
    tmp_draw = ImageDraw.Draw(tmp_img)
    font_normal = _font(11)
    font_bold = _font(12)
    font_header = _font(11)

    meeting_h = 30
    details_h = _content_height(patient_details_text, SPLIT_LEFT, font_normal, tmp_draw, min_h=80, max_h=140)
    dates_h = _content_height(cancer_dates_text, SPLIT_RIGHT, font_normal, tmp_draw, min_h=80, max_h=140)
    row2_h = max(details_h, dates_h)

    staging_h = 0
    if len(staging_texts) == 1:
        staging_h = _content_height(staging_texts[0][1], IMG_WIDTH, font_normal, tmp_draw, min_h=60, max_h=160)
    elif len(staging_texts) >= 2:
        h_left = _content_height(staging_texts[0][1], SPLIT_LEFT, font_normal, tmp_draw, min_h=60, max_h=160)
        h_right = _content_height(staging_texts[1][1], SPLIT_RIGHT, font_normal, tmp_draw, min_h=60, max_h=160)
        staging_h = max(h_left, h_right)
    else:
        staging_h = 40

    clinical_h = _content_height(clinical_text, IMG_WIDTH, font_normal, tmp_draw, min_h=60, max_h=200)
    mdt_h = _content_height(mdt_text, IMG_WIDTH, font_normal, tmp_draw, min_h=60, max_h=200)

    total_height = (meeting_h +
                    SECTION_HEADER_H + row2_h +       # Patient Details + Cancer Dates
                    SECTION_HEADER_H + staging_h +     # Staging
                    SECTION_HEADER_H + clinical_h +    # Clinical Details
                    SECTION_HEADER_H + mdt_h)          # MDT Outcome

    # --- Render ---
    img = Image.new('RGB', (IMG_WIDTH, total_height), _CONTENT_BG)
    draw = ImageDraw.Draw(img)
    coords: dict[str, dict] = {}
    y = 0

    # --- Section 1: Meeting Date banner ---
    draw.rectangle([0, y, IMG_WIDTH - 1, y + meeting_h - 1], fill=_MEETING_BG, outline=_BORDER)
    draw.text((CELL_PADDING, y + 6), meeting_text, font=font_bold, fill=_MEETING_TEXT)
    # Store coord for synthetic MDT header cell (row=-1) so source highlighting works
    coords['-1,0'] = {'x': 0, 'y': y, 'w': IMG_WIDTH, 'h': meeting_h}
    y += meeting_h

    # --- Section 2+3: Patient Details | Cancer Target Dates ---
    # Header bar
    draw.rectangle([0, y, SPLIT_LEFT - 1, y + SECTION_HEADER_H - 1], fill=_HEADER_BG, outline=_BORDER)
    draw.text((CELL_PADDING, y + 5), patient_details_label, font=font_header, fill=_HEADER_TEXT)
    draw.rectangle([SPLIT_LEFT, y, IMG_WIDTH - 1, y + SECTION_HEADER_H - 1], fill=_HEADER_BG, outline=_BORDER)
    draw.text((SPLIT_LEFT + CELL_PADDING, y + 5), cancer_dates_label, font=font_header, fill=_HEADER_TEXT)
    # Store coords for header row cells
    coords['0,0'] = {'x': 0, 'y': y, 'w': SPLIT_LEFT, 'h': SECTION_HEADER_H}
    coords['0,1'] = {'x': SPLIT_LEFT, 'y': y, 'w': SPLIT_RIGHT, 'h': SECTION_HEADER_H}
    y += SECTION_HEADER_H

    # Content
    draw.rectangle([0, y, SPLIT_LEFT - 1, y + row2_h - 1], fill=_CONTENT_BG, outline=_BORDER)
    _draw_text_block(draw, 0, y, SPLIT_LEFT, row2_h, patient_details_text, font_normal, _CONTENT_TEXT)
    coords['1,0'] = {'x': 0, 'y': y, 'w': SPLIT_LEFT, 'h': row2_h}

    draw.rectangle([SPLIT_LEFT, y, IMG_WIDTH - 1, y + row2_h - 1], fill=_CONTENT_BG, outline=_BORDER)
    _draw_text_block(draw, SPLIT_LEFT, y, SPLIT_RIGHT, row2_h, cancer_dates_text, font_normal, _CONTENT_TEXT)
    coords['1,1'] = {'x': SPLIT_LEFT, 'y': y, 'w': SPLIT_RIGHT, 'h': row2_h}
    y += row2_h

    # --- Section 4: Staging & Diagnosis ---
    draw.rectangle([0, y, IMG_WIDTH - 1, y + SECTION_HEADER_H - 1], fill=_HEADER_BG, outline=_BORDER)
    draw.text((CELL_PADDING, y + 5), staging_label, font=font_header, fill=_HEADER_TEXT)
    coords['2,0'] = {'x': 0, 'y': y, 'w': IMG_WIDTH, 'h': SECTION_HEADER_H}
    y += SECTION_HEADER_H

    if len(staging_texts) >= 2:
        # Two columns: diagnosis | staging TNM
        draw.rectangle([0, y, SPLIT_LEFT - 1, y + staging_h - 1], fill=_CONTENT_BG, outline=_BORDER)
        _draw_text_block(draw, 0, y, SPLIT_LEFT, staging_h, staging_texts[0][1], font_normal, _CONTENT_TEXT)
        coords[f'3,{staging_texts[0][0]}'] = {'x': 0, 'y': y, 'w': SPLIT_LEFT, 'h': staging_h}

        draw.rectangle([SPLIT_LEFT, y, IMG_WIDTH - 1, y + staging_h - 1], fill=_CONTENT_BG, outline=_BORDER)
        _draw_text_block(draw, SPLIT_LEFT, y, SPLIT_RIGHT, staging_h, staging_texts[1][1], font_normal, _CONTENT_TEXT)
        coords[f'3,{staging_texts[1][0]}'] = {'x': SPLIT_LEFT, 'y': y, 'w': SPLIT_RIGHT, 'h': staging_h}
    elif len(staging_texts) == 1:
        draw.rectangle([0, y, IMG_WIDTH - 1, y + staging_h - 1], fill=_CONTENT_BG, outline=_BORDER)
        _draw_text_block(draw, 0, y, IMG_WIDTH, staging_h, staging_texts[0][1], font_normal, _CONTENT_TEXT)
        coords[f'3,{staging_texts[0][0]}'] = {'x': 0, 'y': y, 'w': IMG_WIDTH, 'h': staging_h}
    else:
        draw.rectangle([0, y, IMG_WIDTH - 1, y + staging_h - 1], fill=_CONTENT_BG, outline=_BORDER)
        draw.text((CELL_PADDING, y + CELL_PADDING), "—", font=font_normal, fill=(100, 100, 100))
    y += staging_h

    # --- Section 5: Clinical Details ---
    draw.rectangle([0, y, IMG_WIDTH - 1, y + SECTION_HEADER_H - 1], fill=_HEADER_BG, outline=_BORDER)
    draw.text((CELL_PADDING, y + 5), clinical_label, font=font_header, fill=_HEADER_TEXT)
    coords['4,0'] = {'x': 0, 'y': y, 'w': IMG_WIDTH, 'h': SECTION_HEADER_H}
    y += SECTION_HEADER_H

    draw.rectangle([0, y, IMG_WIDTH - 1, y + clinical_h - 1], fill=_CONTENT_BG, outline=_BORDER)
    _draw_text_block(draw, 0, y, IMG_WIDTH, clinical_h, clinical_text, font_normal, _CONTENT_TEXT)
    coords['5,0'] = {'x': 0, 'y': y, 'w': IMG_WIDTH, 'h': clinical_h}
    y += clinical_h

    # --- Section 6: MDT Outcome ---
    draw.rectangle([0, y, IMG_WIDTH - 1, y + SECTION_HEADER_H - 1], fill=_HEADER_BG, outline=_BORDER)
    draw.text((CELL_PADDING, y + 5), mdt_label, font=font_header, fill=_HEADER_TEXT)
    coords['6,0'] = {'x': 0, 'y': y, 'w': IMG_WIDTH, 'h': SECTION_HEADER_H}
    y += SECTION_HEADER_H

    draw.rectangle([0, y, IMG_WIDTH - 1, y + mdt_h - 1], fill=_CONTENT_BG, outline=_BORDER)
    _draw_text_block(draw, 0, y, IMG_WIDTH, mdt_h, mdt_text, font_normal, _CONTENT_TEXT)
    coords['7,0'] = {'x': 0, 'y': y, 'w': IMG_WIDTH, 'h': mdt_h}
    y += mdt_h

    # --- Save ---
    file_id = patient.unique_id if patient.unique_id else patient.id
    png_path = os.path.join(out_dir, f'{file_id}.png')
    json_path = os.path.join(out_dir, f'{file_id}.json')
    img.save(png_path, 'PNG')
    with open(json_path, 'w') as f:
        json.dump(coords, f)

    # --- Generate coverage version if coverage data available ---
    if patient.coverage_map:
        _render_coverage_version(patient, out_dir, file_id, row_map, coords)

    return coords


def _render_coverage_version(patient, out_dir, file_id, row_map, coords):
    """Render a second PNG with green=used, amber=unused text colouring."""
    from PIL import Image as _Img, ImageDraw as _Draw

    def cell(r, c):
        return row_map.get(r, {}).get(c, '').strip()

    font_normal = _font(11)
    font_bold = _font(12)
    font_header = _font(11)

    # Rebuild the image from coords (we know the total height from max y+h)
    max_y = max(c['y'] + c['h'] for c in coords.values())
    img = _Img.new('RGB', (IMG_WIDTH, max_y), _CONTENT_BG)
    draw = _Draw.Draw(img)

    # Redraw section headers (not coverage-tracked)
    for key, coord in coords.items():
        row_idx = int(key.split(',')[0])
        col_idx = int(key.split(',')[1])

        # Header rows: redraw with original styling
        if row_idx in (0, 2, 4, 6):
            draw.rectangle([coord['x'], coord['y'], coord['x'] + coord['w'] - 1,
                           coord['y'] + coord['h'] - 1], fill=_HEADER_BG, outline=_BORDER)
            text = cell(row_idx, col_idx)
            if text:
                draw.text((coord['x'] + CELL_PADDING, coord['y'] + 5),
                         _sanitize(text), font=font_header, fill=_HEADER_TEXT)
        elif row_idx == -1:
            # Meeting date banner
            draw.rectangle([coord['x'], coord['y'], coord['x'] + coord['w'] - 1,
                           coord['y'] + coord['h'] - 1], fill=_MEETING_BG, outline=_BORDER)
            meeting_text = f"MDT Meeting: {patient.mdt_date}" if patient.mdt_date else "MDT Meeting Date: —"
            draw.text((CELL_PADDING, coord['y'] + 6), meeting_text, font=font_bold, fill=_MEETING_TEXT)
        else:
            # Content cell — draw with coverage colouring
            draw.rectangle([coord['x'], coord['y'], coord['x'] + coord['w'] - 1,
                           coord['y'] + coord['h'] - 1], fill=_CONTENT_BG, outline=_BORDER)
            text = cell(row_idx, col_idx)
            spans = patient.coverage_map.get(key, [])
            _draw_text_block(draw, coord['x'], coord['y'], coord['w'], coord['h'],
                           text, font_normal, _CONTENT_TEXT, coverage_spans=spans if spans else None)

    cov_path = os.path.join(out_dir, f'{file_id}_coverage.png')
    img.save(cov_path, 'PNG')
