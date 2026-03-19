from openpyxl import Workbook
from config import get_all_fields

def write_excel(patients: list, output_path: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "Prototype V1"

    all_fields = get_all_fields()

    # Header row
    for field in all_fields:
        col = field['excel_column']
        ws.cell(row=1, column=col, value=field['excel_header'])

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
