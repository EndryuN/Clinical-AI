# Presentation Notes — MDT Data Extractor

**Format:** 7 min presentation + 3 min Q&A

**Timing:**
- Problem (1.5 min) — set the scene, make judges feel the pain
- Solution (1.5 min) — what we built, key design decisions
- How the model works (2 min) — architecture, category-grouped extraction, confidence scoring
- Limitations & improvements (1 min) — honest about gaps, clear roadmap
- Live demo woven in (1 min) — quick walkthrough during solution/model sections

---

## 1. Problem We're Facing

**The NHS MDT data bottleneck:**

- Cancer patients are discussed weekly in **Multidisciplinary Team Meetings** (MDTs) — bringing together radiologists, pathologists, oncologists, surgeons
- Patient histories, imaging results, treatments, and outcomes are circulated as **Word documents**
- After the meeting, outcomes should be recorded in databases (e.g., InfoFlex) — but data collection is **inconsistent** and extraction for audit/research is extremely difficult
- Clinicians resort to **manually copying data** from Word documents into spreadsheets — field by field, patient by patient
- This means researchers across the NHS spend **hours to days** just finding out what happened to patients

**Dr Anita Wale (NHS):**
> "Across the NHS there are researchers laboriously looking through notes to find out what has happened to patients and improve care, can you help?"

**The scale of the problem:**
- 97 data fields per patient (demographics, endoscopy, histology, imaging, staging, treatment, surgery, follow-up)
- 50+ patients per MDT list
- Multiple MDT meetings per week across the NHS
- Manual data entry = errors, inconsistency, and researcher burnout

---

## 2. How the Problem Will Be Solved

**Our solution: A locally-hosted web application that automates the extraction.**

**Workflow:**
1. **Upload** — Clinician drags a Word document onto the web interface
2. **Parse** — System automatically detects all patients in the document (e.g., "50 patients found")
3. **Extract** — A local AI model reads each patient's notes and extracts structured data into 88 clinical fields, grouped into 16 categories
4. **Review** — Clinician reviews extractions in a dashboard with confidence scoring (GREEN = high, AMBER = medium, RED = low). They can edit any field before export.
5. **Export** — One click produces a standardised Excel spreadsheet matching the required 97-column format

**Key design decisions:**
- **Fully local processing** — No patient data ever leaves the machine. The AI model (Llama 3.1 8B) runs on localhost via Ollama. This satisfies DTAC data residency requirements.
- **Human-in-the-loop** — The AI assists data entry; the clinician makes the final call. This is a data extraction aid, not an autonomous system.
- **Config-driven** — A single YAML configuration file defines all 88 fields. Change the config to support a different cancer pathway — no code changes needed.
- **Confidence scoring** — Every extracted value gets a confidence rating. Low-confidence fields are highlighted in red so clinicians know exactly where to focus their review.
- **Audit trail** — Every extraction and manual edit is logged with timestamps for clinical safety and traceability (DTAC/DCB0129 alignment).

---

## 3. How the Model Works

**Architecture:**

```
Word Document (.docx)
        |
        v
  Document Parser (python-docx)
        |  Splits into per-patient text blocks
        v
  For each patient, for each clinical category:
        |
        v
  Prompt Builder (reads field_schema.yaml)
        |  Generates a focused prompt for each category
        |  e.g., "Extract Demographics: DOB, Gender, NHS Number..."
        v
  Local LLM (Ollama — Llama 3.1 8B on localhost)
        |  Returns JSON: {"dob": {"value": "26/05/1970", "confidence": "high"}, ...}
        v
  Response Parser
        |  Validates JSON structure
        |  Applies programmatic confidence overrides:
        |    - Date fields that fail DD/MM/YYYY → forced to LOW
        |    - Null values → forced to LOW regardless of LLM self-assessment
        |    - This hybrid approach compensates for small model limitations
        v
  Review Dashboard (Flask + Bootstrap)
        |  Clinician reviews, edits, filters by category and confidence
        v
  Excel Export (openpyxl)
        |  Maps fields to exact column positions via schema
        v
  97-column Excel spreadsheet
```

**Why category-grouped extraction?**
- Instead of asking the LLM for all 88 fields in one prompt (which overwhelms a small model), we split into 16 focused prompts per patient
- Each prompt covers 2-15 related fields (e.g., "Baseline MRI" = 6 fields)
- This dramatically improves extraction accuracy on an 8B parameter model
- 50 patients x 16 categories = ~800 LLM calls, but each is focused and reliable

**Why a local model instead of GPT-4/Claude API?**
- These are patient records — data residency is non-negotiable
- Local model = zero data leakage risk
- The confidence scoring + human review compensates for smaller model accuracy
- Runs on a standard laptop (8GB+ free RAM)

**Tech stack:**
- Python / Flask (backend)
- Ollama + Llama 3.1 8B (local LLM)
- python-docx (Word parsing), openpyxl (Excel generation)
- Bootstrap 5 dark theme, Chart.js, DataTables (frontend)
- field_schema.yaml (single source of truth for all 88 fields)

---

## 4. Current Limitations & Further Improvements

### Current Limitations

| Limitation | Impact | Mitigation |
|-----------|--------|-----------|
| **8B model accuracy** | Some fields may be extracted incorrectly, especially complex prose descriptions | Confidence scoring flags uncertain extractions; clinician reviews before export |
| **Single document format** | Parser is tuned for the specific hackathon proforma structure | Config-driven approach means re-tuning the parser for new formats requires minimal code changes |
| **Sequential processing** | 50 patients x 16 categories = ~800 LLM calls, takes 15-25 min on CPU | GPU inference would be ~10x faster; progress bar keeps clinician informed |
| **No persistent storage** | Data is held in memory; closing the app loses the session | Acceptable for the hackathon scope; database backend is a natural extension |
| **English-only** | Assumes MDT notes are in English | Covers the immediate NHS use case |

### Further Improvements

**Short-term (next iteration):**
- **SNOMED CT coding** — Automatically tag extracted tumour morphology, topography, and staging with SNOMED CT codes for international standardisation
- **HL7 FHIR output** — Generate FHIR resources (Patient, Observation, Condition) alongside Excel for interoperability with modern EHR systems
- **PDF and scanned document support** — Add OCR capability for handwritten or scanned MDT notes
- **Database backend** — Persistent storage across sessions, enabling longitudinal queries

**Medium-term (production readiness):**
- **Larger models** — When hardware allows, 70B parameter models would significantly improve accuracy and reduce low-confidence extractions
- **Multi-user support** — Authentication and concurrent sessions for MDT teams
- **Batch processing** — Upload multiple documents and process overnight
- **SaMD assessment** — Full clinical safety assessment (DCB0129) if the tool moves toward clinical decision support

**Long-term (vision):**
- **Cross-site deployment** — Standardised extraction across multiple NHS trusts
- **Research data pipeline** — Direct feed into research databases for clinical trials and outcome auditing
- **Real-time MDT integration** — Extract data during the meeting from live notes, not after the fact

---

## Demo Script (if doing a live demo)

1. Open http://localhost:5000 — show the landing page, point out "all processing local"
2. Drag the hackathon `.docx` file — show "50 patients detected"
3. Click "Start Extraction" — show the live progress bar and category badges
4. Go to Review — click a patient, show category tabs, show confidence colours
5. Edit a field live — change a value, show it saves
6. Switch to "Low Confidence Only" filter — show focused review
7. Show source text panel — "clinician can always verify against the document"
8. Click "Export Excel" — open it, show columns match ground truth
9. Show Analytics page — charts for cancer types and confidence distribution

---

## Q&A Prep

**Q: How accurate is it?**
A: Depends on the field. Demographics (names, dates, numbers) are high accuracy. Complex prose fields (treatment decisions, clinical findings) are medium. The confidence system ensures clinicians don't trust the AI blindly.

**Q: Why not a cloud API?**
A: Patient data. DTAC requires data residency. Local model = zero leakage risk.

**Q: Could this work for other cancer types?**
A: Yes — edit the YAML config to define new fields. The extraction engine is cancer-type agnostic.

**Q: What about clinical safety?**
A: Human-in-the-loop by design. Audit trail logs everything. Not classified as a medical device since it assists data entry, not clinical decisions.
