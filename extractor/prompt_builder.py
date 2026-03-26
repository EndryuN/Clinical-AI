# extractor/prompt_builder.py
"""
Builds LLM prompts from per-group template files in config/prompts/.

Prompt structure (optimised for 8B models):
1. Base system instructions (short, from system_base.txt)
2. Group-specific instructions + clinical reference + few-shot example (from {group}.txt)
3. Field list with allowed values from overrides
4. ONLY the relevant section of patient text (not the full document)
"""
import os
import re
from config import get_groups, get_field_override
from extractor.clinical_context import get_context_for_group, ABBREVIATIONS

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'prompts')

# Cache loaded prompt files
_prompt_cache: dict[str, str] = {}


def _load_prompt_file(name: str) -> str:
    """Load a prompt template from config/prompts/. Cached."""
    if name not in _prompt_cache:
        path = os.path.join(_PROMPTS_DIR, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                _prompt_cache[name] = f.read().strip()
        except FileNotFoundError:
            _prompt_cache[name] = ''
    return _prompt_cache[name]


def _clear_prompt_cache():
    """Clear cache (for testing or after editing prompt files)."""
    _prompt_cache.clear()


# Section markers → which text sections to include
_GROUP_SECTIONS = {
    'Endoscopy':        ['(f)'],
    'Baseline CT':      ['(h)'],
    'Surgery':          ['(h)'],
    'Watch and Wait':   ['(h)', '(f)'],
    'Histology':        ['(g)', '(h)'],
    'Baseline MRI':     ['(h)'],
    'Second MRI':       ['(h)'],
    '12-Week MRI':      ['(h)'],
    'MDT':              ['(h)', '(i)'],
    'Chemotherapy':     ['(h)'],
    'Immunotherapy':    ['(h)'],
    'Radiotherapy':     ['(h)'],
    'CEA and Clinical': ['(f)', '(h)'],
    'Follow-up Flex Sig': ['(f)', '(h)'],
    'Watch and Wait Dates': ['(f)', '(h)'],
}

# Map section markers to document section headers
_SECTION_HEADERS = {
    '(f)': r'Clinical Details\(f\)',
    '(g)': r'Staging & Diagnosis\(g\)',
    '(h)': r'MDT Outcome\(h\)',
    '(i)': r'MDT Meeting Date',
}


def _extract_relevant_text(patient_text: str, group_name: str) -> str:
    """Extract only the relevant sections of patient text for this group.

    Falls back to full text if section extraction fails.
    """
    sections_needed = _GROUP_SECTIONS.get(group_name)
    if not sections_needed:
        return patient_text

    extracted_parts = []

    # Always include the header (Cancer Type + MDT date)
    header_match = re.match(r'(Cancer Type:.*?\n(?:MDT Meeting Date:.*?\n)?)', patient_text)
    if header_match:
        extracted_parts.append(header_match.group(1).strip())

    for marker in sections_needed:
        header_pattern = _SECTION_HEADERS.get(marker)
        if not header_pattern:
            continue
        # Find section: from header to next section or end
        pattern = rf'({header_pattern}.*?)(?=\n(?:Patient Details|Staging & Diagnosis|Clinical Details|MDT Outcome|Cancer Target)|$)'
        m = re.search(pattern, patient_text, re.DOTALL | re.IGNORECASE)
        if m:
            extracted_parts.append(m.group(1).strip())

    if not extracted_parts:
        return patient_text  # fallback

    return '\n\n'.join(extracted_parts)


def build_prompt(patient_text: str, group: dict) -> tuple[str, str]:
    """Build system and user prompts for a specific schema group.

    Uses per-group prompt files from config/prompts/ if available,
    falls back to generic template otherwise.
    """
    group_name = group['name']

    # Build field list with allowed values from overrides
    field_lines = []
    for f in group['fields']:
        override = get_field_override(f['key'])
        allowed = override.get('allowed_values', [])
        hint = f['prompt_hint']
        if allowed:
            hint += f" MUST be one of: {', '.join(allowed)}, or null."
        field_lines.append(f"- {f['key']}: {hint}")
    field_list = '\n'.join(field_lines)

    # JSON format example
    json_fields = ',\n'.join(
        f'  "{f["key"]}": {{"value": "...", "reason": "...", "source_section": "(f)|(g)|(h)|null"}}'
        for f in group['fields']
    )

    # Load base system prompt
    base = _load_prompt_file('system_base.txt')

    # Load group-specific prompt (instructions + reference + example)
    group_file = group_name.lower().replace(' ', '_').replace('&', 'and') + '.txt'
    group_prompt = _load_prompt_file(group_file)

    # If no group-specific file, use clinical context as fallback
    if not group_prompt:
        context = get_context_for_group(group_name)
        if context:
            group_prompt = f"Clinical Reference:\n{context}"

    # Assemble system prompt (concise for 8B models)
    system_parts = [base]
    if group_prompt:
        system_parts.append(group_prompt)
    system_parts.append(f"Return JSON in this exact format:\n{{\n{json_fields}\n}}")
    system_prompt = '\n\n'.join(system_parts)

    # Extract only relevant text sections
    relevant_text = _extract_relevant_text(patient_text, group_name)

    user_prompt = f"Fields to extract:\n{field_list}\n\nPatient notes:\n---\n{relevant_text}\n---"

    return system_prompt, user_prompt


def build_all_prompts(patient_text: str) -> list[tuple[dict, str, str]]:
    """Build system+user prompts for all schema groups."""
    return [
        (group, *build_prompt(patient_text, group))
        for group in get_groups()
    ]
