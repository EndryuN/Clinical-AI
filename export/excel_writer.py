from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from config import get_all_fields, get_groups


def _get_group_colors() -> dict:
    """Build a mapping of field key → hex color from the schema groups."""
    colors = {}
    for group in get_groups():
        color = group.get('color', '#D9D9D9')
        # Remove the # prefix for openpyxl
        hex_color = color.lstrip('#')
        for field in group['fields']:
            colors[field['key']] = hex_color
    return colors


def write_excel(patients: list, output_path: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "Prototype V1"

    all_fields = get_all_fields()
    group_colors = _get_group_colors()

    # Header row with colour coding
    header_font = Font(bold=True, size=9)
    for field in all_fields:
        col = field['excel_column']
        cell = ws.cell(row=1, column=col, value=field['excel_header'])
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True, vertical='top')

        hex_color = group_colors.get(field['key'], 'D9D9D9')
        cell.fill = PatternFill(start_color=hex_color, end_color=hex_color, fill_type='solid')

    # Cell styles for confidence levels
    inferred_fill = PatternFill(start_color='D4EDFC', end_color='D4EDFC', fill_type='solid')  # light blue
    inferred_font = Font(italic=True, color='0066AA')
    low_fill = PatternFill(start_color='FCE4E4', end_color='FCE4E4', fill_type='solid')  # light red
    low_font = Font(color='CC0000')

    # Patient data rows
    for row_idx, patient in enumerate(patients, start=2):
        for group_name, fields in patient.extractions.items():
            for field_key, field_result in fields.items():
                col = _get_column(all_fields, field_key)
                if col and field_result.value is not None:
                    cell = ws.cell(row=row_idx, column=col, value=field_result.value)
                    field_def = _get_field_def(all_fields, field_key)
                    if field_def and field_def['type'] == 'date':
                        cell.number_format = 'DD/MM/YYYY'

                    # Highlight inferred values
                    reason = (field_result.reason or '').lower()
                    is_inferred = field_result.confidence == 'medium' or 'infer' in reason
                    if is_inferred:
                        cell.fill = inferred_fill
                        cell.font = inferred_font
                    elif field_result.confidence == 'low':
                        cell.fill = low_fill
                        cell.font = low_font

    # Add legend below data
    legend_row = ws.max_row + 2
    ws.cell(row=legend_row, column=1, value="Legend:").font = Font(bold=True)
    c1 = ws.cell(row=legend_row + 1, column=1, value="Inferred value (derived from context)")
    c1.fill = inferred_fill
    c1.font = inferred_font
    c2 = ws.cell(row=legend_row + 2, column=1, value="Low confidence (uncertain extraction)")
    c2.fill = low_fill
    c2.font = low_font
    ws.cell(row=legend_row + 3, column=1, value="No highlight = high confidence (explicitly stated)")

    # Auto-width columns (capped at 30)
    for col_idx in range(1, 89):
        max_len = 0
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx, min_row=1, max_row=min(ws.max_row, 5)):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 30)

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
