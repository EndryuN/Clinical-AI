import pytest
from extractor.coverage import compute_coverage, _merge_spans
from models import PatientBlock, FieldResult


def test_merge_spans_combines_overlapping():
    spans = [
        {"start": 0, "end": 10, "used": True, "type": "verbatim"},
        {"start": 5, "end": 15, "used": True, "type": "verbatim"},
        {"start": 20, "end": 30, "used": False, "type": "unused"},
    ]
    merged = _merge_spans(spans)
    assert len(merged) == 3
    assert merged[0]["start"] == 0
    assert merged[0]["end"] == 15
    assert merged[0]["used"] == True
    assert merged[1]["start"] == 15  # gap filled
    assert merged[1]["end"] == 20
    assert merged[1]["used"] == False
    assert merged[2]["start"] == 20
    assert merged[2]["end"] == 30


def test_compute_coverage_basic():
    patient = PatientBlock(id="test")
    patient.raw_cells = [
        {"row": 4, "col": 0, "text": "Clinical details header"},
        {"row": 5, "col": 0, "text": "Patient has T3 tumour at 5cm."},
        {"row": 6, "col": 0, "text": "MDT outcome header"},
        {"row": 7, "col": 0, "text": "Recommend surgery."},
    ]
    patient.extractions = {
        "ClinicalDetails": {
            "tumour_stage": FieldResult(
                value="T3", confidence_basis="freeform_verbatim",
                source_snippet="T3", source_cell={"row": 5, "col": 0}
            ),
        }
    }

    compute_coverage(patient)

    assert patient.coverage_map is not None
    assert "5,0" in patient.coverage_map
    assert patient.coverage_pct is not None
    assert patient.coverage_pct > 0
    assert patient.coverage_pct < 100
    # Should have coverage_stats
    assert patient.coverage_stats is not None
    assert patient.coverage_stats["verbatim_pct"] > 0
    assert patient.coverage_stats["unused_pct"] > 0


def test_coverage_pct_none_when_no_freeform_text():
    patient = PatientBlock(id="test")
    patient.raw_cells = [
        {"row": 0, "col": 0, "text": "Header only"},
        {"row": 1, "col": 0, "text": "Structured data"},
    ]
    patient.extractions = {}

    compute_coverage(patient)
    assert patient.coverage_pct is None


def test_coverage_pct_zero_when_nothing_used():
    patient = PatientBlock(id="test")
    patient.raw_cells = [
        {"row": 5, "col": 0, "text": "Some text here"},
    ]
    patient.extractions = {}

    compute_coverage(patient)
    assert patient.coverage_pct == 0.0
    assert patient.coverage_stats["unused_pct"] == 100.0
    assert patient.coverage_stats["inferred_fields"] == 0


def test_coverage_tracks_inferred_fields():
    patient = PatientBlock(id="test")
    patient.raw_cells = [
        {"row": 5, "col": 0, "text": "Some clinical text here"},
    ]
    patient.extractions = {
        "Clinical": {
            "field1": FieldResult(
                value="inferred value", confidence_basis="freeform_inferred",
            ),
        }
    }

    compute_coverage(patient)
    assert patient.coverage_stats["inferred_fields"] == 1
