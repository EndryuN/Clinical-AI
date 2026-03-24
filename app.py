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
from extractor.llm_client import (check_ollama, generate, get_backend, set_backend,
    check_ollama_available, check_claude_available, list_ollama_models, get_ollama_model, set_ollama_model, SUGGESTED_MODELS)
from extractor.prompt_builder import build_prompt, build_all_prompts
from extractor.clinical_context import get_context_for_group
from extractor.response_parser import parse_llm_response
from extractor.regex_extractor import regex_extract
from extractor.preview_renderer import render_patient_preview
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
                           session_active=bool(session.patients),
                           current_backend=get_backend(),
                           ollama_available=check_ollama_available(),
                           claude_available=check_claude_available(),
                           ollama_models=list_ollama_models(),
                           suggested_models=SUGGESTED_MODELS,
                           current_ollama_model=get_ollama_model())


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

            # Render patient preview images (non-fatal if Pillow unavailable)
            # log_event is already used throughout app.py with signature (event_name, **kwargs)
            try:
                ts = safe_name.split('_')[0]
                preview_dir = os.path.join(app.static_folder, 'previews', ts)
                os.makedirs(preview_dir, exist_ok=True)
                for p in patients:
                    render_patient_preview(p, preview_dir)
            except Exception as preview_err:
                log_event('preview_render_error', error=str(preview_err))

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

    # Load Metadata sheet if present (written by new exporter)
    meta_lookup = {}
    if "Metadata" in wb.sheetnames:
        ws_meta = wb["Metadata"]
        # Row 1 might be SOURCE_FILE
        if ws_meta.cell(row=1, column=1).value == "SOURCE_FILE":
            session.file_name = ws_meta.cell(row=1, column=2).value or ""
        
        # Data starts from row 3 if Row 1 is SOURCE_FILE, else row 2
        start_row = 3 if ws_meta.cell(row=1, column=1).value == "SOURCE_FILE" else 2
        for row in ws_meta.iter_rows(min_row=start_row, values_only=True):
            pid, fkey, conf, reason, *extra = row
            source_cell = None
            source_snippet = None
            if len(extra) >= 2:
                source_cell_json, source_snippet = extra[0:2]
                if source_cell_json:
                    try:
                        source_cell = json.loads(source_cell_json)
                    except:
                        pass
            
            if pid and fkey:
                meta_lookup[(str(pid), str(fkey))] = {
                    "confidence": conf or 'high',
                    "reason": reason or '',
                    "source_cell": source_cell,
                    "source_snippet": source_snippet
                }

    ws = wb.active

    patients = []
    for row_idx in range(2, ws.max_row + 1):
        # Check if row is a real patient (must have MRN col 3 or NHS number col 4)
        mrn_val = ws.cell(row=row_idx, column=3).value
        nhs_val = ws.cell(row=row_idx, column=4).value
        if not mrn_val and not nhs_val:
            continue

        # Determine patient_id early (needed for meta_lookup)
        mrn_col = next((f['excel_column'] for f in all_fields if f['key'] == 'mrn'), None)
        mrn_cell_val = ws.cell(row=row_idx, column=mrn_col).value if mrn_col else None
        patient_id = str(mrn_cell_val).strip() if mrn_cell_val else f"patient_{row_idx - 1:03d}"

        # Build extractions from Excel data
        extractions = {}
        for group in groups:
            group_fields = {}
            for field in group['fields']:
                col = field['excel_column']
                cell_value = ws.cell(row=row_idx, column=col).value
                if cell_value is not None:
                    value = str(cell_value).strip()
                    meta = meta_lookup.get((patient_id, field['key']), {})
                    cb = meta.get('confidence_basis') or meta.get('confidence', 'structured_verbatim')
                    # Map legacy confidence string to basis if needed
                    if cb in ('high', 'medium', 'low', 'none'):
                        cb = {'high': 'structured_verbatim', 'medium': 'freeform_verbatim',
                              'low': 'freeform_inferred', 'none': 'absent'}[cb]
                    group_fields[field['key']] = FieldResult(
                        value=value,
                        confidence_basis=cb,
                        reason=meta.get('reason', ''),
                        source_cell=meta.get('source_cell'),
                        source_snippet=meta.get('source_snippet')
                    )
                else:
                    group_fields[field['key']] = FieldResult(value=None, confidence_basis='absent')
            extractions[group['name']] = group_fields

        # Get patient identifiers from Demographics fields
        initials = ""
        nhs_number = ""

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
    concurrency = int(data.get('concurrency', 1))

    session.status = 'extracting'
    session.stop_requested = False
    session.concurrency = concurrency

    # Run extraction in background thread
    thread = threading.Thread(target=_run_extraction, args=(patient_limit, concurrency))
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})


@app.route('/stop', methods=['POST'])
def stop_extraction():
    """Request to stop the background extraction thread."""
    session.stop_requested = True
    return jsonify({"status": "stop_requested"})


def _run_extraction(patient_limit=None, concurrency=1):
    import time
    from concurrent.futures import ThreadPoolExecutor

    groups = get_groups()
    llm_groups = [g for g in groups if g.get('llm_required', False)]
    patients_to_process = session.patients[:patient_limit] if patient_limit else session.patients

    if not patients_to_process:
        session.status = 'complete'
        session.progress['phase'] = 'complete'
        return

    session.progress['total'] = len(patients_to_process)
    session.progress['phase'] = 'llm'
    session.progress['regex_complete'] = 0
    session.progress['llm_complete'] = 0
    session.progress['llm_queue_size'] = len(patients_to_process)
    session.progress['current_patient'] = 0
    session.progress['patient_times'] = []
    session.progress['average_seconds'] = 0
    session.progress['active_patients'] = {}
    session.progress['completed_patients'] = []
    session.progress['start_time'] = time.time()

    _counter_lock = threading.Lock()
    llm_semaphore = threading.Semaphore(concurrency)

    def process_patient(patient):
        if session.stop_requested:
            return

        # --- Regex (inline, fast) ---
        for group in groups:
            results = regex_extract(patient.raw_text, group['name'], group['fields'], patient.raw_cells)
            if group.get('llm_required', False):
                for key, fr in results.items():
                    if fr.value is None:
                        results[key] = FieldResult(value=None, confidence_basis='absent')
            patient.extractions[group['name']] = results
        with _counter_lock:
            session.progress['regex_complete'] += 1

        if session.stop_requested:
            return

        # --- LLM (serial via semaphore, groups run sequentially per patient) ---
        patient_llm_groups = [
            g for g in llm_groups
            if any(fr.value is None for fr in patient.extractions.get(g['name'], {}).values())
        ]

        if not patient_llm_groups:
            conf = _confidence_summary(patient)
            with _counter_lock:
                session.progress['llm_complete'] += 1
                session.progress['current_patient'] = session.progress['llm_complete']
                session.progress['completed_patients'].append({
                    "id": patient.id, "initials": patient.initials,
                    "confidence_summary": conf, "seconds": 0,
                })
            return

        start_time = time.time()
        session.progress['active_patients'][patient.id] = {
            "initials": patient.initials,
            "group": patient_llm_groups[0]['name'],
            "start": start_time,
            "status": "queued",
            "has_context": bool(get_context_for_group(patient_llm_groups[0]['name'])),
            "groups_done": 0,
            "groups_total": len(patient_llm_groups),
        }

        for group in patient_llm_groups:
            if session.stop_requested:
                break
            session.progress['active_patients'][patient.id].update({
                'group': group['name'],
                'has_context': bool(get_context_for_group(group['name'])),
                'status': 'queued',
            })
            with llm_semaphore:
                if session.stop_requested:
                    break
                session.progress['active_patients'][patient.id]['status'] = 'running'
                try:
                    system_prompt, user_prompt = build_prompt(patient.raw_text, group)
                    raw_response = generate(user_prompt, system_prompt)
                    llm_results = parse_llm_response(raw_response, group)
                    for key, llm_fr in llm_results.items():
                        current = patient.extractions[group['name']].get(key)
                        if current and current.value is None and llm_fr.value is not None:
                            _resolve_source_cell(patient, llm_fr)
                            llm_fr.reason = f"[LLM] {llm_fr.reason}"
                            patient.extractions[group['name']][key] = llm_fr
                except Exception as e:
                    log_event('llm_extraction_error', patient_id=patient.id, group=group['name'], error=str(e))
            session.progress['active_patients'][patient.id]['groups_done'] += 1

        session.progress['active_patients'].pop(patient.id, None)

        elapsed = round(time.time() - start_time, 1)
        conf = _confidence_summary(patient)
        with _counter_lock:
            session.progress['llm_complete'] += 1
            session.progress['current_patient'] = session.progress['llm_complete']
            session.progress['patient_times'].append(elapsed)
            session.progress['average_seconds'] = round(
                sum(session.progress['patient_times']) / len(session.progress['patient_times']), 1
            )
            session.progress['completed_patients'].append({
                "id": patient.id, "initials": patient.initials,
                "confidence_summary": conf, "seconds": elapsed,
            })

    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, 3))) as ex:
        list(ex.map(process_patient, patients_to_process))

    session.status = 'complete' if not session.stop_requested else 'stopped'
    session.progress['phase'] = 'complete'


@app.route('/progress')
def progress():
    def event_stream():
        import time
        while session.status == 'extracting' or session.status == 'complete' or session.status == 'stopped':
            # Send update if patient changed, group changed, or every 2 seconds for timer
            event_data = {
                "current_patient": session.progress['current_patient'],
                "total": session.progress['total'],
                "phase": session.progress.get('phase', 'idle'),
                "regex_complete": session.progress.get('regex_complete', 0),
                "llm_complete": session.progress.get('llm_complete', 0),
                "llm_queue_size": session.progress.get('llm_queue_size', 0),
                "active_patients": session.progress.get('active_patients', {}),
                "completed_patients": session.progress.get('completed_patients', []),
                "average_seconds": round(session.progress.get('average_seconds', 0), 1),
                "start_time": session.progress.get('start_time', 0),
                "status": session.status
            }
            yield f"data: {json.dumps(event_data)}\n\n"
            
            if session.status in ('complete', 'stopped'):
                break
                
            time.sleep(2)

    return Response(stream_with_context(event_stream()), mimetype='text/event-stream')


@app.route('/process')
def process_page():
    return render_template('process.html', session_active=bool(session.patients))


@app.route('/patients')
def get_patients():
    cancer_type = request.args.get('cancer_type', '')
    search = request.args.get('search', '').lower()

    # During extraction only expose patients whose LLM is done
    if session.status == 'extracting':
        completed_ids = {p['id'] for p in session.progress.get('completed_patients', [])}
        source = [p for p in session.patients if p.id in completed_ids]
    else:
        source = session.patients

    result = []
    for p in source:
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
            key: {
                "value": fr.value,
                "confidence": fr.confidence,
                "reason": fr.reason,
                "edited": fr.edited,
                "source_cell": fr.source_cell,
                "source_snippet": fr.source_snippet,
            }
            for key, fr in fields.items()
        }

    return jsonify({
        "id": patient.id,
        "initials": patient.initials,
        "nhs_number": patient.nhs_number,
        "raw_text": patient.raw_text,
        "raw_cells": patient.raw_cells,
        "extractions": extractions
    })


@app.route('/patient/<patient_id>/preview')
def patient_preview(patient_id):
    """Return rendered image URL and cell coordinate map for the patient."""
    patient = next((p for p in session.patients if p.id == patient_id), None)
    if not patient:
        return jsonify({"error": "not found"}), 404
    if not session.file_name:
        return jsonify({"error": "no file"}), 404
    ts = session.file_name.split('_')[0]
    json_path = os.path.join(app.static_folder, 'previews', ts, f'{patient.id}.json')
    if not os.path.exists(json_path):
        return jsonify({"error": "preview not available"}), 404
    with open(json_path) as f:
        coords = json.load(f)
    return jsonify({
        "image_url": f"/static/previews/{ts}/{patient.id}.png",
        "coords": coords,
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
        groups = get_groups()
        for group in groups:
            if group['name'] in target_groups:
                try:
                    # Phase 1: regex
                    results = regex_extract(patient.raw_text, group['name'], group['fields'], patient.raw_cells)
                    # Phase 2: LLM for gaps in LLM groups
                    if group.get('llm_required', False):
                        gaps = sum(1 for fr in results.values() if fr.value is None)
                        if gaps > 0:
                            system_prompt, user_prompt = build_prompt(patient.raw_text, group)
                            raw_response = generate(user_prompt, system_prompt)
                            llm_results = parse_llm_response(raw_response, group)
                            for key, llm_fr in llm_results.items():
                                if key in results and results[key].value is None and llm_fr.value is not None:
                                    _resolve_source_cell(patient, llm_fr)
                                    llm_fr.reason = f"[LLM] {llm_fr.reason}"
                                    results[key] = llm_fr
                    patient.extractions[group['name']] = results
                except Exception as e:
                    log_event('re_extract_error', group=group['name'], error=str(e))
                    pass  # LLM call failed — regex results preserved for non-llm_required groups

    thread = threading.Thread(target=_do_re_extract)
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})


@app.route('/status')
def status():
    return jsonify({
        "status": session.status,
        "current": session.progress['current_patient'],
        "total": session.progress['total'],
        "phase": session.progress.get('phase', 'idle'),
    })


@app.route('/export')
def export():
    if session.status not in ('complete', 'stopped') or not session.patients:
        return jsonify({"error": "No data to export"}), 400

    output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'export.xlsx')
    write_excel(session.patients, output_path, source_name=session.file_name)

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
    return render_template('analytics.html', session_active=bool(session.patients))


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
    return render_template('review.html', session_active=bool(session.patients))


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
    """Get or set the LLM backend and model."""
    if request.method == 'POST':
        data = request.json or {}
        choice = data.get('backend', 'ollama')
        set_backend(choice)
        if 'ollama_model' in data:
            set_ollama_model(data['ollama_model'])
        return jsonify({"status": "ok", "backend": get_backend(), "ollama_model": get_ollama_model()})
    return jsonify({
        "backend": get_backend(),
        "ollama_available": check_ollama_available(),
        "claude_available": check_claude_available(),
        "ollama_model": get_ollama_model(),
        "ollama_models": list_ollama_models()
    })


@app.route('/link-source', methods=['POST'])
def link_source():
    """Upload a .docx to link previews/cells to an existing session (e.g. after Excel import)."""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    if not session.patients:
        return jsonify({"error": "No active session to link to"}), 400

    file = request.files['file']
    if not file.filename.lower().endswith('.docx'):
        return jsonify({"error": "Only .docx files can be linked as source"}), 400

    # Save with timestamp
    import time
    safe_name = f"{int(time.time())}_{file.filename}"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
    file.save(file_path)

    try:
        new_patients = parse_docx(file_path)
        linked_count = 0

        # Match by ID (Hospital Number) or NHS Number or Initials
        for p_existing in session.patients:
            match = None
            # 1. Try ID (Hospital Number)
            match = next((np for np in new_patients if np.id == p_existing.id), None)
            
            # 2. Try NHS Number
            if not match and p_existing.nhs_number:
                match = next((np for np in new_patients if np.nhs_number == p_existing.nhs_number), None)
            
            # 3. Try Initials (less reliable, but better than nothing if 1 & 2 fail)
            if not match and p_existing.initials:
                # Only match by initials if there's exactly one candidate in the new file
                candidates = [np for np in new_patients if np.initials == p_existing.initials]
                if len(candidates) == 1:
                    match = candidates[0]

            if match:
                p_existing.raw_cells = match.raw_cells
                p_existing.raw_text = match.raw_text
                linked_count += 1

        # Render previews for all patients (even if some didn't match, we try)
        ts = safe_name.split('_')[0]
        preview_dir = os.path.join(app.static_folder, 'previews', ts)
        os.makedirs(preview_dir, exist_ok=True)
        for p in session.patients:
            if p.raw_cells: # Only render if we have cells
                render_patient_preview(p, preview_dir)

        session.file_name = safe_name
        log_event('link_source', file_name=file.filename, matched=linked_count)

        return jsonify({
            "status": "ok",
            "matched": linked_count,
            "total": len(session.patients)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Helper functions
def _resolve_source_cell(patient, fr):
    """Search patient.raw_cells for a cell containing fr.value and populate
    fr.source_cell/source_snippet.

    Note: uses substring matching on the normalised value — this is a best-effort
    approximation for LLM-extracted fields. For regex-extracted fields, source_cell
    is already set precisely by regex_extractor.py.
    """
    if not fr.value or not patient.raw_cells:
        return
    for cell in patient.raw_cells:
        if fr.value in cell["text"]:
            fr.source_cell = {"row": cell["row"], "col": cell["col"]}
            if fr.source_snippet is None:     # don't overwrite LLM-provided annotation marker
                fr.source_snippet = fr.value  # approximate — raw LLM token not available
            return


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
    m = re.search(r'Diagnosis:\s*([A-Za-z][A-Za-z\s\-]+?)(?:\s*[,()\n]|$)', patient.raw_text)
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
