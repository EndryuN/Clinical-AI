from config import get_groups

PROMPT_TEMPLATE = """You are a clinical data extraction assistant. Extract the following fields from the patient's MDT notes below.

For each field, provide:
- "value": the extracted value, or null if not mentioned in the text
- "confidence": "high" if explicitly stated in the text, "medium" if inferred from context, "low" if uncertain or ambiguous

Return ONLY valid JSON in this exact format:
{{
{json_example}
}}

Fields to extract:
{field_list}

Patient MDT Notes:
---
{patient_text}
---"""

def build_prompt(patient_text: str, group: dict) -> str:
    field_list = "\n".join(
        f"- {f['key']}: {f['prompt_hint']}" for f in group['fields']
    )
    json_example = ",\n".join(
        f'  "{f["key"]}": {{"value": "...", "confidence": "high|medium|low"}}'
        for f in group['fields']
    )
    return PROMPT_TEMPLATE.format(
        field_list=field_list,
        json_example=json_example,
        patient_text=patient_text
    )

def build_all_prompts(patient_text: str) -> list[tuple[dict, str]]:
    return [(group, build_prompt(patient_text, group)) for group in get_groups()]
