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
    const data = JSON.parse(sessionStorage.getItem('upload_result') || 'null');
    const fileName = sessionStorage.getItem('file_name') || 'Unknown file';

    const fileNameEl = document.getElementById('file-name');
    const patientCountEl = document.getElementById('patient-count');

    if (fileNameEl) fileNameEl.textContent = fileName;
    if (patientCountEl) patientCountEl.textContent = data ? data.patients_detected : '?';
}

function startExtraction() {
    const startBtn = document.getElementById('start-btn');
    if (startBtn) startBtn.classList.add('d-none');

    const progressSection = document.getElementById('progress-section');
    if (progressSection) progressSection.classList.remove('d-none');

    const limitInput = document.getElementById('patient-limit');
    const limit = limitInput && limitInput.value ? parseInt(limitInput.value) : null;
    const body = limit ? JSON.stringify({limit: limit}) : '{}';

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

function listenProgress() {
    const source = new EventSource('/progress');

    source.onmessage = function(event) {
        const data = JSON.parse(event.data);

        if (data.status === 'complete') {
            source.close();
            const progressSection = document.getElementById('progress-section');
            const completeSection = document.getElementById('complete-section');
            const completeSummary = document.getElementById('complete-summary');

            if (progressSection) progressSection.classList.add('d-none');
            if (completeSection) completeSection.classList.remove('d-none');
            if (completeSummary) {
                completeSummary.textContent = `${data.total} patients processed successfully`;
            }
            return;
        }

        const pct = data.total > 0 ? (data.current_patient / data.total * 100).toFixed(0) : 0;

        const progressBar = document.getElementById('progress-bar');
        const progressText = document.getElementById('progress-text');
        const currentPatientEl = document.getElementById('current-patient');

        if (progressBar) progressBar.style.width = pct + '%';
        if (progressText) progressText.textContent = `${data.current_patient} / ${data.total} patients`;
        if (currentPatientEl) {
            currentPatientEl.textContent = `Patient ${data.current_patient} — ${data.current_group}`;
        }

        // Render completed patients log
        if (data.completed_patients && data.completed_patients.length > 0) {
            const log = document.getElementById('completed-log');
            if (log) {
                log.innerHTML = data.completed_patients.slice().reverse().map(p => {
                    const c = p.confidence_summary || {};
                    return `<div class="text-muted py-1">&#x2713; ${p.initials || p.id} &middot; ` +
                        `<span class="text-success">${c.high || 0} high</span> &middot; ` +
                        `<span class="text-warning">${c.medium || 0} med</span> &middot; ` +
                        `<span class="text-danger">${c.low || 0} low</span></div>`;
                }).join('');
                log.scrollTop = 0;
            }
        }
    };

    source.onerror = function() {
        // SSE connection lost — check if extraction is complete
        source.close();
        setTimeout(() => {
            fetch('/patients')
                .then(r => r.json())
                .then(data => {
                    if (data.patients && data.patients.length > 0) {
                        // Extraction may be complete, redirect to review
                        window.location.href = '/review';
                    }
                });
        }, 2000);
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
                <span class="badge bg-warning text-dark" style="font-size:10px">${c.medium || 0} med</span>
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
            // Update source text panel
            const sourceText = document.getElementById('source-text');
            if (sourceText) sourceText.textContent = data.raw_text || '';

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

        const confClass = !hasValue ? 'secondary' :
                          isInferred ? 'info' :
                          fr.confidence === 'high' ? 'success' :
                          fr.confidence === 'medium' ? 'warning' :
                          fr.confidence === 'none' ? 'secondary' : 'danger';
        const confText = !hasValue ? 'EMPTY' :
                         isInferred ? 'INFERRED' :
                         fr.confidence === 'none' ? 'N/A' : (fr.confidence || 'low').toUpperCase();
        const safeValue = (fr.value || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const editedBadge = fr.edited ? '<span class="badge bg-info ms-1" style="font-size:9px">EDITED</span>' : '';
        const safeReason = (fr.reason || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const inputBorder = isInferred ? 'border-color: #0dcaf0 !important;' : '';
        const rowBg = isInferred ? 'background-color: rgba(13, 202, 240, 0.05);' : '';
        return `
        <tr style="border-left: 4px solid ${groupColor}; ${rowBg}">
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
