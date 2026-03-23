# tests/test_prompt_builder.py
from extractor.prompt_builder import build_prompt


def _demo_group(name="Histology"):
    return {
        'name': name,
        'fields': [
            {'key': 'mmr_status', 'prompt_hint': 'MMR status: Proficient or Deficient', 'type': 'string'},
        ]
    }


def test_build_prompt_returns_tuple():
    result = build_prompt("patient text", _demo_group())
    assert isinstance(result, tuple) and len(result) == 2


def test_system_prompt_contains_role():
    system, user = build_prompt("patient text", _demo_group())
    assert "clinical data extraction" in system.lower()


def test_system_prompt_contains_annotation_markers():
    system, user = build_prompt("patient text", _demo_group())
    assert "(f)" in system and "(g)" in system and "(h)" in system


def test_system_prompt_contains_json_format_with_source_section():
    system, user = build_prompt("patient text", _demo_group())
    assert "source_section" in system


def test_system_prompt_contains_g049_context_for_histology():
    system, user = build_prompt("patient text", _demo_group("Histology"))
    assert "MMR" in system


def test_system_prompt_no_g049_context_for_demographics():
    system, user = build_prompt("patient text", _demo_group("Demographics"))
    assert "G049" not in system and "Clinical Reference" not in system


def test_system_prompt_json_fence_uses_single_braces():
    system, user = build_prompt("patient text", _demo_group())
    assert "{\n" in system and "\n}" in system


def test_user_prompt_safe_with_curly_braces_in_patient_text():
    # Patient notes can contain curly braces (e.g. lab values) — must not crash
    system, user = build_prompt("CEA {1.2} ng/mL", _demo_group())
    assert "CEA {1.2} ng/mL" in user


def test_user_prompt_contains_patient_text():
    system, user = build_prompt("patient notes here", _demo_group())
    assert "patient notes here" in user


def test_user_prompt_contains_field_key():
    system, user = build_prompt("text", _demo_group())
    assert "mmr_status" in user


def test_system_prompt_does_not_contain_patient_text():
    system, user = build_prompt("secret patient data", _demo_group())
    assert "secret patient data" not in system
