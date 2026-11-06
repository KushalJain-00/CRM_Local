// CRM Local — Main Application JavaScript
const API = '';
let S = { contacts: [], emails: [], currentView: 'overview', page: 1, pageSize: 50, sort: 'id', dir: 'desc' };

// ── Navigation ──────────────────────────────────────────────────────────────
function showView(id) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const v = document.getElementById('view-' + id);
    if (v) v.classList.add('active');
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const nav = document.querySelector(`.nav-item[data-view="${id}"]`);
    if (nav) nav.classList.add('active');
    const titles = {overview:'Overview',extract:'Extract',contacts:'Contacts',emails:'Emails',profiles:'Customer Profiles',analytics:'Analytics',quality:'Data Quality',history:'History',settings:'Settings'};
    document.getElementById('topTitle').textContent = titles[id] || id;
    S.currentView = id;
    if (id === 'overview') loadOverview();
    if (id === 'contacts') loadContacts();
    if (id === 'emails') loadEmails();
    if (id === 'profiles') loadProfiles();
    if (id === 'analytics') loadAnalytics();
    if (id === 'quality') loadQuality();
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

// ── API helpers ─────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
    const resp = await fetch(API + path, opts);
    if (!resp.ok) throw new Error(`API ${resp.status}: ${await resp.text()}`);
    return resp.json();
}

async function refreshData() {
    if (S.currentView === 'overview') loadOverview();
    if (S.currentView === 'contacts') loadContacts();
    if (S.currentView === 'emails') loadEmails();
}

// ── Overview ────────────────────────────────────────────────────────────────
async function loadOverview() {
    try {
        const status = await api('/api/status');
        const counts = status.counts || {};
        document.getElementById('kpi-contacts').textContent = counts.crm || 0;
        document.getElementById('kpi-emails').textContent = counts.emails || 0;
        document.getElementById('kpi-files').textContent = counts.processed_files || counts.crm || 0;
        document.getElementById('kpi-new').textContent = counts.new || 0;
        document.getElementById('kpi-dupes').textContent = counts.duplicates || 0;
        const total = (counts.crm || 0) + (counts.eml_contacts || 0);
        const withEmail = total; // simplified
        document.getElementById('kpi-completeness').textContent = total > 0 ? Math.round((withEmail / total) * 100) + '%' : '0%';
        document.getElementById('recent-activity').innerHTML = '<p>Status loaded. Contacts: ' + (counts.crm || 0) + ', Emails: ' + (counts.emails || 0) + '</p>';
    } catch (e) {
        document.getElementById('recent-activity').innerHTML = '<p>Error loading data: ' + e.message + '</p>';
    }
}

// ── Universal Extract ───────────────────────────────────────────────────────
let fileQueue = [];

function handleDrop(e) {
    e.preventDefault();
    handleFiles(e.dataTransfer.files);
}

function handleFiles(files) {
    for (const f of files) {
        fileQueue.push(f);
    }
    renderQueue();
    document.getElementById('extractBtn').disabled = fileQueue.length === 0;
}

function renderQueue() {
    const el = document.getElementById('fileQueue');
    el.innerHTML = fileQueue.map((f, i) => `<div class="queue-item">${f.name} (${(f.size/1024).toFixed(1)}KB) <button onclick="removeFromQueue(${i})">✕</button></div>`).join('');
}

function removeFromQueue(i) {
    fileQueue.splice(i, 1);
    renderQueue();
    document.getElementById('extractBtn').disabled = fileQueue.length === 0;
}

function clearQueue() {
    fileQueue = [];
    renderQueue();
    document.getElementById('extractBtn').disabled = true;
}

async function startExtraction() {
    if (fileQueue.length === 0) return;
    const btn = document.getElementById('extractBtn');
    btn.disabled = true;
    const progress = document.getElementById('progress');
    const fill = document.getElementById('progressFill');
    const text = document.getElementById('progressText');
    progress.style.display = 'block';
    const results = document.getElementById('extractResults');
    results.innerHTML = '';

    // Save files to temp and process via paths
    // For local mode, we use the file paths directly
    const paths = fileQueue.map(f => f.name);
    try {
        const resp = await api('/api/intake', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({paths: paths})
        });
        fill.style.width = '100%';
        text.textContent = resp.results.length + '/' + resp.results.length;
        results.innerHTML = resp.results.map(r =>
            `<div class="result-item ${r.status === 'OK' ? 'success' : 'error'}">${r.file}: ${r.status} (${r.contacts_found || 0} contacts) ${r.error || ''}</div>`
        ).join('');
        if (resp.counts) {
            results.innerHTML += `<div class="result-summary">New: ${resp.counts.new}, Merged: ${resp.counts.merged}, Skipped: ${resp.counts.skipped}, Errors: ${resp.counts.error}</div>`;
        }
    } catch (e) {
        results.innerHTML = '<div class="result-item error">Error: ' + e.message + '</div>';
    }
    btn.disabled = false;
    loadOverview();
}

// ── Contacts ────────────────────────────────────────────────────────────────
async function loadContacts() {
    try {
        const data = await api('/api/contacts?which=crm&page=' + S.page + '&size=' + S.pageSize);
        S.contacts = data.rows || [];
        renderContactsTable();
        renderPagination('contactsPagination', data.total, S.page, S.pageSize, (p) => { S.page = p; loadContacts(); });
    } catch (e) {
        document.getElementById('contactsBody').innerHTML = '<tr><td colspan="5">Error: ' + e.message + '</td></tr>';
    }
}

function renderContactsTable() {
    const tbody = document.getElementById('contactsBody');
    if (S.contacts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5">No contacts found</td></tr>';
        return;
    }
    tbody.innerHTML = S.contacts.map(c => `
        <tr>
            <td>${esc(c.name || '')}</td>
            <td>${esc(c.email_primary || '')}</td>
            <td>${esc(c.phone_primary || '')}</td>
            <td>${esc(c.company || '')}</td>
            <td>
                <button class="btn btn-sm" onclick="editContact(${c.id})">Edit</button>
                <button class="btn btn-sm btn-danger" onclick="deleteContact(${c.id})">Delete</button>
            </td>
        </tr>
    `).join('');
}

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

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
    await api('/api/contacts/crm/' + id, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({fields: {name: name}}) });
    loadContacts();
}

async function deleteContact(id) {
    if (!confirm('Delete this contact?')) return;
    await api('/api/contacts/crm/' + id, { method: 'DELETE' });
    loadContacts();
}

function renderPagination(elId, total, page, size, onPage) {
    const el = document.getElementById(elId);
    const pages = Math.ceil(total / size);
    let html = '';
    for (let i = 1; i <= pages; i++) {
        html += `<button class="btn btn-sm ${i === page ? 'active' : ''}" onclick="(${onPage.toString()})(${i})">${i}</button>`;
    }
    el.innerHTML = html;
}

// ── Emails ──────────────────────────────────────────────────────────────────
async function loadEmails() {
    try {
        const data = await api('/api/contacts?which=eml&page=' + S.page + '&size=' + S.pageSize);
        // Emails are in eml_contacts table; fetch via contacts endpoint with which=eml
        const emailData = await api('/api/status');
        document.getElementById('emailsBody').innerHTML = '<tr><td colspan="4">Email browser requires backend endpoint. See /api/contacts?which=eml</td></tr>';
    } catch (e) {
        document.getElementById('emailsBody').innerHTML = '<tr><td colspan="4">Error: ' + e.message + '</td></tr>';
    }
}

async function searchEmails() {
    const q = document.getElementById('emailSearch').value;
    // Delegate to loadEmails with search
    loadEmails();
}

// ── Customer Profiles ───────────────────────────────────────────────────────
async function loadProfiles() {
    try {
        const data = await api('/api/contacts?which=crm&page=1&size=100');
        const el = document.getElementById('profilesList');
        el.innerHTML = (data.rows || []).map(c => `
            <div class="profile-card">
                <h4>${esc(c.name || 'Unnamed')}</h4>
                <p>${esc(c.company || '')} | ${esc(c.email_primary || '')} | ${esc(c.phone_primary || '')}</p>
                <p class="muted">Source: ${esc(c.source_file || 'N/A')}</p>
            </div>
        `).join('') || '<p>No contacts found</p>';
    } catch (e) {
        document.getElementById('profilesList').innerHTML = '<p>Error: ' + e.message + '</p>';
    }
}

// ── Analytics ──────────────────────────────────────────────────────────────
async function loadAnalytics() {
    try {
        const data = await api('/api/contacts?which=crm&page=1&size=1000');
        const rows = data.rows || [];
        // Geographic
        const cities = {};
        rows.forEach(r => { if (r.city) cities[r.city] = (cities[r.city]||0)+1; });
        document.getElementById('chart-geo').innerHTML = Object.entries(cities).map(([k,v]) => `${k}: ${v}`).join('<br>') || 'No data';
        // Completeness
        const fields = ['name','email_primary','phone_primary','company','city'];
        const completeness = fields.map(f => {
            const filled = rows.filter(r => r[f]).length;
            return `${f}: ${rows.length ? Math.round(filled/rows.length*100) : 0}%`;
        });
        document.getElementById('chart-completeness').innerHTML = completeness.join('<br>');
        // Reachability
        const withEmail = rows.filter(r => r.email_primary).length;
        const withPhone = rows.filter(r => r.phone_primary).length;
        document.getElementById('chart-reachability').innerHTML = `Email: ${withEmail}/${rows.length} (${rows.length?Math.round(withEmail/rows.length*100):0}%)<br>Phone: ${withPhone}/${rows.length} (${rows.length?Math.round(withPhone/rows.length*100):0}%)`;
        // Sources
        const sources = {};
        rows.forEach(r => { const s = r.source_file || 'Unknown'; sources[s] = (sources[s]||0)+1; });
        document.getElementById('chart-sources').innerHTML = Object.entries(sources).map(([k,v]) => `${k}: ${v}`).join('<br>') || 'No data';
    } catch (e) {
        console.error(e);
    }
}

// ── Data Quality ────────────────────────────────────────────────────────────
async function loadQuality() {
    try {
        const data = await api('/api/contacts?which=crm&page=1&size=1000');
        const rows = data.rows || [];
        const invalidEmails = rows.filter(r => r.email_primary && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(r.email_primary));
        const invalidPhones = rows.filter(r => r.phone_primary && !/^\+?[\d\s\-()]{7,}$/.test(r.phone_primary));
        const missing = rows.filter(r => !r.name || !r.email_primary);
        const dupes = []; // simplified
        document.getElementById('quality-invalid-emails').innerHTML = invalidEmails.length + ' contacts with invalid emails' + (invalidEmails.length ? '<br>' + invalidEmails.map(r=>esc(r.name||r.email_primary)).join(', ') : '');
        document.getElementById('quality-invalid-phones').innerHTML = invalidPhones.length + ' contacts with invalid phones';
        document.getElementById('quality-missing').innerHTML = missing.length + ' contacts missing name or email';
        document.getElementById('quality-dupes').innerHTML = 'Duplicate detection: use Contacts view for manual review';
    } catch (e) {
        console.error(e);
    }
}

// ── History ─────────────────────────────────────────────────────────────────
async function loadHistory() {
    try {
        const data = await api('/api/status');
        document.getElementById('historyBody').innerHTML = '<tr><td colspan="4">Processing history available via /api/status. Files: ' + (data.counts?.processed_files || 0) + '</td></tr>';
    } catch (e) {
        document.getElementById('historyBody').innerHTML = '<tr><td colspan="4">Error: ' + e.message + '</td></tr>';
    }
}

// ── Settings ────────────────────────────────────────────────────────────────
async function loadSettings() {
    try {
        const cfg = await api('/api/config');
        document.getElementById('crmDir').value = cfg.crm_dir || '';
        document.getElementById('emlDir').value = cfg.eml_dir || '';
        document.getElementById('watchInterval').value = cfg.watch_interval || 30;
        document.getElementById('watchEnabled').checked = cfg.watch || false;
        document.getElementById('themeSelect').value = cfg.theme || 'light';
        // Provider chain
        const chain = cfg.chain || [];
        document.getElementById('providerChain').innerHTML = chain.map((e, i) =>
            `<div class="provider-entry">${e.provider} / ${e.model} ${e.enabled ? '✓' : '✗'} <button onclick="removeProvider(${i})">✕</button></div>`
        ).join('') || '<p>No providers configured</p>';
    } catch (e) {
        console.error(e);
    }
}

function addProvider() {
    const provider = prompt('Provider (openrouter/groq/openai/deepseek/anthropic/gemini/ollama):');
    if (!provider) return;
    const model = prompt('Model:');
    if (!model) return;
    const apiKey = prompt('API Key:');
    fetch('/api/config').then(r=>r.json()).then(cfg => {
        cfg.chain = cfg.chain || [];
        cfg.chain.push({provider, model, api_key: apiKey || '', base_url: '', enabled: true});
        fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(cfg)})
            .then(() => loadSettings());
    });
}

function removeProvider(i) {
    fetch('/api/config').then(r=>r.json()).then(cfg => {
        cfg.chain.splice(i, 1);
        fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(cfg)})
            .then(() => loadSettings());
    });
}

async function saveSettings() {
    const cfg = await api('/api/config');
    cfg.crm_dir = document.getElementById('crmDir').value;
    cfg.eml_dir = document.getElementById('emlDir').value;
    cfg.watch = document.getElementById('watchEnabled').checked;
    cfg.watch_interval = parseInt(document.getElementById('watchInterval').value) || 30;
    cfg.theme = document.getElementById('themeSelect').value;
    await api('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(cfg)});
    alert('Settings saved');
}

async function pickFolder(type) {
    const initial = type === 'crm' ? document.getElementById('crmDir').value : document.getElementById('emlDir').value;
    const resp = await api('/api/pick-folder', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({initial})});
    if (resp.path) {
        if (type === 'crm') document.getElementById('crmDir').value = resp.path;
        else document.getElementById('emlDir').value = resp.path;
    }
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
}

// ── Init ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    if (location.hash) {
        const view = location.hash.replace('#/', '').replace('#', '');
        showView(view || 'overview');
    } else {
        showView('overview');
    }
});