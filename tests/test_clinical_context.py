# tests/test_clinical_context.py
from extractor.clinical_context import get_context_for_group


def test_histology_context_contains_mmr():
    ctx = get_context_for_group("Histology")
    assert "MMR" in ctx
    assert "proficient" in ctx.lower() or "pMMR" in ctx
    assert "deficient" in ctx.lower() or "dMMR" in ctx


def test_baseline_ct_context_contains_tnm():
    ctx = get_context_for_group("Baseline CT")
    assert "T3" in ctx
    assert "N2" in ctx
    assert "M1" in ctx


def test_baseline_mri_context_contains_crm_and_emvi():
    ctx = get_context_for_group("Baseline MRI")
    assert "CRM" in ctx
    assert "1mm" in ctx
    assert "EMVI" in ctx


def test_second_mri_context_contains_trg():
    ctx = get_context_for_group("Second MRI")
    assert "TRG" in ctx
    assert "TRG 0" in ctx or "TRG0" in ctx


def test_unknown_group_returns_empty():
    assert get_context_for_group("Demographics") == ""
    assert get_context_for_group("nonexistent") == ""


def test_all_mri_groups_have_trg_context():
    """Both MRI follow-up groups need TRG definitions."""
    for group in ("Second MRI", "12-Week MRI"):
        ctx = get_context_for_group(group)
        assert "TRG" in ctx, f"No TRG context for {group}"


def test_endoscopy_context_has_type_classification():
    ctx = get_context_for_group("Endoscopy")
    assert "Colonoscopy complete" in ctx
    assert "Incomplete" in ctx
    assert "Flexi sig" in ctx


def test_surgery_context_has_intent():
    ctx = get_context_for_group("Surgery")
    assert "Curative" in ctx
    assert "Palliative" in ctx
    assert "APR" in ctx


def test_watch_wait_context_has_reasons():
    ctx = get_context_for_group("Watch and Wait")
    assert "complete clinical response" in ctx.lower() or "cCR" in ctx
    assert "W&W" in ctx


def test_mri_uses_radiological_not_pathological_staging():
    """MRI context should use mrT (radiological) not pT (pathological)."""
    ctx = get_context_for_group("Baseline MRI")
    assert "mrT" in ctx or "MRI" in ctx
    # Should NOT have pT prefix for radiological groups
    assert "pT1:" not in ctx
