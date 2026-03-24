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


def test_field_result_default_confidence_basis_is_absent():
    fr = FieldResult()
    assert fr.confidence_basis == "absent"


def test_field_result_confidence_property_maps_all_bases():
    assert FieldResult(confidence_basis="structured_verbatim").confidence == "high"
    assert FieldResult(confidence_basis="freeform_verbatim").confidence == "medium"
    assert FieldResult(confidence_basis="freeform_inferred").confidence == "low"
    assert FieldResult(confidence_basis="edited").confidence == "medium"
    assert FieldResult(confidence_basis="absent").confidence == "none"


def test_patient_block_has_unique_id_and_coverage_fields():
    p = PatientBlock(id="x")
    assert p.unique_id == ""
    assert p.gender == ""
    assert p.mdt_date == ""
    assert p.coverage_map == {}
    assert p.coverage_pct is None
