# Clinical AI Hackathon - Problem Statements & Considerations

## Problem Statement (Dr Anita Wale, NHS)

Cancer patients in the NHS are discussed in weekly **Multidisciplinary Team Meetings (MDTs)**. The process:

- Patients are referred to an **MDT coordinator** who collates clinical histories, treatments, questions, imaging, and pathology
- Lists are circulated as **Word documents** to all attendees
- Outcomes are recorded in a database called **InfoFlex**, but data collection is **inconsistent** and extracting meaningful data is extremely difficult
- Clinicians resort to **manual databases**, which is laborious

**Core Challenge:** Can the MDT lists and outcome sheets (Word documents) be used as input to **automatically populate a searchable database**, rather than requiring manual data entry?

> "Across the NHS there are researchers laboriously looking through notes to find out what has happened to patients and improve care, can you help?"

---

## Dataset

- **Input:** `data/hackathon-mdt-outcome-proformas.docx` — 50 synthetic MDT cases, anonymized with dummy NHS numbers (starting with "NNN") and date shifting
- **Ground Truth:** `data/hackathon-database-prototype.xlsx` — Longitudinal patient data in sequential (linear) format in Excel. Cells left null/empty where information is missing or not discussed.

---

## Success Criteria

**"Longitudinal patient data presented in Excel reflects patient history contained in Word document."**

Extract clinical findings as prose directly from the MDT documents into the specific Excel format provided as ground truth.

---

## Evaluation / Judging Criteria

**Three dimensions, each scored 1-4:**

| Score | Meaning |
|-------|---------|
| 1 | Not all core requirements implemented — major gaps |
| 2 | All core requirements implemented — works end-to-end, accurate/useful output |
| 3 | Surpassed expectations — clever features, polish, real-world ready |
| 4 | Blew my mind — innovative, clinically transformative, wow factor |

**Dimensions:**
1. **Documentation** (1-4)
2. **Presentation** (1-4)
3. **Code** (1-4)
4. **Total** (3-12)

**Prize categories:** Best Documentation, Best Presentation, Best Code, Overall Winner

**Score 4 guidance:** Use sparingly — e.g., unusually accurate/safe extraction, smart clinician-friendly additions (confidence flags, summaries), elegant edge case handling, clear potential to save serious time/errors in NHS/MoD workflows.

---

## Technical Considerations (Dr Alex Nicholls, MOD)

### DTAC (Digital Technology Assessment Criteria)
- Software should align with DTAC, specifically regarding **clinical safety** (DCB0129/DCB0160) and **data residency**

### Medical Device Compliance
- Depending on risk level and clinical decision support, the software could be classified as **Software as a Medical Device (SaMD)**, requiring specific regulatory adherence

### HL7 FHIR
- Fast Healthcare Interoperability Resources — modern, open-source standards framework for secure exchange of electronic health data via RESTful APIs
- Key concepts: Resources (Patient, Observation, Medication), API-First Design, Extensibility
- Formats: JSON or XML

### SNOMED CT
- Comprehensive codes for tumour morphology (type), topography (site), staging and grading
- Aligns with international standards such as TNM Classification
- Used in pathology reports to identify, classify, and stage tumours in EHRs

---

## Baseline Results (Reference)

| Metric | Gemini | Codex | Claude Code |
|--------|--------|-------|-------------|
| Non-empty Cells | 127 | 661 | 675 |
| Normalized Match | 8/12 | 10/12 | 11/12 (est.) |

**Known gaps in baselines:**
- Treatment specifics (chemo, radiotherapy, immunotherapy) mostly empty
- Pathology detail (histology biopsy dates, second MRI results) largely missing
- 61+ target columns still empty
- Follow-up and later-pathway fields unimplemented
- MDT decision normalization only works for cases with explicit "Outcome:" labels

---

## Key Dates

- **Today (March 19):** Documentation day / All-nighter
- **Friday March 20:** Opening Ceremony (10:00), Presentations (10:30-13:30), Awards (14:30-15:00)
