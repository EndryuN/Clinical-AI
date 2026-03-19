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
    if (!file.name.endsWith('.docx')) {
        showUploadError('Only .docx files are supported.');
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
            // Store data and redirect to process page
            sessionStorage.setItem('upload_result', JSON.stringify(data));
            sessionStorage.setItem('file_name', file.name);
            window.location.href = '/process';
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

    fetch('/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
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
let confidenceFilter = '';
let allPatientExtractions = {};

function loadPatients(filters) {
    filters = filters || {};
    let url = '/patients?';
    if (filters.cancer_type) url += `cancer_type=${encodeURIComponent(filters.cancer_type)}&`;
    if (filters.search) url += `search=${encodeURIComponent(filters.search)}&`;

    fetch(url)
        .then(r => r.json())
        .then(data => renderPatientList(data.patients || []));
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

            // Set first group as active if none selected or group not in this patient
            const groups = Object.keys(allPatientExtractions);
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

    tabs.innerHTML = groups.map(g => `
        <li class="nav-item">
            <a class="nav-link ${g === currentGroup ? 'active' : ''}" href="#"
               onclick="switchGroup('${g}'); return false;">${g}</a>
        </li>
    `).join('');
}

function switchGroup(group) {
    currentGroup = group;

    // Re-render tabs to update active state
    renderGroupTabs(Object.keys(allPatientExtractions));

    // Render the selected group's fields
    if (allPatientExtractions[group]) {
        renderFieldTable(allPatientExtractions[group], group);
    }
}

function renderFieldTable(fields, groupName) {
    const tbody = document.getElementById('field-table-body');
    if (!tbody) return;

    const allowedConf = confidenceFilter ? confidenceFilter.split(',') : null;

    const entries = Object.entries(fields)
        .filter(([key, fr]) => !allowedConf || allowedConf.includes(fr.confidence));

    if (entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-muted text-center py-3">No fields match the current confidence filter</td></tr>';
        return;
    }

    tbody.innerHTML = entries.map(([key, fr]) => {
        const confClass = fr.confidence === 'high' ? 'success' :
                          fr.confidence === 'medium' ? 'warning' : 'danger';
        const confText = (fr.confidence || 'low').toUpperCase();
        const safeValue = (fr.value || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const editedBadge = fr.edited ? '<span class="badge bg-info ms-1" style="font-size:9px">EDITED</span>' : '';
        return `
        <tr>
            <td class="text-muted small">${key}</td>
            <td>
                <input type="text" class="form-control form-control-sm bg-dark text-light border-${confClass}"
                       value="${safeValue}"
                       onchange="editField('${groupName}', '${key}', this.value)">
            </td>
            <td class="text-center">
                <span class="badge bg-${confClass}">${confText}</span>
                ${editedBadge}
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
                }
            }
        })
        .catch(err => console.error('Edit failed:', err));
}
