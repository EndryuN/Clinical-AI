# extractor/clinical_context.py
"""
Pre-extracted clinical reference context from:
G049 Dataset for histopathological reporting of colorectal cancer (RCPath, 2024).
Injected into the LLM system prompt on a per-group basis.
"""

_TNM8_T = """TNM 8 Tumour (T) staging:
- pT1: invasion into submucosa
- pT2: invasion into muscularis propria
- pT3: invasion beyond muscularis propria into pericolorectal tissues
  - pT3a: <1mm beyond muscularis propria
  - pT3b: 1-5mm beyond
  - pT3c: 5-15mm beyond
  - pT3d: >15mm beyond
- pT4a: tumour penetrates to the surface of the visceral peritoneum
- pT4b: tumour directly invades or is adherent to other organs/structures"""

_TNM8_N = """TNM 8 Nodal (N) staging:
- pN0: no regional lymph node metastasis
- pN1a: metastasis in 1 regional lymph node
- pN1b: metastasis in 2-3 regional lymph nodes
- pN1c: tumour deposit(s) in the subserosa/mesorectal fat, no nodal metastasis
- pN2a: metastasis in 4-6 regional lymph nodes
- pN2b: metastasis in 7 or more regional lymph nodes"""

_TNM8_M = """TNM 8 Metastasis (M) staging:
- M0: no distant metastasis
- M1a: metastasis confined to one organ or site (e.g., liver, lung, ovary, non-regional node)
- M1b: metastasis in more than one organ/site
- M1c: metastasis to the peritoneum with or without other organ involvement"""

_MMR = """Mismatch Repair (MMR) status:
- pMMR (proficient): normal expression of all 4 MMR proteins (MLH1, PMS2, MSH2, MSH6) on immunohistochemistry (IHC). Also called microsatellite stable (MSS).
- dMMR (deficient): loss of expression of one or more MMR proteins on IHC. Also called MSI-H (microsatellite instability-high).
Common text: "MMR proficient" = pMMR. "MMR deficient" or "dMMR" = dMMR.
Clinical significance: dMMR tumours respond to immunotherapy (pembrolizumab/nivolumab)."""

_EMVI = """Extramural Vascular Invasion (EMVI):
- MRI: tumour signal seen within vessels beyond the muscularis propria (mrEMVI).
  Reported as mrEMVI positive (+ve) or negative (-ve).
- Histological: venous invasion identified on H&E or elastin stain.
Adverse prognostic factor for recurrence and metastasis."""

_CRM = """Circumferential Resection Margin (CRM):
- Involved (R1): tumour <=1mm from the inked surgical resection margin.
- Threatened: tumour 1-2mm from the margin.
- Clear (R0): tumour >2mm from the margin.
On MRI, mrCRM is an estimate: <=1mm is reported as threatened/involved."""

_TRG = """Tumour Regression Grade (TRG) after neoadjuvant therapy - Mandard adapted (0-3):
- TRG 0: complete pathological response - no viable tumour cells
- TRG 1: near-complete response - rare residual tumour cells (<5% viable tumour)
- TRG 2: partial response - 5-95% residual viable tumour
- TRG 3: poor/no response - >95% residual viable tumour (minimal or no regression)"""

_GROUP_CONTEXT: dict[str, str] = {
    "Histology": _MMR,
    "Baseline MRI": "\n\n".join([_TNM8_T, _TNM8_N, _EMVI, _CRM]),
    "Baseline CT": "\n\n".join([_TNM8_T, _TNM8_N, _TNM8_M, _EMVI]),
    "Second MRI": "\n\n".join([_TRG, _EMVI, _CRM]),
    "12-Week MRI": "\n\n".join([_TRG, _EMVI, _CRM]),
}


def get_context_for_group(group_name: str) -> str:
    """Return G049 clinical reference context for the given group, or '' if none."""
    return _GROUP_CONTEXT.get(group_name, "")
