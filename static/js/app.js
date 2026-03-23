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
    const startBtn = document.getElementById('start-btn');
    if (startBtn) startBtn.classList.add('d-none');

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
                completeSummary.textContent = `${statusText} ${data.current_patient} / ${data.total} patients processed. Average speed: ${data.average_seconds}s per patient.`;
            }
            return;
        }

        const phase = data.phase || 'idle';
        const total = data.total || 0;

        // Regex bar: regex_complete / total
        const regexPct = total > 0 ? ((data.regex_complete || 0) / total * 100).toFixed(0) : 0;

        // LLM bar: patients fully done / total patients
        const llmTotal = data.llm_queue_size || 0;
        const llmDonePatients = (data.completed_patients || []).length;
        const llmPct = total > 0 ? (llmDonePatients / total * 100).toFixed(0) : 0;

        const regexBar = document.getElementById('progress-bar-regex');
        const llmBar = document.getElementById('progress-bar-llm');
        const progressText = document.getElementById('progress-text');
        const phaseDetail = document.getElementById('phase-detail');
        const activePatientsList = document.getElementById('active-patients-list');
        const averageSpeedEl = document.getElementById('average-speed');

        if (regexBar) {
            regexBar.style.width = regexPct + '%';
            // Animate while regex is active, freeze once done
            if (phase === 'regex') {
                regexBar.className = 'progress-bar bg-success progress-bar-striped progress-bar-animated';
            } else {
                regexBar.className = 'progress-bar bg-success';
            }
        }

        if (llmBar) {
            llmBar.style.width = llmPct + '%';
            // Animate while LLM is active
            if (phase === 'llm') {
                llmBar.className = 'progress-bar bg-primary progress-bar-striped progress-bar-animated';
            } else {
                llmBar.className = 'progress-bar bg-primary';
            }
        }

        // Regex label: always show actual regex counts
        if (progressText) {
            const regexDone = data.regex_complete || 0;
            if (phase === 'llm' || phase === 'complete') {
                progressText.textContent = `${regexDone} / ${total} ✓`;
            } else {
                progressText.textContent = `${regexDone} / ${total} patients`;
            }
        }

        // LLM label: patients fully completed
        if (phaseDetail) {
            if (phase === 'llm') {
                const done = (data.completed_patients || []).length;
                phaseDetail.textContent = `${done} / ${total} patients`;
            } else {
                phaseDetail.textContent = '';
            }
        }

        if (averageSpeedEl && data.average_seconds > 0) {
            averageSpeedEl.textContent = `${data.average_seconds}s / patient`;
        }

        // Render active patients — improved card styling
        if (activePatientsList) {
            // Only show tasks that are actually running (not queued waiting for semaphore)
            const active = Object.entries(data.active_patients || {}).filter(([, p]) => p.status !== 'queued');
            if (active.length === 0) {
                activePatientsList.innerHTML = '<span class="text-muted small">Waiting...</span>';
            } else {
                activePatientsList.innerHTML = active.map(([id, p]) => {
                    const elapsed = Math.floor((Date.now() - (p.start * 1000)) / 1000);
                    const mins = Math.floor(elapsed / 60).toString().padStart(2, '0');
                    const secs = (elapsed % 60).toString().padStart(2, '0');
                    const isRegex = p.group === 'Regex';
                    const isQueued = p.status === 'queued';
                    const accentColor = isRegex ? '#198754' : isQueued ? '#4b5563' : '#0d6efd';
                    const timerColor = isQueued ? '#6b7280' : '#f59e0b';
                    const groupLabel = isQueued ? `⏳ ${p.group}` : p.group || 'Starting...';
                    return `<div style="background:#111827; border:1px solid ${accentColor}; border-radius:6px; padding:8px 12px; min-width:155px; opacity:${isQueued ? '0.6' : '1'};">` +
                           `<div style="font-size:12px; font-weight:700; color:#f0f0f0; letter-spacing:0.5px;">${p.initials || 'Patient'}</div>` +
                           `<div style="font-size:10px; color:#9ca3af; margin-top:2px;">${groupLabel}</div>` +
                           `<div style="font-size:14px; font-weight:700; color:${timerColor}; font-family:monospace; margin-top:4px;">${mins}:${secs}</div>` +
                           `</div>`;
                }).join('');
            }
        }

        // Render completed patients log — medium in red to match badge colour
        if (data.completed_patients && data.completed_patients.length > 0) {
            const log = document.getElementById('completed-log');
            if (log) {
                log.innerHTML = data.completed_patients.slice().reverse().map(p => {
                    const c = p.confidence_summary || {};
                    const timeStr = p.seconds ? `(${p.seconds}s)` : '';
                    return `<div class="text-muted py-1 d-flex justify-content-between">` +
                        `<span>&#x2713; ${p.initials || p.id} &middot; ` +
                        `<span class="text-success">${c.high || 0} high</span> &middot; ` +
                        `<span class="text-danger">${c.medium || 0} med</span> &middot; ` +
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
                <span class="badge bg-danger" style="font-size:10px">${c.medium || 0} med</span>
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
            // Update source document panel and preview
            renderSourceTable(data.raw_cells || []);
            renderDocPreview(data.raw_cells || []);
            window._currentRawCells = data.raw_cells || [];

            // Store extractions for re-rendering on filter change
            allPatientExtractions = data.extractions || {};

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

function renderSourceTable(rawCells) {
    const container = document.getElementById('source-table');
    if (!container) return;
    if (!rawCells || rawCells.length === 0) {
        container.innerHTML = '<span class="text-muted small">No source document available (imported from Excel)</span>';
        return;
    }

    const rowMap = {};
    rawCells.forEach(cell => {
        if (!rowMap[cell.row]) rowMap[cell.row] = {};
        rowMap[cell.row][cell.col] = cell.text;
    });

    const numCols = Math.max(...rawCells.map(c => c.col)) + 1;
    const headerRows = new Set([0, 2, 4, 6]);

    // Single-column document view — each row is a header block or content block.
    // data-row / data-col preserved on each div so highlightSource() can target them.
    let html = '<div style="font-size:11px;">';
    Object.keys(rowMap).sort((a, b) => +a - +b).forEach(rowIdx => {
        const isHeader = headerRows.has(+rowIdx);
        const cols = rowMap[rowIdx];
        if (isHeader) {
            const text = (cols[0] || cols[1] || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            const firstCol = cols[0] ? 0 : 1;
            html += `<div data-row="${rowIdx}" data-col="${firstCol}" ` +
                    `style="background:#21262d; color:#58a6ff; padding:5px 8px; font-weight:700; ` +
                    `margin-top:6px; border-left:3px solid #4580f7; cursor:default;">${text}</div>`;
        } else {
            for (let c = 0; c < numCols; c++) {
                const text = (cols[c] || '').trim();
                if (!text) continue;
                const safe = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                html += `<div data-row="${rowIdx}" data-col="${c}" ` +
                        `style="color:#8b949e; padding:3px 8px 3px 14px; font-family:monospace; ` +
                        `white-space:pre-wrap; word-break:break-word; cursor:pointer;">${safe}</div>`;
            }
        }
    });
    html += '</div>';
    container.innerHTML = html;
}

function renderDocPreview(rawCells) {
    const container = document.getElementById('doc-preview');
    if (!container) return;
    if (!rawCells || rawCells.length === 0) {
        container.innerHTML = '<span class="text-muted small">No document data</span>';
        return;
    }

    const rowMap = {};
    rawCells.forEach(cell => {
        if (!rowMap[cell.row]) rowMap[cell.row] = {};
        rowMap[cell.row][cell.col] = cell.text;
    });

    const numCols = Math.max(...rawCells.map(c => c.col)) + 1;
    const headerRows = new Set([0, 2, 4, 6]);

    let html = '<div style="background:#111827; border-radius:6px; padding:10px 14px; font-size:11px; line-height:1.6;">';
    Object.keys(rowMap).sort((a, b) => +a - +b).forEach(rowIdx => {
        const isHeader = headerRows.has(+rowIdx);
        const cols = rowMap[rowIdx];
        if (isHeader) {
            const text = (cols[0] || cols[1] || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            html += `<div style="color:#f0c060; font-weight:700; margin-top:10px; margin-bottom:3px; ` +
                    `border-bottom:1px solid #2d333b; padding-bottom:2px;">${text}</div>`;
        } else {
            const parts = [];
            for (let c = 0; c < numCols; c++) {
                const t = (cols[c] || '').trim();
                if (t) parts.push(t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'));
            }
            if (parts.length) {
                html += `<div style="color:#c9d1d9;">${parts.join(' &nbsp;&middot;&nbsp; ')}</div>`;
            }
        }
    });
    html += '</div>';
    container.innerHTML = html;
}

function highlightSource(fr) {
    // Clear all previous highlights (now divs, not tds)
    document.querySelectorAll('#source-table [data-row]').forEach(el => {
        el.style.outline = '';
        el.style.background = '';
        if (el.querySelector('mark')) {
            el.textContent = el.textContent;
        }
    });
    const warning = document.getElementById('source-warning');
    if (warning) warning.classList.add('d-none');

    if (!fr || fr.value === null || fr.value === undefined) return;

    const conf = fr.confidence || 'none';
    const colours = {
        high:   { border: '#198754', mark: 'rgba(25,135,84,0.3)',  text: '#6ee7a0' },
        medium: { border: '#dc3545', mark: 'rgba(220,53,69,0.25)', text: '#ff8c94' },
        low:    { border: '#dc3545', mark: 'rgba(220,53,69,0.35)', text: '#ff6b6b' },
    };
    const colour = colours[conf];

    if (fr.source_cell && colour) {
        const { row, col } = fr.source_cell;
        const el = document.querySelector(`#source-table [data-row="${row}"][data-col="${col}"]`);
        if (el) {
            el.style.outline = `2px solid ${colour.border}`;
            el.style.background = colour.mark;
            if (fr.source_snippet) {
                const fullText = el.textContent;
                const idx = fullText.indexOf(fr.source_snippet);
                if (idx !== -1) {
                    el.textContent = '';
                    const before = document.createTextNode(fullText.slice(0, idx));
                    const mark = document.createElement('mark');
                    mark.style.cssText = `background:${colour.mark}; color:${colour.text}; border-radius:2px; padding:0 2px;`;
                    mark.textContent = fr.source_snippet;
                    const after = document.createTextNode(fullText.slice(idx + fr.source_snippet.length));
                    el.appendChild(before);
                    el.appendChild(mark);
                    el.appendChild(after);
                }
            }
            el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    } else if (fr.value !== null) {
        if (warning) warning.classList.remove('d-none');
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
                          isInferred ? 'danger' :
                          fr.confidence === 'high' ? 'success' :
                          fr.confidence === 'none' ? 'secondary' : 'danger';
        const confText = !hasValue ? (isPending ? 'PENDING' : 'EMPTY') :
                         isInferred ? 'INFERRED' :
                         fr.confidence === 'none' ? 'N/A' : (fr.confidence || 'low').toUpperCase();
        const safeValue = (fr.value || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const editedBadge = fr.edited ? '<span class="badge bg-info ms-1" style="font-size:9px">EDITED</span>' : '';
        const safeReason = (fr.reason || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const inputBorder = isInferred ? 'border-color: #dc3545 !important;' : '';
        const rowBg = isInferred ? 'background-color: rgba(220, 53, 69, 0.05);' : '';
        const frData = JSON.stringify({value: fr.value, confidence: fr.confidence, source_cell: fr.source_cell || null, source_snippet: fr.source_snippet || null});
        const safeFrData = frData.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        return `
        <tr class="${isPending ? 'pending-row' : ''}" style="border-left: 4px solid ${groupColor}; ${rowBg} cursor:pointer;"
            data-fr="${safeFrData}" onclick="highlightSource(JSON.parse(this.dataset.fr))">
            <td class="small" style="color: ${hasValue ? '#c9d1d9' : '#555'};">${key}</td>
            <td>
                <input type="text" class="form-control form-control-sm bg-dark text-light border-${confClass}"
                       value="${safeValue}" placeholder="${hasValue ? '' : 'Enter value...'}"
                       style="${inputBorder}"
                       onchange="editField('${groupName}', '${key}', this.value)">
            </td>
            <td class="text-center" style="min-width: 140px;">
                <span class="badge bg-${confClass}" style="font-size:10px; cursor:help;"
                      title="${safeReason}">${confText}</span>
                ${editedBadge}
                ${safeReason && confText !== 'EMPTY' && confText !== 'N/A' ? '<div class="text-muted mt-1" style="font-size:9px; line-height:1.2;">' + safeReason + '</div>' : ''}
            </td>
        </tr>`;
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
function initLiveReview() {
    fetch('/status')
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'extracting') return;
            const source = new EventSource('/progress');

            source.onmessage = function(event) {
                const d = JSON.parse(event.data);
                if (d.status === 'complete' || d.status === 'stopped') {
                    source.close();
                    loadPatients();
                }
            };

            source.onerror = function() {
                source.close();
            };

            window.addEventListener('beforeunload', () => source.close());
        })
        .catch(() => {});
}

// Only run on review page
if (document.getElementById('source-panel')) {
    initLiveReview();
}
