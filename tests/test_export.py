import os
import tempfile
from openpyxl import load_workbook
from models import PatientBlock, FieldResult
from export.excel_writer import write_excel

def test_excel_round_trip():
    patient = PatientBlock(
        id="patient_001",
        initials="AO",
        nhs_number="9990000001",
        raw_text="test",
        extractions={
            "Demographics": {
                "dob": FieldResult(value="26/05/1970", confidence="high"),
                "initials": FieldResult(value="AO", confidence="high"),
                "mrn": FieldResult(value="9990001", confidence="high"),
                "nhs_number": FieldResult(value="9990000001", confidence="high"),
                "gender": FieldResult(value="Male", confidence="high"),
                "previous_cancer": FieldResult(value="No", confidence="medium"),
                "previous_cancer_site": FieldResult(value="N/A", confidence="low"),
            }
        }
    )

    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        output_path = f.name

    try:
        write_excel([patient], output_path)
        wb = load_workbook(output_path)
        ws = wb.active
        assert ws.title == "Prototype V1"
        assert ws.cell(row=1, column=1).value is not None
        assert ws.cell(row=2, column=2).value == "AO"
        assert ws.cell(row=2, column=5).value == "Male"
        wb.close()
    finally:
        os.unlink(output_path)
