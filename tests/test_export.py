import os
import tempfile
from openpyxl import load_workbook
from models import PatientBlock, FieldResult
from export.excel_writer import write_excel


def test_excel_exports_metadata_sheet():
    patient = PatientBlock(
        id="p001", initials="AO", nhs_number="9990000001", raw_text="test",
        extractions={
            "Demographics": {
                "dob": FieldResult(value="26/05/1970", confidence="high", reason="regex match"),
                "initials": FieldResult(value="AO", confidence="high", reason=""),
                "mrn": FieldResult(value="9990001", confidence="high", reason=""),
                "nhs_number": FieldResult(value="9990000001", confidence="medium", reason="LLM inferred"),
                "gender": FieldResult(value="Male", confidence="high", reason=""),
                "previous_cancer": FieldResult(value=None, confidence="none", reason=""),
                "previous_cancer_site": FieldResult(value=None, confidence="none", reason=""),
            }
        }
    )
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        path = f.name
    try:
        write_excel([patient], path)
        wb = load_workbook(path)
        assert "Metadata" in wb.sheetnames
        ws = wb["Metadata"]
        # Header row
        assert ws.cell(1, 1).value == "patient_id"
        # Find nhs_number row and check confidence
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        nhs_row = next((r for r in rows if r[1] == "nhs_number"), None)
        assert nhs_row is not None
        assert nhs_row[2] == "medium"
        assert "LLM inferred" in (nhs_row[3] or "")
        wb.close()
    finally:
        os.unlink(path)


def test_excel_round_trip_restores_confidence_and_reason():
    """Export then re-import — confidence and reason must survive."""
    import sys
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from app import _import_excel  # noqa: import after path setup
    patient = PatientBlock(
        id="p001", initials="AO", nhs_number="9990000001", raw_text="test",
        extractions={
            "Demographics": {
                "dob": FieldResult(value="26/05/1970", confidence="high", reason="regex"),
                "initials": FieldResult(value="AO", confidence="high", reason=""),
                "mrn": FieldResult(value="9990001", confidence="high", reason=""),
                "nhs_number": FieldResult(value="9990000001", confidence="medium", reason="LLM"),
                "gender": FieldResult(value="Male", confidence="high", reason=""),
                "previous_cancer": FieldResult(value=None, confidence="none", reason=""),
                "previous_cancer_site": FieldResult(value=None, confidence="none", reason=""),
            }
        }
    )
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        path = f.name
    try:
        write_excel([patient], path)
        reimported = _import_excel(path)
        demo = reimported[0].extractions.get("Demographics", {})
        assert demo["nhs_number"].confidence == "medium"
        assert "LLM" in (demo["nhs_number"].reason or "")
        assert demo["dob"].confidence == "high"
    finally:
        os.unlink(path)


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
