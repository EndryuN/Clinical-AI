// static/js/app.js

// ===== Upload Zone =====
document.addEventListener('DOMContentLoaded', function() {
    const zone = document.getElementById('upload-zone');
    const input = document.getElementById('file-input');

    if (!zone || !input) return;

    zone.addEventListener('click', () => input.click());
    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('border-primary');
    });
    zone.addEventListener('dragleave', () => {
        zone.classList.remove('border-primary');
    });
    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('border-primary');
        if (e.dataTransfer.files.length) {
            uploadFile(e.dataTransfer.files[0]);
        }
    });
    input.addEventListener('change', () => {
        if (input.files.length) {
            uploadFile(input.files[0]);
        }
    });
});

function uploadFile(file) {
    if (!file.name.endsWith('.docx') && !file.name.endsWith('.xlsx')) {
        showUploadError('Only .docx and .xlsx files are supported.');
        return;
    }

    // Show spinner, hide any previous error
    const spinner = document.getElementById('upload-spinner');
    const errorDiv = document.getElementById('upload-error');
    if (spinner) spinner.classList.remove('d-none');
    if (errorDiv) errorDiv.classList.add('d-none');

    const formData = new FormData();
    formData.append('file', file);

    fetch('/upload', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            if (spinner) spinner.classList.add('d-none');
            if (data.error) {
                showUploadError(data.error);
                return;
            }
            // Store data and redirect
            sessionStorage.setItem('upload_result', JSON.stringify(data));
            sessionStorage.setItem('file_name', file.name);
            if (data.imported) {
                // Excel import — skip extraction, go straight to review
                window.location.href = '/review';
            } else {
                // DOCX upload — go to process page for extraction
                window.location.href = '/process';
            }
        })
        .catch(err => {
            if (spinner) spinner.classList.add('d-none');
            showUploadError('Upload failed: ' + err);
        });
}

function showUploadError(msg) {
    const errorDiv = document.getElementById('upload-error');
    if (errorDiv) {
        errorDiv.textContent = msg;
        errorDiv.classList.remove('d-none');
    } else {
        alert(msg);
    }
}

// ===== Process Page =====
function initProcessPage() {
    // Show current model in both pre-extraction and active extraction sections
    fetch('/backend')
        .then(r => r.json())
        .then(b => {
            const modelText = b.backend === 'claude'
                ? 'Claude API'
                : `${b.ollama_model} (Ollama)`;
            const el = document.getElementById('current-model');
            if (el) el.textContent = modelText;
            const activeEl = document.getElementById('active-model');
            if (activeEl) activeEl.textContent = modelText;
        })
        .catch(() => {});

    // If extraction is already running (user navigated back), resume live view
    fetch('/status')
        .then(r => r.json())
        .then(status => {
            if (status.status === 'extracting') {
                const parseResult = document.getElementById('parse-result');
                const progressSection = document.getElementById('progress-section');
                if (parseResult) parseResult.classList.add('d-none');
                if (progressSection) progressSection.classList.remove('d-none');
                listenProgress();
                return;
            }
            // Normal init from sessionStorage
            const data = JSON.parse(sessionStorage.getItem('upload_result') || 'null');
            const fileName = sessionStorage.getItem('file_name') || 'Unknown file';
            const fileNameEl = document.getElementById('file-name');
            const patientCountEl = document.getElementById('patient-count');
            if (fileNameEl) fileNameEl.textContent = fileName;
            if (patientCountEl) patientCountEl.textContent = data ? data.patients_detected : '?';
        })
        .catch(() => {
            // Fallback to sessionStorage if /status unreachable
            const data = JSON.parse(sessionStorage.getItem('upload_result') || 'null');
            const fileName = sessionStorage.getItem('file_name') || 'Unknown file';
            const fileNameEl = document.getElementById('file-name');
            const patientCountEl = document.getElementById('patient-count');
            if (fileNameEl) fileNameEl.textContent = fileName;
            if (patientCountEl) patientCountEl.textContent = data ? data.patients_detected : '?';
        });
}

function startExtraction() {
    const parseResult = document.getElementById('parse-result');
    if (parseResult) parseResult.classList.add('d-none');

    const progressSection = document.getElementById('progress-section');
    if (progressSection) progressSection.classList.remove('d-none');

    const limitInput = document.getElementById('patient-limit');
    const limit = limitInput && limitInput.value ? parseInt(limitInput.value) : null;
    const concurrencyInput = document.getElementById('concurrency');
    const concurrency = concurrencyInput && concurrencyInput.value ? parseInt(concurrencyInput.value) : 1;
    
    const body = JSON.stringify({limit: limit, concurrency: concurrency});

    fetch('/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body
    })
        .then(r => r.json())
        .then(() => listenProgress())
        .catch(err => {
            alert('Failed to start extraction: ' + err);
            if (startBtn) startBtn.classList.remove('d-none');
            if (progressSection) progressSection.classList.add('d-none');
        });
}

function stopExtraction() {
    if (!confirm('Stop extraction? Progress so far will be saved.')) return;
    fetch('/stop', { method: 'POST' });
    // Show immediate visual feedback — server will confirm via SSE
    const stopBtn = document.querySelector('[onclick="stopExtraction()"]');
    if (stopBtn) {
        stopBtn.textContent = 'Stopping…';
        stopBtn.disabled = true;
    }
    const regexBar = document.getElementById('progress-bar-regex');
    if (regexBar) regexBar.style.background = '#dc3545';
}

function listenProgress() {
    const source = new EventSource('/progress');
    let timerInterval = null;
    let extractionStartTime = null;

    function startTimer() {
        if (timerInterval) return;
        timerInterval = setInterval(() => {
            if (!extractionStartTime) return;
            const elapsed = Math.floor((Date.now() / 1000) - extractionStartTime);
            const mins = Math.floor(elapsed / 60).toString().padStart(2, '0');
            const secs = (elapsed % 60).toString().padStart(2, '0');
            const timerEl = document.getElementById('current-timer');
            if (timerEl) timerEl.textContent = `${mins}:${secs}`;
        }, 1000);
    }

    source.onmessage = function(event) {
        const data = JSON.parse(event.data);

        // Capture start time from first message
        if (data.start_time && !extractionStartTime) {
            extractionStartTime = data.start_time;
            startTimer();
        }

        if (data.status === 'complete' || data.status === 'stopped') {
            source.close();
            if (timerInterval) clearInterval(timerInterval);
            const progressSection = document.getElementById('progress-section');
            const completeSection = document.getElementById('complete-section');
            const completeSummary = document.getElementById('complete-summary');

            if (progressSection) progressSection.classList.add('d-none');
            if (completeSection) completeSection.classList.remove('d-none');
            if (completeSummary) {
                const statusText = data.status === 'stopped' ? 'Extraction stopped.' : 'Extraction complete.';
                const throughput = data.throughput_seconds || data.average_seconds || 0;
                completeSummary.textContent = `${statusText} ${data.current_patient} / ${data.total} patients processed. ${throughput}s avg per patient.`;
            }
            return;
        }

        const total = data.total || 0;
        const donePatientsCount = (data.completed_patients || []).length;
        const overallPct = total > 0 ? (donePatientsCount / total * 100).toFixed(0) : 0;

        const progressBar = document.getElementById('progress-bar');
        const progressText = document.getElementById('progress-text');
        const activePatientsList = document.getElementById('active-patients-list');
        const averageSpeedEl = document.getElementById('average-speed');

        if (progressBar) progressBar.style.width = overallPct + '%';

        if (progressText) {
            progressText.textContent = `${donePatientsCount} / ${total} patients`;
        }

        // Average speed: show throughput (wall time / completed) when multithreaded
        if (averageSpeedEl) {
            const throughput = data.throughput_seconds || 0;
            const avgLlm = data.average_seconds || 0;
            const activeCount = Object.keys(data.active_patients || {}).length;
            if (throughput > 0) {
                // Show throughput rate (accounts for parallelism)
                averageSpeedEl.textContent = `${throughput}s / patient`;
                // If running parallel, show LLM time in parentheses
                if (activeCount > 1 && avgLlm > 0 && avgLlm !== throughput) {
                    averageSpeedEl.textContent += ` (${avgLlm}s LLM)`;
                }
            } else if (avgLlm > 0) {
                averageSpeedEl.textContent = `${avgLlm}s / patient`;
            }
        }

        // Render active patient cards — each with its own group progress bar
        if (activePatientsList) {
            const active = Object.entries(data.active_patients || {});
            if (active.length === 0) {
                activePatientsList.innerHTML = '<span class="text-muted small">Waiting...</span>';
            } else {
                activePatientsList.innerHTML = active.map(([id, p]) => {
                    const isQueued = p.status === 'queued';
                    // Timer: show LLM processing time (from llm_start), not queue time
                    const timerBase = (!isQueued && p.llm_start) ? p.llm_start : p.start;
                    const elapsed = Math.floor((Date.now() - (timerBase * 1000)) / 1000);
                    const mins = Math.floor(elapsed / 60).toString().padStart(2, '0');
                    const secs = (elapsed % 60).toString().padStart(2, '0');
                    const accentColor = isQueued ? '#4b5563' : '#0d6efd';
                    const timerColor = isQueued ? '#6b7280' : '#f59e0b';
                    const groupLabel = isQueued ? `Queued` : p.group || 'Starting...';
                    const contextBadge = (!isQueued && p.has_context)
                        ? `<span style="font-size:9px; background:#1e3a5f; color:#60a5fa; border:1px solid #2563eb; border-radius:3px; padding:1px 4px; margin-left:5px; vertical-align:middle;">G049</span>`
                        : '';
                    const groupsDone = p.groups_done || 0;
                    const groupsTotal = p.groups_total || 1;
                    const groupPct = Math.round(groupsDone / groupsTotal * 100);
                    const miniBarColor = isQueued ? '#374151' : '#2563eb';
                    const statusLabel = isQueued
                        ? `<span style="font-size:9px; color:#6b7280;">QUEUED</span>`
                        : `<span style="font-size:9px; color:#60a5fa;">${groupsDone}/${groupsTotal} groups</span>`;
                    return `<div style="background:#111827; border:1px solid ${accentColor}; border-radius:6px; padding:8px 12px; min-width:160px; opacity:${isQueued ? '0.7' : '1'};">` +
                           `<div style="font-size:12px; font-weight:700; color:#f0f0f0; letter-spacing:0.5px;">${p.initials || 'Patient'}</div>` +
                           `<div style="font-size:10px; color:#9ca3af; margin-top:2px;">${groupLabel}${contextBadge}</div>` +
                           `<div style="display:flex; justify-content:space-between; align-items:baseline; margin-top:4px;">` +
                           `<span style="font-size:14px; font-weight:700; color:${timerColor}; font-family:monospace;">${mins}:${secs}</span>` +
                           `${statusLabel}` +
                           `</div>` +
                           `<div style="margin-top:6px; background:#1f2937; border-radius:3px; height:3px; overflow:hidden;">` +
                           `<div style="width:${groupPct}%; height:100%; background:${miniBarColor}; transition:width 0.5s ease;"></div>` +
                           `</div>` +
                           `</div>`;
                }).join('');
            }
        }

        // Render completed patients log
        if (data.completed_patients && data.completed_patients.length > 0) {
            const log = document.getElementById('completed-log');
            if (log) {
                log.innerHTML = data.completed_patients.slice().reverse().map(p => {
                    const c = p.confidence_summary || {};
                    const llmTime = p.llm_seconds || p.seconds || 0;
                    const timeStr = llmTime ? `(${llmTime}s)` : '';
                    return `<div class="text-muted py-1 d-flex justify-content-between">` +
                        `<span>&#x2713; ${p.initials || p.id} &middot; ` +
                        `<span class="text-success">${c.high || 0} high</span> &middot; ` +
                        `<span style="color:#f97316;">${c.medium || 0} med</span> &middot; ` +
                        `<span style="color:#ff6b6b;">${c.low || 0} low</span></span>` +
                        `<span class="ms-2">${timeStr}</span></div>`;
                }).join('');
                log.scrollTop = 0;
            }
        }
    };

    source.onerror = function() {
        // SSE connection lost (e.g. user navigated away and came back).
        // Close silently — initProcessPage() will reconnect on next visit.
        source.close();
    };
}

// Auto-init process page
if (document.getElementById('parse-result')) {
    initProcessPage();
}

// ===== Review Page Functions =====
let currentPatientId = null;
let currentGroup = null;
let schemaGroups = {};  // {groupName: {color: "#...", fields: [...]}}

// Load schema colours on page load
fetch('/schema').then(r => r.json()).then(groups => {
    groups.forEach(g => { schemaGroups[g.name] = {color: g.color, fields: g.fields}; });
}).catch(() => {});
let confidenceFilter = '';
let allPatientExtractions = {};

// Maps LLM source_snippet annotation markers to MDT table row indices
const MARKER_TO_ROWS = {
    '(a)': [1], '(b)': [1], '(c)': [1], '(d)': [1], '(e)': [1],
    '(f)': [4, 5],
    '(g)': [2, 3],
    '(h)': [6, 7],
    '(i)': [0],
};

function loadPatients(filters) {
    filters = filters || {};
    let url = '/patients?';
    if (filters.cancer_type) url += `cancer_type=${encodeURIComponent(filters.cancer_type)}&`;
    if (filters.search) url += `search=${encodeURIComponent(filters.search)}&`;

    fetch(url)
        .then(r => r.json())
        .then(data => {
            renderPatientList(data.patients || []);
            // Populate cancer type dropdown dynamically (only if not filtered)
            if (!filters.cancer_type) {
                const types = new Set();
                (data.patients || []).forEach(p => { if (p.cancer_type) types.add(p.cancer_type); });
                const select = document.getElementById('cancer-type-filter');
                if (select) {
                    const current = select.value;
                    select.innerHTML = '<option value="">All Cancer Types</option>';
                    [...types].sort().forEach(t => {
                        const opt = document.createElement('option');
                        opt.value = t;
                        opt.textContent = t;
                        if (t === current) opt.selected = true;
                        select.appendChild(opt);
                    });
                }
            }
        });
}

function renderPatientList(patients) {
    const list = document.getElementById('patient-list');
    if (!list) return;

    if (patients.length === 0) {
        list.innerHTML = '<p class="text-muted small text-center mt-3">No patients found</p>';
        return;
    }

    list.innerHTML = patients.map(p => {
        const isActive = p.id === currentPatientId;
        const c = p.confidence_summary || {};
        return `
        <div class="patient-item p-2 mb-1 ${isActive ? 'active border-start border-primary border-3' : ''}"
             onclick="selectPatient('${p.id}')" style="cursor:pointer">
            <div class="fw-bold small">${p.initials || 'Unknown'} &mdash; ${p.gender || 'N/A'}</div>
            <div class="text-muted" style="font-size:11px">${p.nhs_number || ''} &middot; ${p.cancer_type || ''}</div>
            <div class="mt-1">
                <span class="badge bg-success" style="font-size:10px">${c.high || 0} high</span>
                <span class="badge" style="font-size:10px;background:#f97316;">${c.medium || 0} med</span>
                <span class="badge bg-danger" style="font-size:10px">${c.low || 0} low</span>
            </div>
        </div>`;
    }).join('');
}

function selectPatient(patientId) {
    currentPatientId = patientId;

    fetch(`/patients/${patientId}`)
        .then(r => r.json())
        .then(data => {
            // Load rendered preview image and coord map
            window._previewCoords = null;
            const previewImg = document.getElementById('preview-img');
            const previewPlaceholder = document.getElementById('preview-placeholder');
            const previewCanvas = document.getElementById('preview-canvas');
            
            fetch(`/patient/${patientId}/preview`)
                .then(r => r.json())
                .then(preview => {
                    if (preview.image_url && previewImg) {
                        window._previewCoords = preview.coords;
                        previewImg.onload = function() {
                            if (previewCanvas && previewImg.clientWidth > 0) {
                                previewCanvas.width = previewImg.clientWidth;
                                previewCanvas.height = previewImg.clientHeight;
                            }
                        };
                        previewImg.onerror = function() {
                            previewImg.style.display = 'none';
                            if (previewPlaceholder) previewPlaceholder.style.display = '';
                        };
                        previewImg.src = preview.image_url;
                        previewImg.style.display = 'block';
                        if (previewPlaceholder) previewPlaceholder.style.display = 'none';
                        initCoverageToggle(preview.coverage_map, preview.coverage_pct, preview.coords);
                    } else {
                        if (previewImg) previewImg.style.display = 'none';
                        if (previewPlaceholder) previewPlaceholder.style.display = 'block';
                        initCoverageToggle(null, null, null);
                    }
                })
                .catch(() => {
                    if (previewImg) previewImg.style.display = 'none';
                    if (previewPlaceholder) previewPlaceholder.style.display = 'block';
                    initCoverageToggle(null, null, null);
                });

            // Store extractions for re-rendering on filter change
            allPatientExtractions = data.extractions || {};
            // ... (rest of selectPatient)

            // Use schema order, but push completely empty tabs to the end
            const schemaOrder = Object.keys(schemaGroups);
            const allGroups = schemaOrder.length > 0
                ? schemaOrder.filter(g => g in allPatientExtractions)
                : Object.keys(allPatientExtractions);

            const hasData = g => {
                const fields = allPatientExtractions[g];
                if (!fields) return false;
                return Object.values(fields).some(fr => fr.value !== null && fr.value !== undefined && fr.value !== '');
            };
            const groups = [
                ...allGroups.filter(g => hasData(g)),
                ...allGroups.filter(g => !hasData(g))
            ];

            if (!currentGroup || !groups.includes(currentGroup)) {
                currentGroup = groups[0] || null;
            }

            renderGroupTabs(groups);
            if (currentGroup && allPatientExtractions[currentGroup]) {
                renderFieldTable(allPatientExtractions[currentGroup], currentGroup);
            }

            // Refresh patient list to highlight active
            loadPatients();
        })
        .catch(err => console.error('Failed to load patient:', err));
}

function highlightSource(fr) {
    const canvas = document.getElementById('preview-canvas');
    const img = document.getElementById('preview-img');
    const warning = document.getElementById('source-warning');

    if (warning) warning.classList.add('d-none');
    if (!canvas || !img || img.naturalWidth === 0) return;

    // Sync canvas pixel dimensions to current rendered image size
    canvas.width = img.clientWidth;
    canvas.height = img.clientHeight;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!fr || fr.value === null || fr.value === undefined) return;

    let rows = MARKER_TO_ROWS[fr.source_snippet];
    let cellsToHighlight = [];

    if (rows) {
        for (const row of rows) {
            for (let col = 0; col < 3; col++) {
                cellsToHighlight.push({row: row, col: col});
            }
        }
    } else if (fr.source_cell) {
        cellsToHighlight.push(fr.source_cell);
    }

    if (cellsToHighlight.length === 0) {
        // No annotation marker and no source cell — field came from LLM without a location
        if (fr.value !== null && fr.value !== '' && warning) warning.classList.remove('d-none');
        return;
    }

    if (!window._previewCoords) {
        // No preview available for this patient (e.g. Excel import where original preview is missing)
        return;
    }

    const scaleX = img.clientWidth / img.naturalWidth;
    const scaleY = img.clientHeight / img.naturalHeight;

    const conf = fr.confidence || 'low';
    const colours = {
        high:   { fill: 'rgba(25,135,84,0.25)',  stroke: '#198754' },
        medium: { fill: 'rgba(249,115,22,0.20)',  stroke: '#f97316' },
        low:    { fill: 'rgba(220,53,69,0.25)',   stroke: '#dc3545' },
    };
    const colour = colours[conf] || colours.low;

    ctx.fillStyle = colour.fill;
    ctx.strokeStyle = colour.stroke;
    ctx.lineWidth = 2;

    for (const cellPos of cellsToHighlight) {
        const cell = window._previewCoords[`${cellPos.row},${cellPos.col}`];
        if (!cell) continue;
        const x = cell.x * scaleX;
        const y = cell.y * scaleY;
        const w = cell.w * scaleX;
        const h = cell.h * scaleY;
        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x, y, w, h);
    }
}

function renderGroupTabs(groups) {
    const tabs = document.getElementById('group-tabs');
    if (!tabs) return;

    const hasData = g => {
        const fields = allPatientExtractions[g];
        if (!fields) return false;
        return Object.values(fields).some(fr => fr.value !== null && fr.value !== undefined && fr.value !== '');
    };

    let dividerInserted = false;
    let html = '';

    for (const g of groups) {
        const groupHasData = hasData(g);

        // Insert divider before the first empty tab
        if (!groupHasData && !dividerInserted) {
            dividerInserted = true;
            html += `
            <li class="nav-item d-flex align-items-center" style="margin: 2px 8px;">
                <span style="color: #555; font-size: 11px; white-space: nowrap; font-style: italic;">No data &#x27A1;</span>
            </li>`;
        }

        const schema = schemaGroups[g] || {};
        const color = schema.color || '#D9D9D9';
        const isActive = g === currentGroup;
        const opacity = isActive ? '1' : groupHasData ? '0.7' : '0.35';
        const border = isActive ? 'border: 2px solid #fff;' : 'border: 1px solid rgba(255,255,255,0.2);';
        const fontWeight = isActive ? 'font-weight: 700;' : '';
        html += `
        <li class="nav-item" style="margin: 2px;">
            <a class="nav-link" href="#"
               style="background-color: ${color}; opacity: ${opacity}; color: #000; ${border} ${fontWeight}
                      border-radius: 6px; padding: 5px 12px; font-size: 12px;"
               onclick="switchGroup('${g}'); return false;">${g}</a>
        </li>`;
    }

    tabs.innerHTML = html;
}

function switchGroup(group) {
    currentGroup = group;

    // Re-render tabs: schema order, empty tabs at end
    const schemaOrder = Object.keys(schemaGroups);
    const allGroups = schemaOrder.length > 0
        ? schemaOrder.filter(g => g in allPatientExtractions)
        : Object.keys(allPatientExtractions);

    const hasData = g => {
        const fields = allPatientExtractions[g];
        if (!fields) return false;
        return Object.values(fields).some(fr => fr.value !== null && fr.value !== undefined && fr.value !== '');
    };
    const groups = [
        ...allGroups.filter(g => hasData(g)),
        ...allGroups.filter(g => !hasData(g))
    ];
    renderGroupTabs(groups);

    // Render the selected group's fields
    if (allPatientExtractions[group]) {
        renderFieldTable(allPatientExtractions[group], group);
    }
}

function renderFieldTable(fields, groupName) {
    const tbody = document.getElementById('field-table-body');
    if (!tbody) return;

    const allowedConf = confidenceFilter ? confidenceFilter.split(',') : null;

    // Show ALL fields — including empty ones so users can populate them
    const entries = Object.entries(fields)
        .filter(([key, fr]) => {
            if (!allowedConf) return true;
            // When filtering by confidence, still show empty fields (they might need populating)
            if (fr.confidence === 'none' && !fr.value) return !allowedConf;
            return allowedConf.includes(fr.confidence);
        });

    if (entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-muted text-center py-3">No fields in this category</td></tr>';
        return;
    }

    const groupColor = (schemaGroups[groupName] || {}).color || '#D9D9D9';

    tbody.innerHTML = entries.map(([key, fr]) => {
        const hasValue = fr.value !== null && fr.value !== undefined && fr.value !== '';
        const reason = (fr.reason || '').toLowerCase();
        const isInferred = hasValue && (fr.confidence === 'medium' || reason.includes('infer'));
        const isPending = !hasValue && fr.confidence === 'none' && !fr.edited;

        const confClass = !hasValue ? 'secondary' :
                          isInferred ? 'warning' :
                          fr.confidence === 'high' ? 'success' :
                          fr.confidence === 'none' ? 'secondary' : 'danger';
        const confStyle = isInferred ? 'background:#f97316!important;' : '';
        const confText = !hasValue ? (isPending ? 'PENDING' : 'EMPTY') :
                         isInferred ? 'INFERRED' :
                         fr.confidence === 'none' ? 'N/A' : (fr.confidence || 'low').toUpperCase();
        const safeValue = (fr.value || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const editedBadge = fr.edited ? '<span class="badge bg-info ms-1" style="font-size:9px">EDITED</span>' : '';
        const safeReason = (fr.reason || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const inputBorder = isInferred ? 'border-color: #f97316 !important;' : '';
        const rowBg = isInferred ? 'background-color: rgba(249,115,22,0.05);' : '';
        const frData = JSON.stringify({value: fr.value, confidence: fr.confidence, source_cell: fr.source_cell || null, source_snippet: fr.source_snippet || null});
        const safeFrData = frData.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        const reasonRow = (safeReason && confText !== 'EMPTY' && confText !== 'N/A')
            ? `<tr style="border-left: 4px solid ${groupColor}; border-top: none;">
                <td colspan="3" style="padding: 2px 10px 6px 10px; padding-top:0;">
                    <span style="font-size:11px; color:#6b7280; font-style:italic;">${safeReason}</span>
                </td>
               </tr>`
            : '';
        return `
        <tr class="${isPending ? 'pending-row' : ''}" style="border-left: 4px solid ${groupColor}; ${rowBg} cursor:pointer; border-bottom: none;"
            data-fr="${safeFrData}" onclick="highlightSource(JSON.parse(this.dataset.fr))">
            <td class="small" style="color: ${hasValue ? '#c9d1d9' : '#555'};">${key}</td>
            <td>
                <input type="text" class="form-control form-control-sm bg-dark text-light border-${confClass}"
                       value="${safeValue}" placeholder="${hasValue ? '' : 'Enter value...'}"
                       style="${inputBorder}"
                       onchange="editField('${groupName}', '${key}', this.value)">
            </td>
            <td class="text-center" style="min-width: 140px;">
                <span class="badge bg-${confClass}" style="font-size:10px; ${confStyle}">${confText}</span>
                ${editedBadge}
                ${fr.source_cell ? '<span class="source-link badge bg-light text-secondary border ms-1" data-row="' + fr.source_cell.row + '" data-col="' + fr.source_cell.col + '" style="cursor:pointer;font-size:9px" title="Click to highlight source cell">src</span>' : (hasValue ? '<span class="badge bg-light text-muted border ms-1" style="font-size:9px" title="Source cell not available">no src</span>' : '')}
            </td>
        </tr>${reasonRow}`;
    }).join('');
}

function filterConfidence(filter) {
    confidenceFilter = filter;
    if (currentGroup && allPatientExtractions[currentGroup]) {
        renderFieldTable(allPatientExtractions[currentGroup], currentGroup);
    }
}

function editField(group, field, newValue) {
    if (!currentPatientId) return;

    fetch(`/patients/${currentPatientId}/fields`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: group, field: field, value: newValue })
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'ok') {
                // Update local cache
                if (allPatientExtractions[group] && allPatientExtractions[group][field]) {
                    allPatientExtractions[group][field].value = newValue;
                    allPatientExtractions[group][field].edited = true;
                    allPatientExtractions[group][field].confidence = newValue ? 'high' : 'none';
                }
                // Re-sort tabs in case an empty tab now has data
                switchGroup(currentGroup);
            }
        })
        .catch(err => console.error('Edit failed:', err));
}

// ===== Live Review During Extraction =====
let _reviewPollTimer = null;

function _attachProgressSSE() {
    const source = new EventSource('/progress');
    let lastCompleted = 0;

    source.onmessage = function(event) {
        const d = JSON.parse(event.data);

        // Trickle patients in as each one finishes LLM
        const nowCompleted = (d.completed_patients || []).length;
        if (nowCompleted > lastCompleted) {
            lastCompleted = nowCompleted;
            loadPatients();
        }

        if (d.status === 'complete' || d.status === 'stopped') {
            source.close();
            loadPatients();
        }
    };
    source.onerror = function() {
        source.close();
        fetch('/status').then(r => r.json()).then(d => {
            if (d.status === 'complete' || d.status === 'stopped') loadPatients();
        }).catch(() => {});
    };
    window.addEventListener('beforeunload', () => source.close());
}

function _pollUntilExtracting() {
    // Status is 'parsed' — extraction hasn't started yet. Poll until it does.
    _reviewPollTimer = setInterval(() => {
        fetch('/status').then(r => r.json()).then(d => {
            if (d.status === 'extracting') {
                clearInterval(_reviewPollTimer);
                _attachProgressSSE();
            } else if (d.status === 'complete' || d.status === 'stopped') {
                clearInterval(_reviewPollTimer);
                loadPatients();
            }
        }).catch(() => {});
    }, 3000);
    window.addEventListener('beforeunload', () => clearInterval(_reviewPollTimer));
}

function initLiveReview() {
    fetch('/status')
        .then(r => r.json())
        .then(data => {
            if (data.status === 'extracting') {
                loadPatients(); // Show any patients already completed before page opened
                _attachProgressSSE();
            } else if (data.status === 'parsed') {
                _pollUntilExtracting();
            }
            // 'complete'/'stopped'/'idle': DOMContentLoaded handler already loaded patients
        })
        .catch(() => {});
}

// Only run on review page
if (document.getElementById('source-panel')) {
    initLiveReview();
}

function linkSourceFile(file) {
    if (!file) return;
    const btn = document.getElementById('btn-link-source');
    const originalText = btn.textContent;
    btn.textContent = 'Linking...';
    btn.disabled = true;

    const formData = new FormData();
    formData.append('file', file);

    fetch('/link-source', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            btn.textContent = originalText;
            btn.disabled = false;
            if (data.error) {
                alert('Link failed: ' + data.error);
                return;
            }
            const successDiv = document.getElementById('link-success');
            const countSpan = document.getElementById('link-match-count');
            const linkMatchCount = document.getElementById('link-match-count');
            if (successDiv && linkMatchCount) {
                linkMatchCount.textContent = data.matched;
                successDiv.classList.remove('d-none');
                setTimeout(() => successDiv.classList.add('d-none'), 5000);
            }
            // Refresh current patient preview if one is selected
            if (currentPatientId) {
                selectPatient(currentPatientId);
            }
        })
        .catch(err => {
            btn.textContent = originalText;
            btn.disabled = false;
            alert('Link failed: ' + err);
        });
}

// ── Coverage toggle ──
let _coverageVisible = false;
let _coverageMap = null;
let _coveragePct = null;

function initCoverageToggle(coverageMap, coveragePct, coords) {
    _coverageMap = coverageMap;
    _coveragePct = coveragePct;
    _coverageVisible = false;

    const container = document.getElementById('coverage-toggle-container');
    const btn = document.getElementById('coverage-toggle-btn');
    const badge = document.getElementById('coverage-badge');

    if (!container || !btn) return;

    // Reset button state
    btn.textContent = 'Show unused text';
    btn.classList.add('btn-outline-warning');
    btn.classList.remove('btn-warning');
    btn.disabled = false;
    btn.title = '';
    if (badge) {
        badge.classList.remove('d-none');
        badge.textContent = '';
    }

    // Remove old event listener by cloning
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);

    // Remove any existing overlay
    const existing = document.getElementById('coverage-svg-overlay');
    if (existing) existing.remove();

    if (!coverageMap || Object.keys(coverageMap).length === 0) {
        container.classList.remove('d-none');
        newBtn.disabled = true;
        newBtn.title = 'Coverage data not available (legacy file)';
        if (badge) badge.classList.add('d-none');
        return;
    }

    container.classList.remove('d-none');
    if (coveragePct !== null && coveragePct !== undefined) {
        badge.textContent = coveragePct + '% covered';
    } else {
        if (badge) badge.classList.add('d-none');
    }

    newBtn.addEventListener('click', () => {
        _coverageVisible = !_coverageVisible;
        newBtn.textContent = _coverageVisible ? 'Hide unused text' : 'Show unused text';
        newBtn.classList.toggle('btn-warning', _coverageVisible);
        newBtn.classList.toggle('btn-outline-warning', !_coverageVisible);
        renderCoverageOverlay(_coverageVisible, coords);
    });
}

function renderCoverageOverlay(show, coords) {
    const existing = document.getElementById('coverage-svg-overlay');
    if (existing) existing.remove();
    if (!show || !_coverageMap || !coords) return;

    const previewImg = document.getElementById('preview-img');
    if (!previewImg || previewImg.naturalWidth === 0) return;

    const scaleX = previewImg.clientWidth / previewImg.naturalWidth;
    const scaleY = previewImg.clientHeight / previewImg.naturalHeight;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.id = 'coverage-svg-overlay';
    svg.style.cssText = 'position:absolute;top:0;left:0;' +
        'width:' + previewImg.clientWidth + 'px;' +
        'height:' + previewImg.clientHeight + 'px;' +
        'pointer-events:none;z-index:10;';

    for (const [cellKey, spans] of Object.entries(_coverageMap)) {
        if (!spans || spans.length === 0) continue;
        const cellCoord = coords[cellKey];
        if (!cellCoord) continue;
        const unusedLen = spans.filter(s => !s.used).reduce((a, s) => a + (s.end - s.start), 0);
        const totalLen = spans.reduce((a, s) => a + (s.end - s.start), 0);
        if (totalLen === 0 || unusedLen === 0) continue;

        const ratio = unusedLen / totalLen;
        const opacity = Math.min(0.6, ratio * 0.8);

        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', cellCoord.x * scaleX);
        rect.setAttribute('y', cellCoord.y * scaleY);
        rect.setAttribute('width', cellCoord.w * scaleX);
        rect.setAttribute('height', cellCoord.h * scaleY);
        rect.setAttribute('fill', 'rgba(255,165,0,' + opacity + ')');
        rect.setAttribute('stroke', 'rgba(255,140,0,0.6)');
        rect.setAttribute('stroke-width', '1');
        svg.appendChild(rect);
    }

    const previewContainer = document.getElementById('preview-container');
    if (previewContainer) {
        previewContainer.style.position = 'relative';
        previewContainer.appendChild(svg);
    }
}
