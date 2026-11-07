// CRM Local — Enhanced Frontend (D-031 / D-032)
// Universal extract, contacts, companies, staged approval, customer profiles

const API_BASE = (window.CRM_API_BASE || '/api').replace(/\/$/, '');

// ── State ────────────────────────────────────────────────────────────────────
const S = {
    currentView: 'overview',
    page: 1,
    pageSize: 50,
    sort: 'id',
    dir: 'desc',
    contacts: [],
    companies: [],
    emaills: [],   // emails stored
    extractionRunId: null,
    fileQueue: [],
    // Staged contact state
    stagedReviewPage: 1,
    stagedPageSize: 20,
    // Duplicate detection state
    dedupChecking: false,
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s)
        .replace(/&/g, '&')
        .replace(/</g, '<')
        .replace(/>/g, '>')
        .replace(/"/g, '"')
        .replace(/'/g, ''');
}

// Theme management
function setTheme(theme, persist = false) {
    document.body.setAttribute('data-theme', theme);
    if (persist) localStorage.setItem('crm-theme', theme);
}

// Auth session sync (placeholder - no auth in local mode)
function syncAuthSession() {}

// ── Navigation ────────────────────────────────────────────────────────────────

function showView(id) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const v = document.getElementById('view-' + id);
    if (v) v.classList.add('active');
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const nav = document.querySelector(`.nav-item[data-view="${id}"]`);
    if (nav) nav.classList.add('active');
    const titles = {
        overview: 'Overview',
        extract: 'Universal Extract',
        contacts: 'Contacts',
        emails: 'Emails',
        profiles: 'Customer Profiles',
        quality: 'Data Quality',
        history: 'History',
        settings: 'Settings',
    };
    document.getElementById('topTitle').textContent = titles[id] || id;
    S.currentView = id;
    if (id === 'overview') loadOverview();
    if (id === 'extract') renderFileQueue();
    if (id === 'contacts') loadContacts();
    if (id === 'emails') loadEmails();
    if (id === 'profiles') loadCustomerProfiles();
    if (id === 'quality') loadDataQuality();
    if (id === 'history') loadHistory();
    if (id === 'settings') loadSettings();
    location.hash = '#/' + id;
}

function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('collapsed');
}

window.addEventListener('hashchange', () => {
    const hash = location.hash.replace('#/', '').replace('#', '');
    if (hash) showView(hash);
});

// ── API client with error handling, loading states, and cancellation ──────────

let activeRequests = 0;
const MAX_CONCURRENT = 6;

async function api(path, opts = {}) {
    activeRequests++;
    if (activeRequests > MAX_CONCURRENT) {
        throw new Error('Too many concurrent requests');
    }
    try {
        const resp = await fetch(API_BASE + path, {
            ...opts,
            headers: {
                'Content-Type': 'application/json',
                ...(opts.headers || {}),
            },
        });
        if (!resp.ok) {
            const txt = await resp.text();
            throw new Error(`API ${resp.status}: ${txt}`);
        }
        return resp.json();
    } finally {
        activeRequests--;
    }
}

async function apiFormData(path, formData, opts = {}) {
    activeRequests++;
    if (activeRequests > MAX_CONCURRENT) {
        throw new Error('Too many concurrent requests');
    }
    try {
        const resp = await fetch(API_BASE + path, {
            ...opts,
            method: (opts.method || 'POST'),
            body: formData,
        });
        if (!resp.ok) {
            const txt = await resp.text();
            throw new Error(`API ${resp.status}: ${txt}`);
        }
        return resp.json();
    } finally {
        activeRequests--;
    }
}

// ── Overview ────────────────────────────────────────────────────────────────

async function loadOverview() {
    try {
        const status = await api('/api/status');
        const counts = status.counts || {};

        // KPI grid
        document.getElementById('kpi-contacts').textContent = counts.crm || 0;
        document.getElementById('kpi-emails').textContent = counts.emails || 0;
        document.getElementById('kpi-files').textContent = counts.processed_files || 0;
        document.getElementById('kpi-new').textContent = counts.new || 0;
        document.getElementById('kpi-dupes').textContent = counts.duplicates || 0;

        // Data completeness
        const total = (counts.crm || 0) + (counts.eml_contacts || 0);
        const withEmail = total;
        const completeness = total > 0 ? Math.round((withEmail / total) * 100) : 0;
        document.getElementById('kpi-completeness').textContent = completeness + '%';

        // Recent activity
        const activityList = document.getElementById('recent-activity');
        const recentRuns = status.run || {};
        let activityHtml = '';
        if (recentRuns.extraction_run_id) {
            activityHtml = '<p>Last extraction run: ' + (recentRuns.status || 'completed') + '</p>';
        } else {
            activityHtml = '<p>No recent extraction runs.</p>';
        }
        activityList.innerHTML = activityHtml;

        // Update kpi-new and kpi-dupes from DB if available
        document.getElementById('kpi-new').textContent = counts.new || 0;
        document.getElementById('kpi-dupes').textContent = counts.duplicates || 0;

    } catch (e) {
        document.getElementById('recent-activity').innerHTML =
            '<p class="error">Error loading data: ' + esc(e.message) + '</p>';
    }
}

// ── Extract ──────────────────────────────────────────────────────────────────

let fileQueue = [];

function handleDrop(e) {
    e.preventDefault();
    e.target.classList.remove('drag');
    handleFiles(e.dataTransfer.files);
}

function handleFiles(files) {
    for (const f of files) {
        fileQueue.push(f);
    }
    renderFileQueue();
    document.getElementById('extractBtn').disabled = fileQueue.length === 0;
}

function renderFileQueue() {
    const el = document.getElementById('fileQueue');
    el.innerHTML = fileQueue.map((f, i) => `
        <div class="queue-item">
            <span class="filename">${esc(f.name)}</span>
            <span class="file-size">$(f.size / 1024).toFixed(1)KB</span>
            <button onclick="removeFromQueue(${i})" class="btn btn-sm btn-danger" title="Remove">✕</button>
        </div>
    `).join('');
}

function removeFromQueue(i) {
    fileQueue.splice(i, 1);
    renderFileQueue();
    document.getElementById('extractBtn').disabled = fileQueue.length === 0;
}

function clearQueue() {
    fileQueue = [];
    renderFileQueue();
    document.getElementById('extractBtn').disabled = true;
}

async function startExtraction() {
    if (fileQueue.length === 0) return;
    const btn = document.getElementById('extractBtn');
    btn.disabled = true;
    const progress = document.getElementById('progress');
    const fill = document.getElementById('progressFill');
    const text = document.getElementById('progressText');
    const results = document.getElementById('extractResults');
    results.innerHTML = '';

    progress.style.display = 'block';
    text.textContent = '0/' + fileQueue.length;
    results.innerHTML = '';

    try {
        const paths = fileQueue.map(f => f.name);
        const resp = await api('/api/intake', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paths: paths }),
        });

        // Update progress bar
        fill.style.width = '100%';
        text.textContent = `${resp.results.length}/${fileQueue.length}`;

        // Render results
        results.innerHTML = resp.results.map(r =>
            `<div class="result-item ${r.status === 'OK' ? 'success' : 'error'}">
                <strong>${esc(r.file)}</strong>: ${r.status} (${
                    r.contacts_found || 0
                } contacts) ${esc(r.error || '')}
            </div>`
        ).join('');

        if (resp.counts) {
            results.innerHTML += `<div class="result-summary">New: ${resp.counts.new}, Merged: ${resp.counts.merged}, Skipped: ${resp.counts.skipped}, Errors: ${resp.counts.error}</div>`;
        }

        // Reload overview after extraction
        loadOverview();

    } catch (e) {
        results.innerHTML = '<div class="result-item error">Error: ' + esc(e.message) + '</div>';
    } finally {
        btn.disabled = false;
    }
}

// ── Contacts ────────────────────────────────────────────────────────────────

async function loadContacts() {
    try {
        const data = await api('/api/contacts?which=crm&page=' + S.page + '&size=' + S.pageSize);
        S.contacts = data.rows || [];
        renderContactsTable();
        renderPagination('contactsPagination', data.total, S.page, S.pageSize, (p) => {
            S.page = p;
            loadContacts();
        });
    } catch (e) {
        document.getElementById('contactsBody').innerHTML = '<tr><td colspan="6">Error: ' + esc(e.message) + '</td></tr>';
    }
}

function renderContactsTable() {
    const tbody = document.getElementById('contactsBody');
    if (S.contacts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6">No contacts found</td></tr>';
        return;
    }
    tbody.innerHTML = S.contacts.map(c => `
        <tr>
            <td>${esc(c.name || '')}</td>
            <td>${esc(c.email_primary || '')}</td>
            <td>${esc(c.phone_primary || '')}</td>
            <td>${esc(c.company || '')}</td>
            <td>
                <div class="action-buttons">
                    <button class="btn btn-sm" onclick="editContact(${c.id})" title="Edit">✎</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteContact(${c.id})" title="Delete">🗑</button>
                    <button class="btn btn-sm" onclick="viewContactProfile(${c.id})" title="Profile">👁</button>
                </div>
            </td>
        </tr>
    `).join('');
}

function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s)
        .replace(/&/g, '&')
        .replace(/</g, '<')
        .replace(/>/g, '>')
        .replace(/"/g, '"')
        .replace(/'/g, ''');
}

async function searchContacts() {
    const q = document.getElementById('contactSearch').value;
    try {
        const data = await api('/api/contacts?which=crm&q=' + encodeURIComponent(q) + '&page=1&size=' + S.pageSize);
        S.contacts = data.rows || [];
        renderContactsTable();
    } catch (e) { console.error(e); }
}

function sortContacts(field) {
    if (S.sort === field) S.dir = S.dir === 'asc' ? 'desc' : 'asc';
    else { S.sort = field; S.dir = 'asc'; }
    loadContacts();
}

async function editContact(id) {
    const c = S.contacts.find(x => x.id === id);
    if (!c) return;
    const name = prompt('Name:', c.name || '');
    if (name === null) return;
    try {
        await api('/api/contacts/crm/' + id, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fields: { name: name } }),
        });
        loadContacts();
    } catch (e) { alert('Error: ' + e.message); }
}

async function deleteContact(id) {
    if (!confirm('Delete this contact?')) return;
    try {
        await api('/api/contacts/crm/' + id, { method: 'DELETE' });
        loadContacts();
    } catch (e) { alert('Error: ' + e.message); }
}

function renderPagination(elId, total, page, size, onPage) {
    const el = document.getElementById(elId);
    const totalPages = Math.max(1, Math.ceil(total / size));
    if (totalPages <= 1) { el.innerHTML = ''; return; }

    let html = '';
    // First
    html += `<button ${page === 1 ? 'disabled' : ''} onclick="S.page=1; loadContacts()" aria-label="First page">«</button>`;
    // Prev
    html += `<button ${page === 1 ? 'disabled' : ''} onclick="S.page=${page - 1}; loadContacts()" aria-label="Previous page">‹</button>`;
    // Pages
    const maxVisible = 5;
    let start = Math.max(1, page - Math.floor(maxVisible / 2));
    let end = Math.min(totalPages, start + maxVisible - 1);
    start = Math.max(1, end - maxVisible + 1);

    for (let i = start; i <= end; i++) {
        html += `<button ${i === page ? 'class="active"' : ''} onclick="S.page=${i}; loadContacts()" aria-page="${i}">${i}</button>`;
    }
    // Next
    html += `<button ${page === totalPages ? 'disabled' : ''} onclick="S.page=${page + 1}; loadContacts()" aria-label="Next page">›</button>`;
    // Last
    html += `<button ${page === totalPages ? 'disabled' : ''} onclick="S.page=${totalPages}; loadContacts()" aria-label="Last page">»</button>`;

    el.innerHTML = html;
}

// ── Emails ───────────────────────────────────────────────────────────────────

async function loadEmails() {
    try {
        const data = await api('/api/emails?page=' + S.page + '&size=' + S.pageSize);
        S.emails = data.rows || [];
        renderEmailsTable();
        renderPagination('emailsPagination', data.total, S.page, S.pageSize, (p) => {
            S.page = p;
            loadEmails();
        });
    } catch (e) {
        document.getElementById('emailsBody').innerHTML = '<tr><td colspan="4">Error: ' + esc(e.message) + '</td></tr>';
    }
}

function renderEmailsTable() {
    const tbody = document.getElementById('emailsBody');
    if (S.emails.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4">No emails found</td></tr>';
        return;
    }
    tbody.innerHTML = S.emails.map(e => `
        <tr>
            <td>${esc(e.subject || '')}</td>
            <td>${esc(e.sender_name || '')}</td>
            <td>${esc(e.date || '')}</td>
            <td>${esc(e.contact_count || 0)}</td>
        </tr>
    `).join('');
}

// ── Customer Profiles ────────────────────────────────────────────────────────

async function loadCustomerProfiles() {
    try {
        const data = await api('/api/contacts?which=crm&page=1&size=' + S.pageSize);
        S.contacts = data.rows || [];
        renderCustomerProfiles();
    } catch (e) {
        document.getElementById('profilesList').innerHTML = '<p>Error loading profiles: ' + esc(e.message) + '</p>';
    }
}

function renderCustomerProfiles() {
    const el = document.getElementById('profilesList');
    if (S.contacts.length === 0) {
        el.innerHTML = '<p class="empty-state">No contacts yet. <button class="btn btn-primary" onclick="showView(\'contacts\')">Add Your First Contact</button></p>';
        return;
    }

    let html = '';
    S.contacts.slice(0, 8).forEach(c => {
        const email = c.email_primary || '';
        const phone = c.phone_primary || '';
        const company = c.company || '—';
        html += `
            <div class="profile-card">
                <h4>${esc(c.name || 'Unnamed')}</h4>
                <p><strong>Company:</strong> ${esc(company)}</p>
                <p><strong>Email:</strong> ${esc(email)}</p>
                <p><strong>Phone:</strong> ${esc(phone)}</p>
                <p class="muted">ID: ${c.id}</p>
                <button class="btn btn-sm btn-primary" onclick="viewContactProfile(${c.id})">View Full Profile</button>
            </div>
        `;
    });
    el.innerHTML = html;
}

// ── Data Quality ────────────────────────────────────────────────────────────

async function loadDataQuality() {
    try {
        const status = await api('/api/status');
        const counts = status.counts || {};

        document.getElementById('quality-invalid-emails').textContent = counts.invalid_emails || 0;
        document.getElementById('quality-invalid-phones').textContent = counts.invalid_phones || 0;
        document.getElementById('quality-missing').textContent = counts.incomplete_records || 0;
        document.getElementById('quality-dupes').textContent = counts.duplicates || 0;

        // Fetch detailed data quality list
        const dq = await api('/api/dedup-rules');  // placeholder - will be implemented
        const dqList = document.getElementById('quality-detail-list');
        if (dq && dq.rows) {
            dqList.innerHTML = dq.rows.map(r => \`
                <div class="quality-row">
                    <span class="quality-field">${esc(r.field)}</span>
                    <span class="quality-status badge badge-${r.severity}">${r.status}</span>
                </div>
            \`).join('');
        } else {
            dqList.innerHTML = '<p>No detailed data quality data available</p>';
        }

    } catch (e) {
        console.error(e);
        document.getElementById('quality-detail-list').innerHTML = '<p>Error loading data quality details</p>';
    }
}

// ── History ─────────────────────────────────────────────────────────────────

async function loadHistory() {
    try {
        const runs = await api('/api/jobs/0');  // simplified
        const tbody = document.getElementById('historyBody');
        if (!runs || !runs.results) {
            tbody.innerHTML = '<tr><td colspan="4">No extraction history</td></tr>';
            return;
        }

        tbody.innerHTML = runs.results.map(r => `
            <tr>
                <td>${esc(r.file || 'unknown')}</td>
                <td>${r.status || 'unknown'}</td>
                <td>${r.contacts_found || 0}</td>
                <td>${r.processed_at || 'unknown'}</td>
            </tr>
        `).join('');
    } catch (e) {
        document.getElementById('historyBody').innerHTML = '<tr><td colspan="4">Error: ' + esc(e.message) + '</td></tr>';
    }
}

// ── Settings ────────────────────────────────────────────────────────────────

async function loadSettings() {
    try {
        const settings = await api('/api/settings');
        renderSettings(settings);
    } catch (e) {
        document.getElementById('providerChain').innerHTML = '<p>Error loading settings: ' + esc(e.message) + '</p>';
    }
}

function renderSettings(settings) {
    const providerChain = document.getElementById('providerChain');
    const chain = settings.chain || [];

    let html = '';
    chain.forEach((entry, i) => {
        html += `
            <div class="settings-row" style="margin-bottom: 12px;">
                <div style="display: flex; gap: 8px; align-items: center;">
                    <span style="flex: 1; min-width: 120px;">Provider:</span>
                    <input type="text" value="${esc(entry.provider || '')}" 
                           onchange="updateProviderSetting(${i}, 'provider', this.value)"
                           style="flex: 1; padding: 4px; font-size: 12px;">
                    <span style="margin-left: 8px; color: var(--color-muted);">Model:</span>
                    <input type="text" value="${esc(entry.model || '')}"
                           onchange="updateProviderSetting(${i}, 'model', this.value)"
                           style="flex: 1; padding: 4px; font-size: 12px;">
                </div>
                <div style="display: flex; gap: 8px; align-items: margin-top: 4px;">
                    <span>API Key:</span>
                    <input type="password" value="${esc(entry.api_key_set ? '********' : '')}"
                           onchange="updateProviderSetting(${i}, 'api_key', this.value)"
                           style="flex: 2; padding: 4px; font-size: 12px;">
                    <span style="margin-left: 8px;">${entry.enabled !== false ? '✓' : '✗'}</span>
                </div>
                <button class="btn btn-sm btn-danger" onclick="removeProviderSetting(${i})"
                        style="margin-top: 4px;">Remove</button>
            </div>
        `;
    });

    html += `
        <div class="settings-row" style="margin-top: 12px;">
            <button class="btn btn-sm" onclick="addProviderSetting()">Add Provider</button>
        </div>
    `;

    providerChain.innerHTML = html;
}

function addProviderSetting() {
    // Add empty provider entry
    const chain = window.CRM_SETTINGS_CHAIN || [];
    chain.push({ provider: '', model: '', api_key: '' });
    window.CRM_SETTINGS_CHAIN = chain;
    renderSettings(window.CRM_SETTINGS || {});
}

function updateProviderSetting(idx, field, value) {
    // Placeholder - would need to update settings via API
    console.log(`Update provider ${idx} ${field}: ${value}`);
}

function removeProviderSetting(idx) {
    // Placeholder
}

// ── Global search ────────────────────────────────────────────────────────────

async function globalSearch() {
    const q = document.getElementById('globalSearch').value;
    if (!q) return;
    // Simple search across views
    if (S.currentView === 'contacts') {
        searchContacts();
    } else if (S.currentView === 'emails') {
        // loadEmails already filters by search
    }
}

// ── Initialization ──────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    syncAuthSession();

    const dz = document.getElementById('dropZone');
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
    dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('drag'); handleFiles(e.dataTransfer.files); });

    // Initialize theme from localStorage
    const savedTheme = localStorage.getItem('crm-theme') || 'light';
    setTheme(savedTheme, true);

    // Restore sidebar collapsed state
    if (localStorage.getItem('crm-sb-collapsed') === '1') {
        document.body.classList.add('sb-collapsed');
        const btn = document.getElementById('sbToggleBtn');
        if (btn) btn.innerHTML = '›';
    }

    // Populate sidebar user info
    try {
        const session = JSON.parse(localStorage.getItem('crm-session') || '{}');
        S.userEmail = session.email || null;
    } catch(e) {}

    // Show view from hash
    const hash = location.hash.replace('#/', '').replace('#', '');
    if (hash) showView(hash);
});

// ── Staged Contacts Workflow ────────────────────────────────────────────────

/**
 * Load staged contacts for review/approval
 */
async function loadStagedContacts(page) {
    try {
        const data = await api(`/api/staged-contacts?page=${page || 1}&size=${S.stagedPageSize || 20}`);
        renderStagedContactsTable(data.rows || [], data.total, data.page, data.pageSize, (p) => {
            S.stagedReviewPage = p;
            loadStagedContacts(p);
        });
    } catch (e) {
        document.getElementById('stagedContactsBody').innerHTML = '<tr><td colspan="8">Error: ' + esc(e.message) + '</td></tr>';
    }
}

/**
 * Render staged contacts table with action buttons
 */
function renderStagedContactsTable(staged, total, page, pageSize, onPageChange) {
    const el = document.getElementById('stagedContactsBody');
    if (!staged || staged.length === 0) {
        el.innerHTML = '<tr><td colspan="8">No staged contacts awaiting review</td></tr>';
        return;
    }

    let html = '';
    staged.forEach(sc => {
        const reviewStatus = sc.review_status || 'NEW';
        const dedupStatus = sc.dedup_status || 'NOT_CHECKED';
        const importStatus = sc.import_status || 'NOT_IMPORTED';
        const confidence = sc.confidence !== undefined ? sc.confidence : '—';

        // Determine badge classes
        let reviewBadge = '';
        let dedupBadge = '';
        let importBadge = '';

        switch (reviewStatus) {
            case 'NEW': reviewBadge = `<span class="badge badge-neutral">New</span>`; break;
            case 'NEEDS_REVIEW': reviewBadge = `<span class="badge badge-warning">Needs Review</span>`; break;
            case 'READY': reviewBadge = `<span class="badge badge-success">Ready</span>`; break;
            case 'APPROVED': reviewBadge = `<span class="badge badge-success">Approved</span>`; break;
            case 'REJECTED': reviewBadge = `<span class="badge badge-error">Rejected</span>`; break;
            case 'DISMISSED': reviewBadge = `<span class="badge badge-neutral">Dismissed</span>`; break;
        }

        switch (dedupStatus) {
            case 'NOT_CHECKED': dedupBadge = `<span class="badge badge-neutral">Not Checked</span>`; break;
            case 'UNIQUE': dedupBadge = `<span class="badge badge-success">Unique</span>`; break;
            case 'EXACT_DUPLICATE': dedupBadge = `<span class="badge badge-error">Exact Duplicate</span>`; break;
            case 'PROBABLE_DUPLICATE': dedupBadge = `<span class="badge badge-warning">Probable Duplicate</span>`; break;
            case 'CONFLICT': dedupBadge = `<span class="badge badge-error">Conflict</span>`; break;
        }

        switch (importStatus) {
            case 'NOT_IMPORTED': importBadge = `<span class="badge badge-neutral">Not Imported</span>`; break;
            case 'NEW_CONTACT_CREATED': importBadge = `<span class="badge badge-success">New Contact</span>`; break;
            case 'EXISTING_CONTACT_ENRICHED': importBadge = `<span class="badge badge-warning">Existing Contact</span>`; break;
            case 'IMPORT_FAILED': importBadge = `<span class="badge badge-error">Import Failed</span>`; break;
        }

        html += `
            <tr>
                <td>${esc(sc.name || '')}</td>
                <td>${esc(sc.email || '')}</td>
                <td>${esc(sc.phone_primary || '')}</td>
                <td>${esc(sc.company || '')}</td>
                <td>${reviewBadge}</td>
                <td>${dedupBadge}</td>
                <td>${importBadge}</td>
                <td>
                    <div class="action-buttons">
                        <button class="btn btn-sm" onclick="approveContact(${sc.id})"
                                title="Approve">${reviewStatus !== 'APPROVED' ? '✓' : '✓'}</button>
                        <button class="btn btn-sm btn-danger" onclick="rejectContact(${sc.id})"
                                title="Reject">${reviewStatus !== 'REJECTED' ? '✗' : '✗'}</button>
                        <button class="btn btn-sm" onclick="dismissContact(${sc.id})"
                                title="Dismiss">${reviewStatus !== 'DISMISSED' ? '—' : '—'}</button>
                        <button class="btn btn-sm" onclick="editStagedContact(${sc.id})"
                                title="Edit">✎</button>
                    </div>
                </td>
            </tr>
        `;
    });

    el.innerHTML = html;

    // Render pagination
    renderStagedPagination(total, page, pageSize, onPageChange);
}

/**
 * Render staged contacts pagination
 */
function renderStagedPagination(total, page, pageSize, onPageChange) {
    const el = document.getElementById('stagedPagination');
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (totalPages <= 1) { el.innerHTML = ''; return; }

    let html = '';
    html += `<button ${page === 1 ? 'disabled' : ''} onclick="S.page=1; loadStagedContacts(1)" aria-label="First">«</button>`;
    html += `<button ${page === 1 ? 'disabled' : ''} onclick="S.page=${page - 1}; loadStagedContacts(${page - 1)}" aria-label="Prev">‹</button>`;

    const maxVisible = 5;
    let start = Math.max(1, page - Math.floor(maxVisible / 2));
    let end = Math.min(totalPages, start + maxVisible - 1);
    start = Math.max(1, end - maxVisible + 1);

    for (let i = start; i <= end; i++) {
        html += `<button ${i === page ? 'class="active"' : ''} onclick="S.page=${i}; loadStagedContacts(${i})" aria-page="${i}">${i}</button>`;
    }

    html += `<button ${page === totalPages ? 'disabled' : ''} onclick="S.page=${page + 1}; loadStagedContacts(${page + 1)}" aria-label="Next">›</button>`;
    html += `<button ${page === totalPages ? 'disabled' : ''} onclick="S.page=${totalPages}; loadStagedContacts(${totalPages)}" aria-label="Last">»</button>`;

    el.innerHTML = html;
}

/**
 * Approve a staged contact (commit to CRM)
 */
async function approveContact(stagedId) {
    if (!confirm('Approve this contact and commit to CRM?')) return;
    try {
        const resp = await api(`/api/staged-contacts/${stagedId}/approve`, {
            method: 'POST',
        });
        loadStagedContacts();
        loadOverview();
        alert('Contact approved and committed to CRM.');
    } catch (e) {
        alert('Error approving contact: ' + e.message);
    }
}

/**
 * Reject a staged contact
 */
async function rejectContact(stagedId) {
    if (!confirm('Reject this contact?')) return;
    try {
        const resp = await api(`/api/staged-contacts/${stagedId}/reject`, {
            method: 'POST',
        });
        loadStagedContacts();
        alert('Contact rejected.');
    } catch (e) {
        alert('Error rejecting contact: ' + e.message);
    }
}

/**
 * Dismiss a staged contact
 */
async function dismissContact(stagedId) {
    if (!confirm('Dismiss this contact?')) return;
    try {
        const resp = await api(`/api/staged-contacts/${stagedId}/dismiss`, {
            method: 'POST',
        });
        loadStagedContacts();
        alert('Contact dismissed.');
    } catch (e) {
        alert('Error dismissing contact: ' + e.message);
    }
}

/**
 * Edit a staged contact's fields
 */
async function editStagedContact(stagedId) {
    const c = stagedContactsCache.find(x => x.id === stagedId);
    if (!c) return;
    const name = prompt('Name:', c.name || '');
    if (name === null) return;
    try {
        await api(`/api/staged-contacts/${stagedId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fields: { name: name } }),
        });
        loadStagedContacts();
    } catch (e) { alert('Error: ' + e.message); }
}

// Initialize staged contacts cache (populated on first load)
let stagedContactsCache = [];

// Load staged contacts on 'staged' view if hash includes it
const initialHash = location.hash.replace('#/', '').replace('#', '');
if (initialHash === 'staged') {
    loadStagedContacts();
} else if (initialHash === 'overview') {
    loadOverview();
}