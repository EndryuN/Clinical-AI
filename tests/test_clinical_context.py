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
    assert get_context_for_group("Watch and Wait") == ""
    assert get_context_for_group("nonexistent") == ""


def test_all_mri_groups_have_trg_context():
    """Both MRI follow-up groups need TRG definitions."""
    for group in ("Second MRI", "12-Week MRI"):
        ctx = get_context_for_group(group)
        assert "TRG" in ctx, f"No TRG context for {group}"
