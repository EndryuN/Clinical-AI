"""
Regex-based field extraction — handles ~90% of fields without LLM.

Extracts structured data directly from patient raw text using pattern matching
and rule-based logic. Only fields that require contextual interpretation
(endoscopy type, M staging inference, surgery intent, W&W reasoning) are
left for the LLM.
"""

import re
from models import FieldResult


def regex_extract(raw_text: str, group_name: str, fields: list[dict]) -> dict[str, FieldResult]:
    """Extract fields from raw text using regex. Returns dict of field_key -> FieldResult.

    Fields that can't be extracted by regex are returned with value=None, confidence='none'.
    """
    extractors = {
        "Demographics": _extract_demographics,
        "Endoscopy": _extract_endoscopy,
        "Histology": _extract_histology,
        "Baseline MRI": _extract_baseline_mri,
        "Baseline CT": _extract_baseline_ct,
        "MDT": _extract_mdt,
        "Chemotherapy": _extract_chemotherapy,
        "Immunotherapy": _extract_immunotherapy,
        "Radiotherapy": _extract_radiotherapy,
        "CEA and Clinical": _extract_cea,
        "Surgery": _extract_surgery,
        "Second MRI": _extract_second_mri,
        "12-Week MRI": _extract_12week_mri,
        "Follow-up Flex Sig": _extract_flexsig,
        "Watch and Wait": _extract_watch_wait,
        "Watch and Wait Dates": _extract_ww_dates,
    }

    extractor = extractors.get(group_name)
    if not extractor:
        return {f['key']: FieldResult(value=None, confidence='none') for f in fields}

    extracted = extractor(raw_text)

    # Build results, filling in missing keys
    results = {}
    for f in fields:
        key = f['key']
        if key in extracted and extracted[key] is not None:
            results[key] = FieldResult(
                value=extracted[key],
                confidence='high',
                reason='Extracted verbatim from document text'
            )
        else:
            results[key] = FieldResult(value=None, confidence='none', reason='')
    return results


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _find_section(text: str, header: str) -> str:
    """Extract text under a section header until the next section."""
    pattern = re.compile(rf'{header}.*?\n(.*?)(?=\n(?:Staging|Clinical Details|MDT Outcome|Patient Details|Cancer Target)|$)',
                         re.DOTALL | re.IGNORECASE)
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _find_dates(text: str) -> list[str]:
    """Find all dates in text (DD/MM/YYYY or D/M/YY)."""
    # Full format
    dates = re.findall(r'\d{1,2}/\d{1,2}/\d{4}', text)
    # Short format D/M/YY — convert to DD/MM/YYYY
    short = re.findall(r'\b(\d{1,2})/(\d{1,2})/(\d{2})\b', text)
    for d, m, y in short:
        full_date = f"{d}/{m}/20{y}"
        if full_date not in dates:
            dates.append(full_date)
    return dates


def _normalize_date(date_str: str) -> str:
    """Normalize D/M/YY to DD/MM/YYYY."""
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2})$', date_str)
    if m:
        return f"{m.group(1)}/{m.group(2)}/20{m.group(3)}"
    return date_str


def _find_tnm(text: str) -> dict:
    """Extract T, N, M staging from text. Handles both combined (T3bN1M0) and separate patterns."""
    result = {}

    # Combined TNM pattern: T3bN1M0 or T3b N1 M0
    combined = re.search(r'\b(T\d[a-d]?)\s*(N\d[a-c]?)\s*(M\d)', text)
    if combined:
        result['t'] = combined.group(1)
        result['n'] = combined.group(2)
        result['m'] = combined.group(3)
        return result

    # Individual patterns
    t = re.search(r'\b(T\d[a-d]?)\b', text)
    n = re.search(r'\b(N\d[a-c]?)\b', text)
    m = re.search(r'\b(M\d)\b', text)
    if t: result['t'] = t.group(1)
    if n: result['n'] = n.group(1)
    if m: result['m'] = m.group(1)
    return result


def _find_emvi(text: str) -> str | None:
    """Extract EMVI status."""
    m = re.search(r'EMVI\s*[\-:]?\s*(\+ve|positive|negative|\-ve|yes|no)', text, re.IGNORECASE)
    if m:
        val = m.group(1).lower()
        if val in ('+ve', 'positive', 'yes'):
            return 'Positive'
        return 'Negative'
    return None


def _find_crm(text: str) -> str | None:
    """Extract CRM status."""
    m = re.search(r'CRM\s*[\-:]?\s*(clear|involved|threatened|unsafe|positive|negative|\+ve|\-ve)',
                  text, re.IGNORECASE)
    if m:
        val = m.group(1).lower()
        if val in ('involved', 'threatened', 'unsafe', 'positive', '+ve'):
            return m.group(1).capitalize()
        return 'Clear'
    # Also check for "CRM 3mm" type patterns
    m2 = re.search(r'CRM\s*[\-:]?\s*(\d+)\s*mm', text, re.IGNORECASE)
    if m2:
        return f"{m2.group(1)}mm"
    return None


def _find_psw(text: str) -> str | None:
    """Extract peritoneal sidewall status."""
    m = re.search(r'(?:PSW|pelvic\s*side\s*wall?|peritoneal)\s*[\-:]?\s*(positive|negative|\+ve|\-ve|clear|involved)',
                  text, re.IGNORECASE)
    if m:
        val = m.group(1).lower()
        if val in ('positive', '+ve', 'involved'):
            return 'Positive'
        return 'Negative'
    return None


# ---------------------------------------------------------------------------
# Per-group extractors
# ---------------------------------------------------------------------------

def _extract_demographics(text: str) -> dict:
    result = {}

    # DOB - marked with (a)
    m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s*\(a\)', text)
    if not m:
        m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s*(?:Age|$)', text)
    if m:
        result['dob'] = m.group(1)

    # Initials - from name marked with (b) or the all-caps name
    name_match = re.search(r'([A-Z][A-Za-z\'\-]+(?:\s+[A-Za-z\'\-]+)+)\s*\(b\)', text)
    if not name_match:
        # Try all-caps name line
        for line in text.split('\n'):
            cleaned = re.sub(r'\([a-z]\)', '', line).strip()
            if cleaned and len(cleaned) > 3 and ' ' in cleaned:
                if cleaned.replace(' ', '').replace("'", '').replace('-', '').isupper():
                    name_match = type('', (), {'group': lambda self, x: cleaned})()
                    break
    if name_match:
        name = re.sub(r'\([a-z]\)', '', name_match.group(1)).strip()
        parts = re.split(r"[\s'\-]+", name)
        result['initials'] = ''.join(p[0].upper() for p in parts if p)

    # MRN - marked with (d)
    m = re.search(r'Hospital\s*Number:\s*(\d+)', text, re.IGNORECASE)
    if m:
        result['mrn'] = m.group(1)

    # NHS number - marked with (c)
    m = re.search(r'NHS\s*Number:\s*([\d\s\(\)c]+)', text, re.IGNORECASE)
    if m:
        result['nhs_number'] = re.sub(r'[^\d]', '', m.group(1))

    # Gender - marked with (e)
    m = re.search(r'(Male|Female)\s*\(?e?\)?', text, re.IGNORECASE)
    if m:
        result['gender'] = m.group(1).capitalize()

    # Previous cancer - look for mentions
    if re.search(r'previous\s*cancer|prior\s*(?:malignan|cancer|lymphoma|leukaemia)|previous\s*(?:malignan|cancer)|known\s*prior|history\s*of\s*(?:cancer|lymphoma|carcinoma|melanoma)', text, re.IGNORECASE):
        result['previous_cancer'] = 'Yes'
        # Try to extract the site/type
        site_match = re.search(r'(?:previous|prior|known\s*prior)\s*(\w+(?:\s+\w+)?)\s*(?:cancer|malignan|,|\.|\n)', text, re.IGNORECASE)
        if not site_match:
            site_match = re.search(r'(?:history\s*of|known)\s*(?:prior\s*)?(\w+(?:\s+\w+)?)', text, re.IGNORECASE)
        if site_match:
            site = site_match.group(1).strip()
            if site.lower() not in ('cancer', 'malignancy', 'prior'):
                result['previous_cancer_site'] = site.title()

    return result


def _extract_endoscopy(text: str) -> dict:
    result = {}
    clinical = _find_section(text, r'Clinical Details')

    # Endoscopy date
    m = re.search(r'(?:Colonoscopy|Flexi\s*sig(?:moidoscopy)?|Endoscopy)\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})',
                  text, re.IGNORECASE)
    if m:
        result['endoscopy_date'] = m.group(1)

    # Endoscopy findings - grab everything after "Colonoscopy:" or "Flexi sig:"
    # Check Clinical Details first, then MDT Outcome
    for section in [clinical, text]:
        if not section:
            continue
        m = re.search(r'(?:Colonoscopy|Flexi\s*sig(?:moidoscopy)?)\s*(?:on\s*\d{1,2}/\d{1,2}/\d{2,4})?\s*[:\-–—]\s*(.+?)(?=\n\n|\nDiscuss|\nOutcome|\nMDT|Histo|$)',
                      section, re.DOTALL | re.IGNORECASE)
        if m:
            findings = m.group(1).strip()
            if len(findings) > 10:  # skip very short matches
                result['endoscopy_findings'] = findings
                break

    # Endoscopy type is often inferred — leave for LLM
    # But we can detect explicit mentions
    if re.search(r'flexi\s*sig', text, re.IGNORECASE):
        result['endoscopy_type'] = 'Flexi sig'
    elif re.search(r'incomplete\s*colonoscopy', text, re.IGNORECASE):
        result['endoscopy_type'] = 'Incomplete colonoscopy'
    # "Colonoscopy complete" requires inference — skip

    return result


def _extract_histology(text: str) -> dict:
    result = {}

    # Biopsy result from Diagnosis line
    m = re.search(r'Diagnosis:\s*([A-Z][A-Z\s\-,]+?)(?:\s*\n|ICD)', text)
    if m:
        diag = m.group(1).strip().rstrip(',')
        if diag and not diag.upper().startswith('ICD'):
            result['biopsy_result'] = diag.title()

    # Also check in MDT Outcome for "Histo:" mentions
    if 'biopsy_result' not in result:
        m = re.search(r'Histo?(?:logy)?:\s*([A-Za-z\s]+?)(?:\.|,|\n)', text, re.IGNORECASE)
        if m:
            result['biopsy_result'] = m.group(1).strip().title()

    # Biopsy date
    m = re.search(r'biops(?:y|ied)\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
    if m:
        result['biopsy_date'] = m.group(1)

    # MMR status
    m = re.search(r'MMR\s*[\-:]?\s*(proficient|deficient|intact|loss|dMMR|pMMR)', text, re.IGNORECASE)
    if m:
        val = m.group(1).lower()
        if val in ('proficient', 'intact', 'pmmr'):
            result['mmr_status'] = 'Proficient'
        else:
            result['mmr_status'] = 'Deficient'

    return result


def _extract_baseline_mri(text: str) -> dict:
    result = {}

    # Find MRI date and content — handle both DD/MM/YYYY and D/M/YY
    m = re.search(r'MRI\s*(?:pelvis\s*)?(?:on\s*)?(\d{1,2}/\d{1,2}/\d{2,4})\s*[:\-–—]?\s*(.*?)(?=\n\n|CT\s+\d|Colonoscopy|Outcome|$)',
                  text, re.DOTALL | re.IGNORECASE)
    if m:
        result['baseline_mri_date'] = _normalize_date(m.group(1))
        mri_text = m.group(2)

        tnm = _find_tnm(mri_text)
        if 't' in tnm: result['baseline_mri_t'] = tnm['t']
        if 'n' in tnm: result['baseline_mri_n'] = tnm['n']

        emvi = _find_emvi(mri_text)
        if emvi: result['baseline_mri_emvi'] = emvi

        crm = _find_crm(mri_text)
        if crm: result['baseline_mri_crm'] = crm

        psw = _find_psw(mri_text)
        if psw: result['baseline_mri_psw'] = psw

    # Also check Staging section for MRI values
    staging = _find_section(text, r'Staging')
    if staging and 'baseline_mri_t' not in result:
        tnm = _find_tnm(staging)
        if 't' in tnm: result['baseline_mri_t'] = tnm['t']
        if 'n' in tnm: result['baseline_mri_n'] = tnm['n']

    return result


def _extract_baseline_ct(text: str) -> dict:
    result = {}

    # Find CT date and content — handle both DD/MM/YYYY and D/M/YY
    m = re.search(r'CT\s*(?:TAP\s*)?(?:on\s*)?(\d{1,2}/\d{1,2}/\d{2,4})\s*[:\-–—]?\s*(.*?)(?=\n\n|MRI\s+\d|Colonoscopy|Outcome|Histo|$)',
                  text, re.DOTALL | re.IGNORECASE)
    if m:
        result['baseline_ct_date'] = _normalize_date(m.group(1))
        ct_text = m.group(2)

        tnm = _find_tnm(ct_text)
        if 't' in tnm: result['baseline_ct_t'] = tnm['t']
        if 'n' in tnm: result['baseline_ct_n'] = tnm['n']
        if 'm' in tnm: result['baseline_ct_m'] = tnm['m']

        emvi = _find_emvi(ct_text)
        if emvi: result['baseline_ct_emvi'] = emvi

        # Incidental findings — check for unexpected findings
        if re.search(r'incidental|unexpected|additionally|also\s+(?:noted|found)', ct_text, re.IGNORECASE):
            result['baseline_ct_incidental'] = 'Y'
        # M staging inference: "metastases" or "no metastases"
        if 'baseline_ct_m' not in result:
            if re.search(r'metastas[ei]s|metastatic', ct_text, re.IGNORECASE):
                if re.search(r'no\s+(?:distant\s+)?metastas|no\s+evidence\s+of\s+metastas', ct_text, re.IGNORECASE):
                    result['baseline_ct_m'] = 'M0'
                else:
                    result['baseline_ct_m'] = 'M1'

    # Also extract from combined TNM staging lines elsewhere
    staging_line = re.search(r'staging[:\s]*(T\d[a-d]?\s*N\d[a-c]?\s*M\d)', text, re.IGNORECASE)
    if staging_line:
        tnm = _find_tnm(staging_line.group(1))
        if 't' in tnm and 'baseline_ct_t' not in result: result['baseline_ct_t'] = tnm['t']
        if 'n' in tnm and 'baseline_ct_n' not in result: result['baseline_ct_n'] = tnm['n']
        if 'm' in tnm and 'baseline_ct_m' not in result: result['baseline_ct_m'] = tnm['m']

    # Incidental findings — also check full text
    if 'baseline_ct_incidental' not in result:
        if re.search(r'incidental|enlarged\s+(?:retro)?peritoneal\s+nodes|suspicious\s+lesion|indeterminate',
                     text, re.IGNORECASE):
            result['baseline_ct_incidental'] = 'Y'
            detail = re.search(r'((?:Mildly\s+)?enlarged[^.]+|suspicious[^.]+|indeterminate[^.]+)', text, re.IGNORECASE)
            if detail:
                result['baseline_ct_incidental_detail'] = detail.group(1).strip()
        elif 'baseline_ct_date' in result:
            # CT was done but no incidental findings mentioned
            result['baseline_ct_incidental'] = 'N'

    return result


def _extract_mdt(text: str) -> dict:
    result = {}

    # MDT meeting date — from the prepended header
    m = re.search(r'MDT Meeting Date:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    if m:
        result['first_mdt_date'] = m.group(1)

    # Treatment approach — full text after "Outcome:"
    m = re.search(r'Outcome:\s*(.+?)(?=\n\n|$)', text, re.DOTALL)
    if m:
        result['first_mdt_treatment'] = m.group(1).strip()

    # 6-week and 12-week MDT dates — look for "MDT DD/MM/YYYY" patterns after the first
    mdt_dates = re.findall(r'MDT\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
    # Skip the first MDT date (already captured)
    first_date = result.get('first_mdt_date', '')
    subsequent = [d for d in mdt_dates if d != first_date]
    if len(subsequent) >= 1:
        result['mdt_6week_date'] = subsequent[0]
    if len(subsequent) >= 2:
        result['mdt_12week_date'] = subsequent[1]

    return result


def _extract_chemotherapy(text: str) -> dict:
    result = {}

    # Look for chemo drug names
    drugs = re.findall(r'\b(capecitabine|oxaliplatin|FOLFOX|CAPOX|5-?FU|irinotecan|FOLFIRI|FOLFOXIRI)\b',
                       text, re.IGNORECASE)
    if drugs:
        result['chemo_drugs'] = ', '.join(set(d.upper() for d in drugs))

    # Chemo goals
    if re.search(r'palliative', text, re.IGNORECASE):
        result['chemo_goals'] = 'Palliative'
    elif re.search(r'curative|radical', text, re.IGNORECASE):
        result['chemo_goals'] = 'Curative'

    # Cycles
    m = re.search(r'(\d+)\s*(?:cycles?|courses?)\s*(?:of)?\s*(?:chemo|FOLFOX|CAPOX)?', text, re.IGNORECASE)
    if m:
        result['chemo_cycles'] = m.group(1)

    return result


def _extract_immunotherapy(text: str) -> dict:
    result = {}
    m = re.search(r'\b(pembrolizumab|nivolumab|ipilimumab|atezolizumab|dostarlimab)\b', text, re.IGNORECASE)
    if m:
        result['immuno_drug'] = m.group(1).capitalize()
    return result


def _extract_radiotherapy(text: str) -> dict:
    result = {}

    # Total dose
    m = re.search(r'(\d+(?:\.\d+)?)\s*Gy', text)
    if m:
        result['radio_total_dose'] = f"{m.group(1)}Gy"

    # Concomitant chemo
    m = re.search(r'concom(?:itant|mittant)\s*(?:chemo(?:therapy)?)?\s*[\-:]?\s*(\w+)?', text, re.IGNORECASE)
    if m and m.group(1):
        result['radio_concomitant_chemo'] = m.group(1).capitalize()
    elif re.search(r'chemoradio', text, re.IGNORECASE):
        result['radio_concomitant_chemo'] = 'Yes'

    return result


def _extract_cea(text: str) -> dict:
    result = {}

    # CEA value
    m = re.search(r'CEA\s*[\-:]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if m:
        result['cea_value'] = m.group(1)

    return result


def _extract_surgery(text: str) -> dict:
    result = {}

    # Surgery date
    m = re.search(r'(?:surgery|operation|resection|hemicolectomy|colectomy|APR)\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})',
                  text, re.IGNORECASE)
    if m:
        result['surgery_date'] = m.group(1)

    # Defunctioned/stoma
    if re.search(r'defunction|stoma\s*form', text, re.IGNORECASE):
        result['defunctioned'] = 'Yes'

    # Surgery intent is free-text — leave for LLM

    return result


def _extract_second_mri(text: str) -> dict:
    result = {}

    # Find second MRI — look for MRI mentions after the first one (handle D/M/YY too)
    mri_mentions = list(re.finditer(
        r'(?:repeat\s+|2nd\s+|second\s+)?MRI\s*(?:pelvis\s*)?(?:on\s*)?(\d{1,2}/\d{1,2}/\d{2,4})\s*[:\-–—]?\s*(.*?)(?=\n\n|CT\s+\d|Colonoscopy|Outcome|MDT|$)',
        text, re.DOTALL | re.IGNORECASE
    ))

    if len(mri_mentions) >= 2:
        m = mri_mentions[1]  # second MRI
        result['second_mri_date'] = _normalize_date(m.group(1))
        mri_text = m.group(2)

        tnm = _find_tnm(mri_text)
        if 't' in tnm: result['second_mri_t'] = tnm['t']
        if 'n' in tnm: result['second_mri_n'] = tnm['n']

        emvi = _find_emvi(mri_text)
        if emvi: result['second_mri_emvi'] = emvi

        crm = _find_crm(mri_text)
        if crm: result['second_mri_crm'] = crm

        psw = _find_psw(mri_text)
        if psw: result['second_mri_psw'] = psw

        # TRG score
        trg = re.search(r'TRG\s*[\-:]?\s*(\d)', mri_text, re.IGNORECASE)
        if trg: result['second_mri_trg'] = trg.group(1)

    return result


def _extract_12week_mri(text: str) -> dict:
    result = {}

    # Look for 12-week or third MRI
    mri_mentions = list(re.finditer(
        r'(?:12\s*week|third|3rd)\s*MRI\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})\s*:?\s*(.*?)(?=\n\n|$)',
        text, re.DOTALL | re.IGNORECASE
    ))

    if mri_mentions:
        m = mri_mentions[0]
        result['week12_mri_date'] = m.group(1)
        mri_text = m.group(2)

        tnm = _find_tnm(mri_text)
        if 't' in tnm: result['week12_mri_t'] = tnm['t']
        if 'n' in tnm: result['week12_mri_n'] = tnm['n']

        emvi = _find_emvi(mri_text)
        if emvi: result['week12_mri_emvi'] = emvi

        crm = _find_crm(mri_text)
        if crm: result['week12_mri_crm'] = crm

        psw = _find_psw(mri_text)
        if psw: result['week12_mri_psw'] = psw

        trg = re.search(r'TRG\s*[\-:]?\s*(\d)', mri_text, re.IGNORECASE)
        if trg: result['week12_mri_trg'] = trg.group(1)

    return result


def _extract_flexsig(text: str) -> dict:
    result = {}

    m = re.search(r'(?:flexi(?:ble)?\s*sig(?:moidoscopy)?|flex\s*sig)\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})\s*:?\s*(.*?)(?=\n\n|MDT|Outcome|$)',
                  text, re.DOTALL | re.IGNORECASE)
    if m:
        result['flexsig_date'] = m.group(1)
        findings = m.group(2).strip()
        if findings:
            result['flexsig_findings'] = findings

    return result


def _extract_watch_wait(text: str) -> dict:
    result = {}

    # Watch and wait entry
    m = re.search(r'watch\s*(?:and|&)\s*wait', text, re.IGNORECASE)
    if m:
        # Try to find the MDT date where W&W was decided
        ww_date = re.search(r'MDT\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4}).*?watch\s*(?:and|&)\s*wait',
                            text, re.IGNORECASE | re.DOTALL)
        if ww_date:
            result['ww_entered_date'] = ww_date.group(1)

        # Frequency
        freq = re.search(r'(\d+)\s*(?:month|week)(?:ly|s)?', text[m.start():], re.IGNORECASE)
        if freq:
            result['ww_frequency'] = freq.group(0)

    # W&W reasoning needs LLM — leave empty

    return result


def _extract_ww_dates(text: str) -> dict:
    result = {}

    # Look for repeated flexi sig dates in W&W context
    if not re.search(r'watch\s*(?:and|&)\s*wait', text, re.IGNORECASE):
        return result

    flexi_dates = re.findall(
        r'(?:flexi(?:ble)?\s*sig(?:moidoscopy)?|flex\s*sig)\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})',
        text, re.IGNORECASE
    )
    for i, d in enumerate(flexi_dates[:4]):
        result[f'ww_flexi_{i+1}_date'] = d

    mri_dates = re.findall(
        r'MRI\s*(?:on\s*)?(\d{1,2}/\d{1,2}/\d{4})',
        text, re.IGNORECASE
    )
    # Skip the first MRI (baseline) — take subsequent ones
    for i, d in enumerate(mri_dates[1:3]):
        result[f'ww_mri_{i+1}_date'] = d

    return result
