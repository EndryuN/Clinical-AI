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
HEADER_ROW_HEIGHT = 36        # rows 0, 2, 4, 6 (section headers)
CONTENT_ROW_HEIGHT = 72       # rows 1, 3, 5, 7 (data content — 72px gives 4 lines at 11px + padding)
CELL_PADDING = 6

# Column width presets by column count
_COL_PRESETS = {
    1: [800],
    2: [520, 280],           # 65% / 35%
    3: [480, 160, 160],      # 60% / 20% / 20%
}

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
    """Return a PIL FreeType font at the requested size. Requires Pillow >= 10."""
    return ImageFont.load_default(size=size)


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
            # If the word itself exceeds max_px, hard-truncate with ellipsis
            if draw.textlength(word, font=font) > max_px:
                while word and draw.textlength(word + '…', font=font) > max_px:
                    word = word[:-1]
                word = word + '…'
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

    # Determine column count from data (max col index + 1)
    num_cols = max((c['col'] for c in patient.raw_cells), default=0) + 1
    col_widths = _COL_PRESETS.get(num_cols)
    if col_widths is None:
        # Fallback: first column 60%, rest split equally
        first_w = IMG_WIDTH * 60 // 100
        rest_w = (IMG_WIDTH - first_w) // max(num_cols - 1, 1)
        col_widths = [first_w] + [rest_w] * (num_cols - 1)

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

        for c, col_w in enumerate(col_widths):
            # Draw cell
            draw.rectangle([x, y, x + col_w - 1, y + h - 1], fill=bg, outline=_BORDER_COLOUR)
            coords[f'{r},{c}'] = {'x': x, 'y': y, 'w': col_w, 'h': h}

            text = row_map.get(r, {}).get(c, '').strip()
            if text:
                font = font_bold if is_header else font_normal
                max_w = col_w - CELL_PADDING * 2
                lines = _wrap(text, font, max_w, draw)
                # Cap lines: header rows (36px) fit 1 line; content rows fit 4
                max_lines = 1 if is_header else 4
                if len(lines) > max_lines:
                    lines = lines[:max_lines]
                    lines[-1] = lines[-1][:-1] + '…' if lines[-1] else '…'
                ty = y + CELL_PADDING
                bb = draw.textbbox((0, 0), 'Ag', font=font)
                line_h = (bb[3] - bb[1]) + 2
                for line in lines:
                    draw.text((x + CELL_PADDING, ty), line, font=font, fill=_TEXT_COLOUR)
                    ty += line_h

            x += col_w
        y += h

    file_id = patient.unique_id if patient.unique_id else patient.id
    png_path = os.path.join(out_dir, f'{file_id}.png')
    json_path = os.path.join(out_dir, f'{file_id}.json')
    img.save(png_path, 'PNG')
    with open(json_path, 'w') as f:
        json.dump(coords, f)

    return coords
