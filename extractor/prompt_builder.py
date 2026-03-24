# extractor/prompt_builder.py
from config import get_groups
from extractor.clinical_context import get_context_for_group, ABBREVIATIONS

_SYSTEM_TEMPLATE = """You are a clinical data extraction assistant specialising in NHS MDT (Multidisciplinary Team Meeting) outcome proformas for colorectal cancer patients.

The document uses annotation markers: (a)=DOB, (b)=Name, (c)=NHS Number, (d)=Hospital Number, (e)=Gender, (f)=Clinical Details/Endoscopy, (g)=Staging & Diagnosis/Histology, (h)=MDT Outcome/Imaging, (i)=MDT date.

{abbreviations}

IMPORTANT RULES:
- If a date or value is not mentioned in the text, return null as the value.
- Dates should be in DD/MM/YYYY format.
- For the "1st MDT: Treatment approach" field, extract the FULL text after "Outcome:" in the MDT Outcome section — this includes the complete management plan, not just a category name.
- The "MDT Meeting Date" line at the top of the notes is the 1st MDT date.
- CT and MRI staging data is usually found in the "MDT Outcome(h)" section, not in a separate imaging report.
- Look for TNM staging patterns like T2N0M0 or T3dN2M1 — split these into separate T, N, M values.
- Endoscopy findings are in the "Clinical Details(f)" section, often after "Colonoscopy:" or "Flexi sig:".
- Histology/biopsy results are in the "Staging & Diagnosis(g)" section under "Diagnosis:".
- MMR status may appear in the MDT Outcome section (e.g., "MMR proficient" or "MMR deficient").
- EMVI status may be written as "EMVI +ve"/"EMVI -ve" or "EMVI positive"/"EMVI negative".
- For each field, return "source_section": the annotation marker where you found the value — one of (a), (b), (c), (d), (e), (f), (g), (h), (i) — or null if not found.

For each field, provide:
- "value": the extracted value, or null if not mentioned in the text
- "confidence": one of "high", "medium", or "low"
- "reason": a brief explanation (1 sentence) of WHY you assigned this confidence level.{context_reason_rule}
- "source_section": annotation marker where the value was found, e.g. "(h)", or null

Confidence levels:
- "high": the value is explicitly and clearly stated in the text
- "medium": the value is inferred from context or partially stated
- "low": the value is ambiguous, unclear, or you are guessing

{context_section}Return ONLY valid JSON in this exact format:
{{
{json_example}
}}"""

_CONTEXT_REASON_RULE = """ If you used the Clinical Reference below to classify or interpret a value, start your reason with "[REF]" and cite the specific definition used. If you did NOT use the reference, do not mention it."""


def build_prompt(patient_text: str, group: dict) -> tuple[str, str]:
    """Build system and user prompts for a specific schema group.
    Returns (system_prompt, user_prompt).
    """
    field_list = "\n".join(
        f"- {f['key']}: {f['prompt_hint']}" for f in group['fields']
    )
    json_example = ",\n".join(
        f'  "{f["key"]}": {{"value": "...", "confidence": "high|medium|low", "reason": "...", "source_section": "(a)-(i) or null"}}'
        for f in group['fields']
    )

    context = get_context_for_group(group['name'])
    context_section = ""
    context_reason_rule = ""
    if context:
        context_section = f"## Clinical Reference\n{context}\n\n"
        context_reason_rule = _CONTEXT_REASON_RULE

    system_prompt = _SYSTEM_TEMPLATE.format(
        abbreviations=ABBREVIATIONS,
        context_section=context_section,
        context_reason_rule=context_reason_rule,
        json_example=json_example,
    )
    user_prompt = (
        f"Fields to extract:\n{field_list}\n\n"
        f"Patient MDT Notes:\n---\n{patient_text}\n---"
    )
    return system_prompt, user_prompt


def build_all_prompts(patient_text: str) -> list[tuple[dict, str, str]]:
    """Build system+user prompts for all schema groups.
    Returns list of (group, system_prompt, user_prompt).
    """
    return [
        (group, *build_prompt(patient_text, group))
        for group in get_groups()
    ]
