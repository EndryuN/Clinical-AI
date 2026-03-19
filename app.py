# app.py
import os
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, send_file, stream_with_context
from models import ExtractionSession, PatientBlock, FieldResult
from parser.docx_parser import parse_docx, get_raw_text
from extractor.llm_client import check_ollama, generate
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
    ollama_ok = check_ollama()
    return render_template('index.html',
                           session_active=(session.status == 'complete'),
                           ollama_ok=ollama_ok)


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if not file.filename.endswith('.docx'):
        return jsonify({"error": "Only .docx files are supported"}), 400

    # Save file
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(file_path)

    # Parse and detect patients
    session.file_name = file.filename
    session.upload_time = datetime.now().isoformat()
    session.status = 'parsing'

    try:
        patients = parse_docx(file_path)
        session.patients = patients
        session.status = 'parsed'
        session.progress['total'] = len(patients)

        log_event('upload', file_name=file.filename, patients_detected=len(patients))

        return jsonify({
            "status": "ok",
            "patients_detected": len(patients),
            "patient_list": [
                {"id": p.id, "initials": p.initials, "nhs_number": p.nhs_number}
                for p in patients
            ]
        })
    except Exception as e:
        session.status = 'idle'
        return jsonify({"error": str(e)}), 500


@app.route('/extract', methods=['POST'])
def extract():
    if session.status not in ('parsed', 'complete'):
        return jsonify({"error": "No document uploaded or already extracting"}), 400

    session.status = 'extracting'

    # Run extraction in background thread
    thread = threading.Thread(target=_run_extraction)
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})


def _run_extraction():
    groups = get_groups()
    completed_patients = []

    for i, patient in enumerate(session.patients):
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
            key: {"value": fr.value, "confidence": fr.confidence, "edited": fr.edited}
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
            treatments[treat] = treatments.get(treat, 0) + 1

        for fields in p.extractions.values():
            for fr in fields.values():
                confidence[fr.confidence] += 1

    return jsonify({
        "cancer_types": cancer_types,
        "treatments": treatments,
        "confidence": confidence
    })


@app.route('/analytics-page')
def analytics_page():
    return render_template('analytics.html', session_active=(session.status == 'complete'))


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
    # Derive from biopsy result or default to "Colorectal" for this dataset
    biopsy = _get_field_value(patient, "Histology", "biopsy_result")
    if biopsy and "adenocarcinoma" in biopsy.lower():
        return "Colorectal"
    return "Unknown"


def _confidence_summary(patient):
    summary = {"high": 0, "medium": 0, "low": 0}
    for fields in patient.extractions.values():
        for fr in fields.values():
            summary[fr.confidence] += 1
    return summary


if __name__ == '__main__':
    import sys
    port = 5000
    if '--port' in sys.argv:
        port = int(sys.argv[sys.argv.index('--port') + 1])
    app.run(debug=True, port=port, threaded=True)
