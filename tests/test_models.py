from models import PatientBlock, FieldResult, ExtractionSession


def test_patient_block_has_raw_cells():
    p = PatientBlock(id="x")
    assert p.raw_cells == []


def test_field_result_has_provenance_fields():
    fr = FieldResult()
    assert fr.source_cell is None
    assert fr.source_snippet is None


def test_extraction_session_progress_has_phase_fields():
    s = ExtractionSession()
    assert s.progress['phase'] == 'idle'
    assert s.progress['regex_complete'] == 0
    assert s.progress['llm_queue_size'] == 0
    assert s.progress['llm_complete'] == 0
