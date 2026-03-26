# extractor/clinical_context.py
"""
Clinical reference context injected into LLM system prompts per group.

Sources:
- G049 Dataset for histopathological reporting of colorectal cancer (RCPath, 2024)
- Radiopaedia: Rectal cancer staging (TNM 8, MRI-specific criteria)
- NHS colorectal cancer MDT reporting standards
- NICE NG151 Colorectal cancer guidelines
"""

# ── Radiological staging (for MRI/CT groups) ──

_MRI_T = """MRI Tumour (mrT) staging:
- mrT1: tumour invades submucosa (MRI cannot reliably differentiate T1 from T2)
- mrT2: tumour invades muscularis propria (confined to bowel wall)
- mrT3: tumour extends through muscularis propria into perirectal fat
  - mrT3a: <1mm beyond muscularis propria
  - mrT3b: 1-5mm beyond
  - mrT3c: 5-15mm beyond
  - mrT3d: >15mm beyond
- mrT4a: tumour penetrates visceral peritoneum
- mrT4b: tumour invades adjacent organs
Note: Desmoplastic reaction (spiky/sharp) can mimic T3 — tumour has nodular/lumpy configuration.
Common text: "T3" without substage = report as "T3". Only add substage if distance is stated."""

_MRI_N = """MRI Nodal (mrN) staging:
- mrN0: no suspicious lymph nodes
- mrN1: 1-3 suspicious mesorectal lymph nodes
  - N1a: metastasis in 1 node
  - N1b: metastasis in 2-3 nodes
  - N1c: tumour deposits in mesentery/perirectal fat without nodal metastasis
- mrN2: 4 or more suspicious lymph nodes
  - N2a: 4-6 nodes
  - N2b: 7+ nodes
MRI criteria for suspicious nodes: signal heterogeneity, irregular contour, round shape.
- >9mm short axis = suspicious
- 5-9mm with 2 of 3 criteria (heterogeneous/irregular/round) = suspicious
- <5mm needs all 3 criteria
Common text: "N0", "N1", "N2", "no lymphadenopathy" = N0.
If text says "mesorectal lymph nodes" without specifying count, infer based on description.
If text says "associated mesorectal lymph nodes" without specifying count = likely N1.
If text says "multiple" or "extensive" lymph nodes = likely N2.
Always quote the source text in your reason when inferring."""

_CT_M = """CT Metastasis (M) staging:
- M0: no distant metastasis on imaging
- M1a: metastasis in one organ (e.g., liver only, lung only, ovary, non-regional node)
- M1b: metastasis in more than one organ
- M1c: peritoneal metastasis (with or without other organ involvement)
Common text: "no distant metastases" = M0. "liver mets" = M1a. "lung and liver mets" = M1b.
"multiple nodules suspicious for lung metastases" = M1a (single organ: lung).
"peritoneal disease" or "peritoneal deposits" = M1c."""

_EMVI = """Extramural Vascular Invasion (EMVI) on MRI:
- mrEMVI positive (+ve): tumour signal in serpiginous/tubular vessels beyond muscularis propria
  May be contiguous or non-contiguous with primary tumour
  Non-contiguous deposits = N1c
  Predictor of haematogenous spread (poor prognosis)
- mrEMVI negative (-ve): no vascular invasion seen
Common text: "EMVI +ve", "EMVI positive", "EMVI -ve", "EMVI negative"
Report as: "Positive" or "Negative"."""

_CRM = """Circumferential Resection Margin (CRM) on MRI:
The CRM is represented by the mesorectal fascia (MRF).
- CRM positive/involved: tumour, involved node, or EMVI within 1mm of mesorectal fascia
- CRM threatened: tumour 1-2mm from mesorectal fascia
- CRM clear: tumour >2mm from mesorectal fascia
Note: Peritoneal reflection does not constitute CRM — involvement there = at least T4a.
Common text: "CRM clear", "CRM involved", "CRM threatened", "CRM unsafe"
If distance stated (e.g., "CRM 3mm"), report as "Clear (3mm)"."""

_TRG = """Tumour Regression Grade (TRG) after neoadjuvant therapy:
- TRG 0: complete response — no viable tumour
- TRG 1: near-complete — rare residual tumour (<5%)
- TRG 2: partial response — 5-95% residual tumour
- TRG 3: poor/no response — >95% residual tumour
Report as: "TRG 0", "TRG 1", "TRG 2", or "TRG 3"."""

_STAGE_GROUPS = """Stage groupings (for reference):
- Stage 0: Tis N0 M0
- Stage I: T1-2 N0 M0
- Stage IIa: T3 N0 M0
- Stage IIb: T4a N0 M0
- Stage IIc: T4b N0 M0
- Stage IIIa: T1-2 N1 M0
- Stage IIIb: T3-4 N1 M0
- Stage IIIc: T3-4b N2 M0
- Stage IV: any T, any N, M1"""

# ── Pathological definitions (for histology) ──

_MMR = """Mismatch Repair (MMR) status:
- Proficient (pMMR/MSS): normal expression of MLH1, PMS2, MSH2, MSH6
- Deficient (dMMR/MSI-H): loss of one or more MMR proteins
Common text: "MMR proficient", "MMR deficient", "dMMR", "MSI-H", "MSS"
Report as: "Proficient" or "Deficient"."""

# ── Clinical context (for treatment/endoscopy groups) ──

_ENDOSCOPY_CONTEXT = """Endoscopy type classification:
- "Colonoscopy complete": full examination to caecum/terminal ileum completed
  Look for: "caecum reached", "complete to caecum", "terminal ileum", "complete examination"
- "Incomplete colonoscopy": examination did not reach caecum
  Look for: "incomplete", "unable to pass", "could not reach caecum", "failed", "stenosis", "stricture"
- "Flexi sig": flexible sigmoidoscopy (limited examination of left colon/rectum)
  Look for: "flexi sig", "flexible sigmoidoscopy", "FS"
If no qualifier stated and "colonoscopy" is mentioned, report as "Colonoscopy complete"."""

_SURGERY_CONTEXT = """Surgery types and intent in colorectal cancer:
- APR (abdominoperineal resection): removal of rectum + anus, permanent stoma
- LAR (low anterior resection): removal of rectum, anastomosis preserved
- AR (anterior resection): standard rectal resection
- Hemicolectomy: removal of half the colon (right or left)
- TME (total mesorectal excision): en-bloc removal of mesorectum
- Hartmann's: resection with end colostomy, no anastomosis
- Defunctioning stoma: temporary diversion, not definitive surgery

Intent classification:
- "Curative": surgery aims to remove all disease
- "Palliative": surgery to relieve symptoms (e.g., obstruction), not cure
- "Neoadjuvant then surgery": chemotherapy/radiotherapy before planned surgery
Report the intent as stated or inferred from context."""

_WATCH_WAIT_CONTEXT = """Watch and Wait (W&W) programme:
Patients who achieve complete clinical response (cCR) after neoadjuvant therapy
may be offered organ-preserving surveillance instead of surgery.

Entry reasons:
- "Complete clinical response" / "cCR" on MRI + endoscopy
- "Near-complete response" with ongoing monitoring
- "Patient preference" / "declined surgery"

Common text: "watch and wait", "W&W", "active surveillance", "organ preservation"
If the reason is not explicitly stated, look for response assessment results."""

# ── Common abbreviations (injected into all LLM prompts) ──

ABBREVIATIONS = """Common abbreviations:
CRT=chemoradiotherapy, TNT=total neoadjuvant therapy, SCRT=short-course radiotherapy,
LCCRT=long-course chemoradiotherapy, APR=abdominoperineal resection, LAR=low anterior resection,
AR=anterior resection, TME=total mesorectal excision, ISP=intersphincteric plane,
+ve=positive, -ve=negative, NAD=nothing abnormal detected, Hx=history, Bx=biopsy,
Dx=diagnosis, Rx=treatment, FS=flexi sig, CT TAP=CT thorax abdomen pelvis,
PET-CT=positron emission tomography CT, FDG=fluorodeoxyglucose, CEA=carcinoembryonic antigen,
DRE=digital rectal examination, MDT=multidisciplinary team, W&W=watch and wait."""


# ── Group → Context mapping ──

_GROUP_CONTEXT: dict[str, str] = {
    "Histology": _MMR,
    "Baseline MRI": "\n\n".join([_MRI_T, _MRI_N, _EMVI, _CRM, _STAGE_GROUPS]),
    "Baseline CT": "\n\n".join([_MRI_T, _MRI_N, _CT_M, _EMVI, _STAGE_GROUPS]),
    "Second MRI": "\n\n".join([_TRG, _EMVI, _CRM]),
    "12-Week MRI": "\n\n".join([_TRG, _EMVI, _CRM]),
    "Endoscopy": _ENDOSCOPY_CONTEXT,
    "Surgery": _SURGERY_CONTEXT,
    "Watch and Wait": _WATCH_WAIT_CONTEXT,
}


def get_context_for_group(group_name: str) -> str:
    """Return clinical reference context for the given group, or '' if none."""
    return _GROUP_CONTEXT.get(group_name, "")
