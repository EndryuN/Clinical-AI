# app.py
import os

# Load .env BEFORE any other imports so API keys are available
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _val = _line.split('=', 1)
                os.environ[_key.strip()] = _val.strip()

import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, send_file, stream_with_context
from models import ExtractionSession, PatientBlock, FieldResult
from parser.docx_parser import parse_docx, get_raw_text
from extractor.llm_client import check_ollama, generate, get_backend, set_backend, check_ollama_available, check_claude_available
from extractor.prompt_builder import build_prompt, build_all_prompts
from extractor.response_parser import parse_llm_response
from export.excel_writer import write_excel
from config import get_groups, get_all_fields
from audit import log_event
import json

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Global session (one at a time)
session = ExtractionSession()


@app.route('/')
def index():
    return render_template('index.html',
                           session_active=(session.status == 'complete'),
                           current_backend=get_backend(),
                           ollama_available=check_ollama_available(),
                           claude_available=check_claude_available())


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    filename = file.filename.lower()

    if not (filename.endswith('.docx') or filename.endswith('.xlsx')):
        return jsonify({"error": "Only .docx and .xlsx files are supported"}), 400

    # Save file with timestamp to avoid permission errors on re-upload
    import time
    safe_name = f"{int(time.time())}_{file.filename}"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
    file.save(file_path)

    session.file_name = safe_name
    session.upload_time = datetime.now().isoformat()

    try:
        if filename.endswith('.xlsx'):
            # Import previously exported Excel — skip extraction
            patients = _import_excel(file_path)
            session.patients = patients
            session.status = 'complete'
            session.progress['total'] = len(patients)
            session.progress['current_patient'] = len(patients)

            log_event('import_excel', file_name=file.filename, patients_imported=len(patients))

            return jsonify({
                "status": "ok",
                "patients_detected": len(patients),
                "imported": True,
                "patient_list": [
                    {"id": p.id, "initials": p.initials, "nhs_number": p.nhs_number}
                    for p in patients
                ]
            })
        else:
            # Parse .docx and detect patients
            session.status = 'parsing'
            patients = parse_docx(file_path)
            session.patients = patients
            session.status = 'parsed'
            session.progress['total'] = len(patients)

            log_event('upload', file_name=file.filename, patients_detected=len(patients))

            return jsonify({
                "status": "ok",
                "patients_detected": len(patients),
                "imported": False,
                "patient_list": [
                    {"id": p.id, "initials": p.initials, "nhs_number": p.nhs_number}
                    for p in patients
                ]
            })
    except Exception as e:
        session.status = 'idle'
        return jsonify({"error": str(e)}), 500


def _import_excel(file_path: str) -> list:
    """Import a previously exported Excel file back into PatientBlock objects."""
    from openpyxl import load_workbook

    all_fields = get_all_fields()
    groups = get_groups()

    # Build reverse lookup: excel_column → (group_name, field_key, field_type)
    col_to_field = {}
    for field in all_fields:
        col_to_field[field['excel_column']] = (field['group_name'], field['key'], field['type'])

    wb = load_workbook(file_path)
    ws = wb.active

    patients = []
    for row_idx in range(2, ws.max_row + 1):
        # Check if row is a real patient (must have MRN col 3 or NHS number col 4)
        mrn_val = ws.cell(row=row_idx, column=3).value
        nhs_val = ws.cell(row=row_idx, column=4).value
        if not mrn_val and not nhs_val:
            continue

        # Build extractions from Excel data
        extractions = {}
        for group in groups:
            group_fields = {}
            for field in group['fields']:
                col = field['excel_column']
                cell_value = ws.cell(row=row_idx, column=col).value
                if cell_value is not None:
                    value = str(cell_value).strip()
                    group_fields[field['key']] = FieldResult(value=value, confidence='high')
                else:
                    group_fields[field['key']] = FieldResult(value=None, confidence='none')
            extractions[group['name']] = group_fields

        # Get patient identifiers from Demographics fields
        initials = ""
        nhs_number = ""
        patient_id = f"patient_{row_idx - 1:03d}"

        demo = extractions.get("Demographics", {})
        if "initials" in demo and demo["initials"].value:
            initials = demo["initials"].value
        if "nhs_number" in demo and demo["nhs_number"].value:
            nhs_number = demo["nhs_number"].value
        if "mrn" in demo and demo["mrn"].value:
            patient_id = demo["mrn"].value

        # Derive cancer type from biopsy result for the raw_text header
        biopsy = extractions.get("Histology", {}).get("biopsy_result")
        cancer_type = ""
        if biopsy and biopsy.value and biopsy.value.lower() not in ('missing', 'n/a', ''):
            cancer_type = biopsy.value.split(',')[0].strip().title()

        patients.append(PatientBlock(
            id=patient_id,
            initials=initials,
            nhs_number=nhs_number,
            raw_text=f"Diagnosis: {cancer_type.upper()}\n(imported from Excel)" if cancer_type else "(imported from Excel)",
            extractions=extractions,
        ))

    wb.close()
    return patients


@app.route('/extract', methods=['POST'])
def extract():
    if session.status not in ('parsed', 'complete'):
        return jsonify({"error": "No document uploaded or already extracting"}), 400

    data = request.json or {}
    patient_limit = data.get('limit', None)  # Optional: limit number of patients to process

    session.status = 'extracting'

    # Run extraction in background thread
    thread = threading.Thread(target=_run_extraction, args=(patient_limit,))
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})


def _run_extraction(patient_limit=None):
    groups = get_groups()
    completed_patients = []

    patients_to_process = session.patients[:patient_limit] if patient_limit else session.patients
    session.progress['total'] = len(patients_to_process)

    for i, patient in enumerate(patients_to_process):
        session.progress['current_patient'] = i + 1

        for group in groups:
            session.progress['current_group'] = group['name']

            try:
                prompt = build_prompt(patient.raw_text, group)
                raw_response = generate(prompt)
                results = parse_llm_response(raw_response, group)

                # Retry once if all fields are null (likely malformed response)
                all_null = all(fr.value is None for fr in results.values())
                if all_null and len(group['fields']) > 0:
                    raw_response = generate(prompt)
                    results = parse_llm_response(raw_response, group)

                patient.extractions[group['name']] = results

                conf_summary = {"high": 0, "medium": 0, "low": 0}
                for fr in results.values():
                    if fr.confidence in conf_summary:
                        conf_summary[fr.confidence] += 1

                log_event('extraction',
                          patient_id=patient.nhs_number,
                          group=group['name'],
                          fields_extracted=len(results),
                          confidence_summary=conf_summary)
            except Exception as e:
                patient.extractions[group['name']] = {
                    f['key']: FieldResult(value=None, confidence='low')
                    for f in group['fields']
                }
                log_event('extraction_error',
                          patient_id=patient.nhs_number,
                          group=group['name'],
                          error=str(e))

        # Track completed patient for SSE progress
        completed_patients.append({
            "id": patient.id,
            "initials": patient.initials,
            "confidence_summary": _confidence_summary(patient)
        })
        session.progress['completed_patients'] = completed_patients

    session.status = 'complete'


@app.route('/progress')
def progress():
    def event_stream():
        import time
        last_patient = 0
        while session.status == 'extracting':
            current = session.progress.get('current_patient', 0)
            if current != last_patient:
                last_patient = current
                event_data = {
                    "current_patient": session.progress['current_patient'],
                    "total": session.progress['total'],
                    "current_group": session.progress.get('current_group', ''),
                    "completed_patients": session.progress.get('completed_patients', [])
                }
                yield f"data: {json.dumps(event_data)}\n\n"
            time.sleep(1)
        # Final event
        yield f"data: {json.dumps({'status': 'complete', 'total': session.progress['total']})}\n\n"

    return Response(stream_with_context(event_stream()), mimetype='text/event-stream')


@app.route('/process')
def process_page():
    return render_template('process.html', session_active=(session.status == 'complete'))


@app.route('/patients')
def get_patients():
    cancer_type = request.args.get('cancer_type', '')
    search = request.args.get('search', '').lower()

    result = []
    for p in session.patients:
        ct = _get_cancer_type(p)

        if cancer_type and ct != cancer_type:
            continue
        if search and search not in p.initials.lower() and search not in p.nhs_number:
            continue

        conf = _confidence_summary(p)
        result.append({
            "id": p.id,
            "initials": p.initials,
            "nhs_number": p.nhs_number,
            "gender": _get_field_value(p, "Demographics", "gender"),
            "cancer_type": ct,
            "confidence_summary": conf
        })

    return jsonify({"patients": result})


@app.route('/patients/<patient_id>')
def get_patient(patient_id):
    patient = _find_patient(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    extractions = {}
    for group_name, fields in patient.extractions.items():
        extractions[group_name] = {
            key: {"value": fr.value, "confidence": fr.confidence, "reason": fr.reason, "edited": fr.edited}
            for key, fr in fields.items()
        }

    return jsonify({
        "id": patient.id,
        "initials": patient.initials,
        "nhs_number": patient.nhs_number,
        "raw_text": patient.raw_text,
        "extractions": extractions
    })


@app.route('/patients/<patient_id>/fields', methods=['PUT'])
def edit_field(patient_id):
    patient = _find_patient(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    data = request.json
    group = data.get('group')
    field_key = data.get('field')
    new_value = data.get('value')

    if group not in patient.extractions or field_key not in patient.extractions[group]:
        return jsonify({"error": "Field not found"}), 404

    fr = patient.extractions[group][field_key]
    old_value = fr.value

    if not fr.edited:
        fr.original_value = old_value
    fr.value = new_value
    fr.edited = True

    log_event('manual_edit',
              patient_id=patient.nhs_number,
              group=group, field=field_key,
              old_value=old_value, new_value=new_value)

    return jsonify({"status": "ok", "old_value": old_value, "new_value": new_value})


@app.route('/patients/<patient_id>/re-extract', methods=['POST'])
def re_extract(patient_id):
    patient = _find_patient(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    data = request.json or {}
    target_groups = data.get('groups', [g['name'] for g in get_groups()])

    def _do_re_extract():
        for group in get_groups():
            if group['name'] in target_groups:
                try:
                    prompt = build_prompt(patient.raw_text, group)
                    raw_response = generate(prompt)
                    results = parse_llm_response(raw_response, group)
                    patient.extractions[group['name']] = results
                except Exception:
                    pass

    thread = threading.Thread(target=_do_re_extract)
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})


@app.route('/export')
def export():
    if session.status != 'complete' or not session.patients:
        return jsonify({"error": "No data to export"}), 400

    output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'export.xlsx')
    write_excel(session.patients, output_path)

    log_event('export', patients_exported=len(session.patients), format='xlsx')

    return send_file(output_path,
                     download_name='mdt_extraction.xlsx',
                     as_attachment=True)


@app.route('/analytics')
def analytics_data():
    if not session.patients:
        return jsonify({})

    cancer_types = {}
    treatments = {}
    confidence = {"high": 0, "medium": 0, "low": 0}

    for p in session.patients:
        ct = _get_cancer_type(p)
        cancer_types[ct] = cancer_types.get(ct, 0) + 1

        treat = _get_field_value(p, "MDT", "first_mdt_treatment")
        if treat:
            # Extract key treatment keywords from the free-text outcome
            for keyword in _extract_treatment_keywords(treat):
                treatments[keyword] = treatments.get(keyword, 0) + 1

        for fields in p.extractions.values():
            for fr in fields.values():
                if fr.confidence in confidence:  # skip "none" (null/absent)
                    confidence[fr.confidence] += 1

    return jsonify({
        "cancer_types": cancer_types,
        "treatments": treatments,
        "confidence": confidence
    })


@app.route('/analytics/column/<field_key>')
def column_stats(field_key):
    """Compute statistics for a specific column across all patients."""
    import re
    from datetime import date

    is_dob = (field_key == 'dob')

    values = []
    numeric_values = []
    value_counts = {}

    for p in session.patients:
        for group_name, fields in p.extractions.items():
            if field_key in fields:
                v = fields[field_key].value
                if v is not None and v.lower() not in ('missing', 'n/a', ''):
                    if is_dob:
                        age = _dob_to_age(v)
                        if age is not None:
                            display = str(age)
                            values.append(display)
                            numeric_values.append(float(age))
                            value_counts[display] = value_counts.get(display, 0) + 1
                    else:
                        values.append(v)
                        value_counts[v] = value_counts.get(v, 0) + 1
                        try:
                            numeric_values.append(float(re.sub(r'[^\d.\-]', '', v)))
                        except (ValueError, TypeError):
                            pass

    result = {
        "field": "Age (from DOB)" if is_dob else field_key,
        "total_patients": len(session.patients),
        "populated": len(values),
        "empty": len(session.patients) - len(values),
        "unique_values": len(set(values)),
        "value_distribution": dict(sorted(value_counts.items(), key=lambda x: -x[1])[:20]),
    }

    if numeric_values:
        n = len(numeric_values)
        mean = sum(numeric_values) / n
        variance = sum((x - mean) ** 2 for x in numeric_values) / n if n > 1 else 0
        std_dev = variance ** 0.5
        result["numeric"] = True
        result["mean"] = round(mean, 2)
        result["std_dev"] = round(std_dev, 2)
        result["min"] = round(min(numeric_values), 2)
        result["max"] = round(max(numeric_values), 2)
        result["count"] = n
    else:
        result["numeric"] = False

    return jsonify(result)


def _dob_to_age(dob_str: str):
    """Convert a DOB string to age in years (for analytics only)."""
    from datetime import date
    import re
    try:
        m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', dob_str)
        if m:
            born = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        else:
            m = re.match(r'(\d{4})-(\d{2})-(\d{2})', dob_str)
            if m:
                born = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            else:
                return None
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except (ValueError, TypeError):
        return None


@app.route('/analytics-page')
def analytics_page():
    return render_template('analytics.html', session_active=(session.status == 'complete'))


@app.route('/schema')
def schema():
    """Return schema groups with colours and field keys for the frontend."""
    groups = get_groups()
    return jsonify([{
        "name": g['name'],
        "color": g.get('color', '#D9D9D9'),
        "fields": [f['key'] for f in g['fields']]
    } for g in groups])


@app.route('/review')
def review_page():
    return render_template('review.html', session_active=(session.status == 'complete'))


@app.route('/audit')
def audit_trail():
    from audit import read_log
    return jsonify(read_log())


@app.route('/debug/raw-text')
def debug_raw_text():
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], session.file_name) if session.file_name else None
    if not file_path or not os.path.exists(file_path):
        return "No file uploaded", 404
    return f"<pre>{get_raw_text(file_path)}</pre>"


@app.route('/backend', methods=['GET', 'POST'])
def backend():
    """Get or set the LLM backend."""
    if request.method == 'POST':
        data = request.json or {}
        choice = data.get('backend', 'ollama')
        set_backend(choice)
        return jsonify({"status": "ok", "backend": get_backend()})
    return jsonify({
        "backend": get_backend(),
        "ollama_available": check_ollama_available(),
        "claude_available": check_claude_available()
    })


@app.route('/reset', methods=['POST'])
def reset():
    """Wipe all session data and start fresh."""
    global session
    session = ExtractionSession()
    # Clear audit log
    log_path = os.path.join(os.path.dirname(__file__), 'logs', 'audit.jsonl')
    if os.path.exists(log_path):
        os.remove(log_path)
    log_event('reset')
    return jsonify({"status": "ok"})


# Helper functions
def _find_patient(patient_id: str):
    for p in session.patients:
        if p.id == patient_id:
            return p
    return None


def _get_field_value(patient, group_name, field_key):
    if group_name in patient.extractions and field_key in patient.extractions[group_name]:
        return patient.extractions[group_name][field_key].value
    return None


def _get_cancer_type(patient):
    import re
    # 1. Extract from Diagnosis line (e.g., "Diagnosis: ADENOCARCINOMA, NOT OTHERWISE SPECIFIED")
    m = re.search(r'Diagnosis:\s*([A-Z][A-Z\s\-]+)', patient.raw_text)
    if m:
        diag = m.group(1).strip()
        if not diag.upper().startswith('ICD'):
            diag = re.split(r',\s*', diag)[0].strip()
            return diag.title()
    # 2. Fallback: try the LLM-extracted biopsy_result
    biopsy = _get_field_value(patient, "Histology", "biopsy_result")
    if biopsy and biopsy.lower() not in ('missing', 'n/a', 'null'):
        return biopsy.split(',')[0].strip().title()
    # 3. No diagnosis yet
    return "Pending Diagnosis"


def _extract_treatment_keywords(text: str) -> list[str]:
    """Extract recognisable treatment categories from free-text MDT outcome."""
    import re
    text_lower = text.lower()
    found = []

    keywords = [
        ('TNT', r'\btnt\b'),
        ('Chemotherapy', r'chemo(?:therapy)?'),
        ('Radiotherapy', r'radio(?:therapy)?|chemoradio'),
        ('Short-course RT', r'short.?course'),
        ('Long-course CRT', r'long.?course'),
        ('Surgery', r'surgery|resection|hemicolectomy|colectomy|anterior resection|apr\b'),
        ('Watch & Wait', r'watch\s*(?:and|&)\s*wait'),
        ('Palliative', r'palliat'),
        ('MRI', r'\bmri\b'),
        ('CT scan', r'\bct\b(?!\.)|pet.?ct'),
        ('Papillon', r'papillon'),
        ('Immunotherapy', r'immuno(?:therapy)?|pembrolizumab|nivolumab'),
        ('Stoma', r'stoma|defunction'),
        ('Biopsy', r'biopsy'),
        ('Referred', r'refer|rediscuss|relist'),
    ]

    for label, pattern in keywords:
        if re.search(pattern, text_lower):
            found.append(label)

    return found if found else ['Other']


def _confidence_summary(patient):
    summary = {"high": 0, "medium": 0, "low": 0}
    for fields in patient.extractions.values():
        for fr in fields.values():
            if fr.confidence in summary:  # skip "none" (null/absent fields)
                summary[fr.confidence] += 1
    return summary


if __name__ == '__main__':
    import sys
    port = 5000
    if '--port' in sys.argv:
        port = int(sys.argv[sys.argv.index('--port') + 1])
    app.run(debug=True, port=port, threaded=True)
