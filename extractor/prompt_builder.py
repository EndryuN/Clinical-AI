from config import get_groups

PROMPT_TEMPLATE = """You are a clinical data extraction assistant specialising in NHS MDT (Multidisciplinary Team Meeting) outcome proformas for colorectal cancer patients.

The document uses annotation markers: (a)=DOB, (b)=Name, (c)=NHS Number, (d)=Hospital Number, (e)=Gender, (f)=Clinical Details/Endoscopy, (g)=Staging & Diagnosis/Histology, (h)=MDT Outcome/Imaging, (i)=MDT date.

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

For each field, provide:
- "value": the extracted value, or null if not mentioned in the text
- "confidence": one of "high", "medium", or "low"
- "reason": a brief explanation (1 sentence) of WHY you assigned this confidence level

Confidence levels:
- "high": the value is explicitly and clearly stated in the text (e.g., "DOB: 26/05/1970", "Male", "NHS Number: 9990000001")
- "medium": the value is inferred from context or partially stated (e.g., staging derived from a TNM string, treatment approach summarised from discussion notes)
- "low": the value is ambiguous, unclear, or you are guessing based on limited information

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
    """Build an extraction prompt for a specific schema group."""
    field_list = "\n".join(
        f"- {f['key']}: {f['prompt_hint']}" for f in group['fields']
    )
    json_example = ",\n".join(
        f'  "{f["key"]}": {{"value": "...", "confidence": "high|medium|low", "reason": "..."}}'
        for f in group['fields']
    )
    return PROMPT_TEMPLATE.format(
        field_list=field_list,
        json_example=json_example,
        patient_text=patient_text
    )


def build_all_prompts(patient_text: str) -> list[tuple[dict, str]]:
    """Build prompts for all schema groups."""
    return [(group, build_prompt(patient_text, group)) for group in get_groups()]
