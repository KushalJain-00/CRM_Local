// ═══════════════════════════════════════════════════════════════════════════
// CRM Local — redesigned front-end logic ("quiet chrome, dense data")
// Vanilla JS, no dependencies, 100% offline.
// Contracts preserved: every /api/... endpoint, payload shape,
// window.CRM_API_BASE behavior, element IDs and inline-handler function names.
// ═══════════════════════════════════════════════════════════════════════════

const API_BASE = (window.CRM_API_BASE !== undefined ? window.CRM_API_BASE : '').replace(/\/$/, '');

const REDUCED = window.matchMedia ? matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

// ── State ────────────────────────────────────────────────────────────────────
const S = {
    currentView: 'overview',
    page: 1,
    pageSize: 50,
    contactsPage: 1,
    contactsPageSize: 50,
    emailsPage: 1,
    emailsPageSize: 50,
    sort: 'id',
    dir: 'desc',
    contacts: [],
    companies: [],
    emaills: [],   // legacy key kept for compatibility
    emails: [],
    extractionRunId: null,
    fileQueue: [],
    // Staged contact state
    stagedReviewPage: 1,
    stagedPageSize: 20,
    // Duplicate detection state
    dedupChecking: false,
    // Added by redesign (additive)
    contactsTotal: 0,
    contactsFiltered: [],
    profileContacts: [],
    emailsTotal: 0,
    historyRows: [],
    stagedCache: [],
    stagedTotal: 0,
    _kpiPrev: {},
};

let fileQueue = [];                    // [{file, status, error, progress, contactsFound}]
let stagedContactsCache = [];          // populated by loadStagedContacts (fixes old bug: was never filled)
let settingsWorking = null;            // working copy of settings.chain for editing
let settingsDirtyFlag = false;
let historySort = { key: 'processed_at', dir: 'desc' };
let emailsSort = { key: 'date', dir: 'desc' };
let stagedCursor = -1;                 // keyboard triage row index

// ── Helpers ──────────────────────────────────────────────────────────────────

function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function fmtInt(n) {
    if (n === null || n === undefined || n === '' || isNaN(Number(n))) return '—';
    return Number(n).toLocaleString();
}

function fmtBytes(n) {
    if (!n && n !== 0) return '';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / (1024 * 1024)).toFixed(1) + ' MB';
}

function fmtDateTime(s) {
    if (!s) return '—';
    const d = new Date(s);
    if (isNaN(d)) return String(s);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function relTime(s) {
    if (!s) return '';
    const d = new Date(s);
    if (isNaN(d)) return String(s);
    const diff = Date.now() - d.getTime();
    if (diff < 60e3) return 'just now';
    if (diff < 3600e3) return Math.floor(diff / 60e3) + 'm ago';
    if (diff < 86400e3) return Math.floor(diff / 3600e3) + 'h ago';
    if (diff < 7 * 86400e3) return Math.floor(diff / 86400e3) + 'd ago';
    return d.toLocaleDateString();
}

function initials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    return ((parts[0][0] || '') + (parts[1] ? parts[1][0] : '')).toUpperCase();
}

function debounce(fn, ms) {
    let t = null;
    return function (...args) { clearTimeout(t); t = setTimeout(() => fn.apply(this, args), ms); };
}

function csvCell(v) {
    let s = v === null || v === undefined ? '' : String(v);
    // SEC: sanitize spreadsheet formula triggers (=, +, -, @, tab, CR)
    // but preserve legitimate negative numbers
    if (/^[=+@\t\r]/.test(s) || (/^-/.test(s) && isNaN(Number(s)))) s = "'" + s;
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function downloadFile(name, text, mime) {
    try {
        const blob = new Blob([text], { type: mime || 'text/csv;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (e) { toast('Export failed: ' + e.message, { type: 'error' }); }
}

function showBanner(id, type, title, message) {
    const el = document.getElementById(id);
    if (!el) return;
    const icon = { error: 'i-alert-circle', info: 'i-info', success: 'i-check-circle' }[type] || 'i-info';
    el.className = 'banner ' + type;
    el.innerHTML = `<svg class="icon" aria-hidden="true"><use href="#${icon}"/></svg><div><strong>${esc(title)}</strong>${message ? ' — ' + esc(message) : ''}</div>`;
    el.hidden = false;
}

function hideBanner(id) {
    const el = document.getElementById(id);
    if (el) { el.hidden = true; el.innerHTML = ''; }
}

function emptyStateHTML({ icon = 'i-inbox', title, hint, ctaLabel, ctaFn }) {
    return `<div class="empty">
        <span class="empty-ic"><svg class="icon" aria-hidden="true"><use href="#${icon}"/></svg></span>
        <strong>${esc(title)}</strong>
        ${hint ? `<p>${esc(hint)}</p>` : ''}
        ${ctaLabel ? `<button type="button" class="btn btn-primary btn-sm" onclick="${ctaFn}">${esc(ctaLabel)}</button>` : ''}
    </div>`;
}

function skeletonRows(tbodyId, cols, rows) {
    const tb = document.getElementById(tbodyId);
    if (!tb) return;
    const n = rows || 8;
    let html = '';
    for (let r = 0; r < n; r++) {
        let tds = '';
        for (let i = 0; i < cols; i++) {
            const w = 24 + ((r * 17 + i * 29) % 52);
            tds += `<td><span class="skel" style="width:${w}%"></span></td>`;
        }
        html += `<tr class="skel-row">${tds}</tr>`;
    }
    tb.innerHTML = html;
}

function setBusy(btn, busy) {
    if (!btn) return;
    btn.classList.toggle('is-busy', !!busy);
    if (busy) btn.setAttribute('aria-busy', 'true'); else btn.removeAttribute('aria-busy');
}

// ── Toasts (role="status" region lives on #toasts) ───────────────────────────

function toast(message, opts) {
    opts = opts || {};
    const wrap = document.getElementById('toasts');
    if (!wrap) return;
    const type = opts.type || 'info';
    const icon = { success: 'i-check-circle', error: 'i-x-circle', info: 'i-info' }[type];
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.innerHTML =
        `<svg class="icon" aria-hidden="true"><use href="#${icon}"/></svg>` +
        `<div class="toast-body">` +
        (opts.title ? `<span class="toast-title">${esc(opts.title)}</span>` : '') +
        `<span class="toast-msg">${esc(message)}</span>` +
        (opts.actions && opts.actions.length ? `<div class="toast-actions"></div>` : '') +
        `</div>` +
        `<button type="button" class="toast-close" aria-label="Dismiss notification"><svg class="icon" aria-hidden="true"><use href="#i-x"/></svg></button>`;
    let timer = null;
    const dismiss = () => {
        clearTimeout(timer);
        el.classList.add('is-leaving');
        setTimeout(() => el.remove(), 260);
    };
    const arm = () => { timer = setTimeout(dismiss, opts.timeout != null ? opts.timeout : 4000); };
    const disarm = () => clearTimeout(timer);
    el.addEventListener('mouseenter', disarm);
    el.addEventListener('mouseleave', arm);
    el.querySelector('.toast-close').addEventListener('click', dismiss);
    if (opts.actions && opts.actions.length) {
        const box = el.querySelector('.toast-actions');
        opts.actions.forEach(a => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'btn-link';
            b.textContent = a.label;
            b.addEventListener('click', () => { if (a.onClick) a.onClick(); if (!a.keepOpen) dismiss(); });
            box.appendChild(b);
        });
    }
    wrap.appendChild(el);
    arm();
    return dismiss;
}

// ── Confirm dialog (native <dialog>: focus trap, Esc, focus restore) ─────────

function confirmDialog(opts) {
    opts = opts || {};
    const dlg = document.getElementById('confirmDialog');
    const title = opts.title || 'Are you sure?';
    const message = opts.message || '';
    const confirmLabel = opts.confirmLabel || 'Confirm';
    const danger = opts.danger !== false;
    if (!dlg || typeof dlg.showModal !== 'function') {
        return Promise.resolve(window.confirm(message ? title + '\n\n' + message : title));
    }
    return new Promise((resolve) => {
        const opener = document.activeElement;
        const ok = dlg.querySelector('#confirmOk');
        const cancel = dlg.querySelector('#confirmCancel');
        dlg.querySelector('#confirmTitle').textContent = title;
        dlg.querySelector('#confirmMessage').textContent = message;
        ok.textContent = confirmLabel;
        ok.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
        const ic = dlg.querySelector('.dialog-ic');
        if (ic) {
            ic.className = 'dialog-ic ' + (danger ? 'tone-warning' : 'tone-info');
            const use = ic.querySelector('use');
            if (use) use.setAttribute('href', danger ? '#i-alert-triangle' : '#i-info');
        }
        const done = (val) => {
            ok.removeEventListener('click', onOk);
            cancel.removeEventListener('click', onCancel);
            dlg.removeEventListener('cancel', onEsc);
            dlg.classList.add('is-closing');
            setTimeout(() => { dlg.close(); dlg.classList.remove('is-closing'); }, REDUCED.matches ? 0 : 160);
            if (opener && typeof opener.focus === 'function') opener.focus();
            resolve(val);
        };
        function onOk() { done(true); }
        function onCancel() { done(false); }
        function onEsc(e) { e.preventDefault(); done(false); }
        ok.addEventListener('click', onOk);
        cancel.addEventListener('click', onCancel);
        dlg.addEventListener('cancel', onEsc);
        dlg.showModal();
        ok.focus();
    });
}

// ── Theme management ─────────────────────────────────────────────────────────

function applyTheme(mode) {
    if (!['light', 'dark', 'system'].includes(mode)) mode = 'system';
    const resolved = mode === 'system'
        ? (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
        : mode;
    document.documentElement.setAttribute('data-theme', resolved);
    document.documentElement.setAttribute('data-theme-mode', mode);
    try {
        localStorage.setItem('crm-theme-mode', mode);
        localStorage.setItem('crm-theme', mode); // legacy key kept in sync
    } catch (e) { /* private mode */ }
    // sync Settings UI (hidden legacy select + segmented control)
    const sel = document.getElementById('themeSelect');
    if (sel) sel.value = mode;
    $$('input[name="theme-mode"]').forEach(r => { r.checked = r.value === mode; });
    const tt = document.getElementById('themeToggle');
    if (tt) tt.setAttribute('aria-label', 'Theme: ' + mode);
    window.dispatchEvent(new CustomEvent('crm:themechange', { detail: { mode, resolved } }));
}

// Legacy-compatible: setTheme('light'|'dark'|'system', persist)
function setTheme(theme, persist) {
    applyTheme(theme);
}

function cycleTheme() {
    const order = ['light', 'dark', 'system'];
    const cur = document.documentElement.getAttribute('data-theme-mode') || 'system';
    const next = order[(order.indexOf(cur) + 1) % order.length];
    applyTheme(next);
    toast('Theme: ' + next.charAt(0).toUpperCase() + next.slice(1), { type: 'info', timeout: 2200 });
}

// Auth session sync (placeholder - no auth in local mode)
function syncAuthSession() {}

// ── Navigation ───────────────────────────────────────────────────────────────

const VIEW_TITLES = {
    overview: 'Overview',
    extract: 'Universal Extract',
    staged: 'Staged review',
    contacts: 'Contacts',
    emails: 'Emails',
    profiles: 'Customer Profiles',
    analytics: 'Analytics',
    quality: 'Data Quality',
    history: 'History',
    settings: 'Settings',
};

function swapView(id) {
    $$('.view').forEach(v => v.classList.remove('active'));
    const v = document.getElementById('view-' + id);
    if (v) v.classList.add('active');
    $$('.nav-item').forEach(n => n.classList.remove('active'));
    const nav = document.querySelector(`.nav-item[data-view="${id}"]`);
    if (nav) nav.classList.add('active');
    document.getElementById('topTitle').textContent = VIEW_TITLES[id] || id;
    S.currentView = id;
    closeMobileSidebar();   // navigating always closes the off-canvas drawer
    if (id === 'overview') loadOverview();
    if (id === 'extract') renderFileQueue();
    if (id === 'contacts') loadContacts();
    if (id === 'staged') loadStagedContacts();
    if (id === 'emails') loadEmails();
    if (id === 'profiles') loadCustomerProfiles();
    if (id === 'analytics') loadAnalytics();
    if (id === 'quality') loadDataQuality();
    if (id === 'history') loadHistory();
    if (id === 'settings') loadSettings();
    const want = '#/' + id;
    if (location.hash !== want) location.hash = want;
}

function showView(id) {
    if (document.startViewTransition && !REDUCED.matches) {
        const vt = document.startViewTransition(() => swapView(id));
        const handleTransitionError = (error) => {
            if (error.name !== 'AbortError') console.error('View transition failed:', error);
        };
        if (vt && vt.ready && vt.ready.catch) vt.ready.catch(handleTransitionError);
        if (vt && vt.finished && vt.finished.catch) vt.finished.catch(handleTransitionError);
    } else {
        swapView(id);
    }
}

function toggleSidebar() {
    const mq = window.matchMedia && matchMedia('(max-width: 900px)');
    if (mq && mq.matches) {
        // mobile: the hamburger simply toggles the off-canvas drawer
        const open = document.body.classList.toggle('sb-open');
        const bd = document.getElementById('sidebarBackdrop');
        if (bd) bd.hidden = !open;
        const b = document.querySelector('.hamburger');
        if (b) b.setAttribute('aria-expanded', open ? 'true' : 'false');
        return;
    }
    // desktop: collapse/expand the rail
    const root = document.documentElement;
    const collapsed = root.classList.toggle('sb-collapsed');
    const sb = document.querySelector('.sidebar');
    if (sb) sb.classList.toggle('collapsed', collapsed); // legacy class kept in sync
    try { localStorage.setItem('crm-sb-collapsed', collapsed ? '1' : '0'); } catch (e) { /* ignore */ }
    const btn = document.getElementById('sbToggleBtn');
    if (btn) {
        btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        btn.setAttribute('data-tip', collapsed ? 'Expand' : 'Collapse');
    }
}

function closeMobileSidebar() {
    if (!document.body.classList.contains('sb-open')) return;
    document.body.classList.remove('sb-open');
    const bd = document.getElementById('sidebarBackdrop');
    if (bd) bd.hidden = true;
    const b = document.querySelector('.hamburger');
    if (b) b.setAttribute('aria-expanded', 'false');
}

window.addEventListener('hashchange', () => {
    const hash = location.hash.replace('#/', '').replace('#', '');
    if (hash && hash !== S.currentView) showView(hash);
});

async function refreshData() {
    const btn = document.getElementById('refreshBtn');
    setBusy(btn, true);
    try {
        await loadOverview();               // refresh KPIs + staged badge everywhere
        const loader = {
            overview: null, extract: null, contacts: loadContacts, staged: loadStagedContacts,
            emails: loadEmails, profiles: loadCustomerProfiles, analytics: loadAnalytics,
            quality: loadDataQuality, history: loadHistory, settings: loadSettings,
        }[S.currentView];
        if (loader) await loader();
    } catch (e) { /* loaders handle their own errors */ }
    finally { setBusy(btn, false); }
}

// ── API client (identical behavior: paths like '/api/...' appended to API_BASE) ─

let activeRequests = 0;
const MAX_CONCURRENT = 6;

async function api(path, opts = {}) {
    activeRequests++;
    if (activeRequests > MAX_CONCURRENT) {
        activeRequests--;
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
        activeRequests--;
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

function setKpi(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    if (typeof value !== 'number') { el.textContent = value; return; }
    const prev = S._kpiPrev[id];
    const paint = (v) => { el.textContent = fmtInt(Math.round(v)); };
    if (REDUCED.matches || prev === undefined || prev === value) {
        paint(value);
        S._kpiPrev[id] = value;
        return;
    }
    // count-up on first load only, ≤600ms
    const from = prev === undefined ? 0 : prev;
    const start = performance.now();
    const dur = 600;
    function tick(now) {
        const t = Math.min(1, (now - start) / dur);
        const eased = 1 - Math.pow(1 - t, 3);
        paint(from + (value - from) * eased);
        if (t < 1) requestAnimationFrame(tick); else S._kpiPrev[id] = value;
    }
    requestAnimationFrame(tick);
}

// Delta/sparkline support: only rendered when the API actually returns
// status.trends = { <key>: { delta: number, spark: number[] } }. Never fabricated.
const TREND_MAP = {
    contacts: { deltaEl: 'kpi-contacts-delta', sparkEl: 'kpi-contacts-spark', upIsGood: true },
    emails: { deltaEl: 'kpi-emails-delta', sparkEl: 'kpi-emails-spark', upIsGood: true },
    files: { deltaEl: 'kpi-files-delta', sparkEl: 'kpi-files-spark', upIsGood: true },
    new: { deltaEl: 'kpi-new-delta', sparkEl: 'kpi-new-spark', upIsGood: true },
    duplicates: { deltaEl: null, sparkEl: null, upIsGood: false },
};

function renderTrends(status) {
    const trends = status && status.trends;
    Object.keys(TREND_MAP).forEach(key => {
        const cfg = TREND_MAP[key];
        const t = trends && trends[key];
        if (cfg.deltaEl) {
            const el = document.getElementById(cfg.deltaEl);
            if (el) {
                if (t && typeof t.delta === 'number' && t.delta !== 0) {
                    const up = t.delta > 0;
                    const good = up === cfg.upIsGood;
                    el.className = 'kpi-delta ' + (good ? 'good' : 'bad');
                    el.innerHTML = `<svg class="icon" aria-hidden="true"><use href="#${up ? 'i-arrow-up' : 'i-arrow-down'}"/></svg>${Math.abs(t.delta)}%`;
                    el.hidden = false;
                    el.setAttribute('aria-label', `${Math.abs(t.delta)}% ${up ? 'higher' : 'lower'} than previous period`);
                } else { el.hidden = true; el.innerHTML = ''; }
            }
        }
        if (cfg.sparkEl) {
            const svg = document.getElementById(cfg.sparkEl);
            if (svg) {
                if (t && Array.isArray(t.spark) && t.spark.length > 1) { renderSpark(svg, t.spark); svg.hidden = false; }
                else { svg.hidden = true; svg.innerHTML = ''; }
            }
        }
    });
}

function renderSpark(svg, values) {
    const w = 72, h = 20, pad = 2;
    const min = Math.min(...values), max = Math.max(...values);
    const range = max - min || 1;
    const pts = values.map((v, i) => {
        const x = pad + (i / (values.length - 1)) * (w - pad * 2);
        const y = h - pad - ((v - min) / range) * (h - pad * 2);
        return [x.toFixed(1), y.toFixed(1)];
    });
    const last = pts[pts.length - 1];
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    svg.innerHTML =
        `<polyline points="${pts.map(p => p.join(',')).join(' ')}" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round"/>` +
        `<circle cx="${last[0]}" cy="${last[1]}" r="2" fill="var(--accent)" stroke-dasharray="1 1.4" stroke-width="1"/>`;
}

function updateStagedBadge(counts) {
    const badge = document.getElementById('staged-badge');
    if (!badge) return;
    const n = counts ? firstCount(counts, ['staged', 'staged_pending', 'staged_awaiting_review', 'pending_review']) : null;
    if (typeof n === 'number' && n > 0) {
        badge.textContent = fmtInt(n);
        badge.hidden = false;
    } else {
        badge.hidden = true;
    }
}

function firstCount(counts, keys) {
    for (const k of keys) {
        if (counts[k] !== undefined && counts[k] !== null) return Number(counts[k]);
    }
    return null;
}

function renderAttention(counts) {
    const defs = [
        { el: 'attention-staged', countEl: 'kpi-staged', keys: ['staged', 'staged_pending', 'staged_awaiting_review', 'pending_review'] },
        { el: 'attention-invalid-emails', countEl: 'kpi-dupes-att-emails', keys: ['invalid_emails'] },
        { el: 'attention-duplicates', countEl: 'kpi-dupes', keys: ['duplicates'] },
        { el: 'attention-missing', countEl: 'kpi-att-missing', keys: ['incomplete_records'] },
    ];
    let anyShown = false, anyZero = true;
    defs.forEach(d => {
        const item = document.getElementById(d.el);
        if (!item) return;
        const n = firstCount(counts || {}, d.keys);
        if (typeof n === 'number') {
            item.hidden = false;
            const c = document.getElementById(d.countEl);
            if (c) c.textContent = fmtInt(n);
            anyShown = true;
            if (n > 0) anyZero = false;
        } else {
            item.hidden = true;
        }
    });
    const empty = document.getElementById('attentionEmpty');
    if (empty) empty.hidden = !(anyShown && anyZero);
}

async function renderActivity(status) {
    const list = document.getElementById('recent-activity');
    if (!list) return;
    let items = [];
    const run = (status && status.run) || {};
    if (run.extraction_run_id) {
        items.push(`<li><span class="activity-ic tone-info"><svg class="icon" aria-hidden="true"><use href="#i-sparkle"/></svg></span>
            <span class="activity-text">Last extraction run <strong>${esc(run.status || 'completed')}</strong></span>
            <span class="activity-time">${esc(run.finished_at ? relTime(run.finished_at) : '')}</span></li>`);
    }
    try {
        const jobs = await api('/api/history');
        const results = (jobs && jobs.results) || [];
        results.slice(0, 5).forEach(r => {
            const ok = String(r.status || '').toUpperCase() === 'OK';
            items.push(`<li><span class="activity-ic ${ok ? 'tone-success' : 'tone-danger'}"><svg class="icon" aria-hidden="true"><use href="#${ok ? 'i-file-text' : 'i-alert-circle'}"/></svg></span>
                <span class="activity-text">Processed <strong title="${esc(r.file || '')}">${esc(r.file || 'unknown file')}</strong> — ${esc(r.status || 'unknown')}${r.contacts_found ? `, ${fmtInt(r.contacts_found)} contacts` : ''}</span>
                <span class="activity-time">${esc(relTime(r.processed_at))}</span></li>`);
        });
    } catch (e) { /* history timeline is optional for the feed */ }
    list.innerHTML = items.length ? items.join('') :
        `<li>${emptyStateHTML({ icon: 'i-clock', title: 'No activity yet', hint: 'Extract your first file to see it here.', ctaLabel: 'Go to Extract', ctaFn: "showView('extract')" })}</li>`;
}

async function loadOverview() {
    try {
        const status = await api('/api/status');
        const counts = status.counts || {};

        setKpi('kpi-contacts', Number(counts.crm || 0));
        setKpi('kpi-emails', Number(counts.emails || 0));
        setKpi('kpi-files', Number(counts.processed_files || 0));
        setKpi('kpi-new', Number(counts.new || 0));

        // Data completeness — computed only from fields the API actually returns.
        const total = (Number(counts.crm) || 0) + (Number(counts.eml_contacts) || 0);
        const incomplete = counts.incomplete_records;
        if (incomplete !== undefined && incomplete !== null && total > 0) {
            const completeness = Math.max(0, Math.round(((total - Number(incomplete)) / total) * 100));
            setKpi('kpi-completeness', completeness + '%');
            const note = document.getElementById('kpi-completeness-note');
            if (note) note.textContent = fmtInt(incomplete) + ' records missing fields';
        } else if (total > 0) {
            setKpi('kpi-completeness', '—');
        } else {
            setKpi('kpi-completeness', 0);
        }

        renderTrends(status);
        renderAttention(counts);
        updateStagedBadge(counts);
        await renderActivity(status);
        S.extractionRunId = (status.run && status.run.extraction_run_id) || null;
        hideBanner('contactsBanner');
    } catch (e) {
        ['kpi-contacts', 'kpi-emails', 'kpi-files', 'kpi-new', 'kpi-completeness'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = '—';
        });
        const act = document.getElementById('recent-activity');
        if (act) {
            act.innerHTML = `<li><div class="banner error" style="flex:1"><svg class="icon" aria-hidden="true"><use href="#i-alert-circle"/></svg>
                <div><strong>Could not reach the local API.</strong> Make sure the CRM Local service is running, then press Refresh. (${esc(e.message)})</div></div></li>`;
        }
    }
}

// ── Extract ──────────────────────────────────────────────────────────────────

const ACCEPT_EXTS = ['xlsx', 'xls', 'csv', 'pdf', 'txt', 'eml'];

function fileExt(name) {
    const m = String(name || '').toLowerCase().match(/\.([a-z0-9]+)$/);
    return m ? m[1] : '';
}

function fileIcon(name) {
    const ext = fileExt(name);
    if (ext === 'xlsx' || ext === 'xls' || ext === 'csv') return 'i-file-sheet';
    if (ext === 'eml') return 'i-mail';
    return 'i-file-text';
}

function handleDrop(e) {
    e.preventDefault();
    const dz = document.getElementById('dropZone');
    if (dz) dz.classList.remove('drag');
    if (e.dataTransfer && e.dataTransfer.files) handleFiles(e.dataTransfer.files);
}

function handleFiles(files) {
    const list = Array.from(files || []);
    if (!list.length) return;
    for (const f of list) {
        const ext = fileExt(f.name);
        const supported = ACCEPT_EXTS.includes(ext);
        fileQueue.push({
            file: f,
            status: supported ? 'queued' : 'failed',
            error: supported ? '' : `Unsupported file type (.${ext || 'none'}). Accepted: XLSX, XLS, CSV, PDF, TXT, EML.`,
            progress: 0,
            contactsFound: null,
        });
    }
    renderFileQueue();
    syncExtractButtons();
    const rejected = list.filter(f => !ACCEPT_EXTS.includes(fileExt(f.name))).length;
    if (rejected) toast(`${rejected} file${rejected > 1 ? 's' : ''} skipped — unsupported type.`, { type: 'error' });
}

function syncExtractButtons() {
    const btn = document.getElementById('extractBtn');
    if (btn) btn.disabled = !fileQueue.some(q => q.status === 'queued');
    const summary = document.getElementById('queueSummary');
    if (summary) {
        const n = fileQueue.length;
        const bytes = fileQueue.reduce((a, q) => a + (q.file.size || 0), 0);
        summary.textContent = n ? `${n} file${n > 1 ? 's' : ''} · ${fmtBytes(bytes)}` : '';
    }
}

function renderFileQueue() {
    const el = document.getElementById('fileQueue');
    if (!el) return;
    if (!fileQueue.length) { el.innerHTML = ''; syncExtractButtons(); return; }
    el.innerHTML = fileQueue.map((q, i) => {
        const statusBadge = {
            queued: '<span class="badge badge-neutral">Queued</span>',
            processing: '<span class="badge badge-info">Processing…</span>',
            done: '<span class="badge badge-success"><svg class="icon" aria-hidden="true"><use href="#i-check"/></svg>Done</span>',
            failed: '<span class="badge badge-error"><svg class="icon" aria-hidden="true"><use href="#i-alert-circle"/></svg>Failed</span>',
        }[q.status] || '';
        const actions = [];
        if (q.status === 'failed' && ACCEPT_EXTS.includes(fileExt(q.file.name))) {
            actions.push(`<button type="button" class="row-btn" title="Retry" aria-label="Retry ${esc(q.file.name)}" onclick="retryFile(${i})"><svg class="icon" aria-hidden="true"><use href="#i-rotate"/></svg></button>`);
        }
        actions.push(`<button type="button" class="row-btn danger" title="Remove" aria-label="Remove ${esc(q.file.name)}" onclick="removeFromQueue(${i})"><svg class="icon" aria-hidden="true"><use href="#i-x"/></svg></button>`);
        return `<div class="queue-item is-${q.status}" data-idx="${i}">
            <svg class="icon q-ic" aria-hidden="true"><use href="#${fileIcon(q.file.name)}"/></svg>
            <span class="q-name" title="${esc(q.file.name)}">${esc(q.file.name)}</span>
            <span class="q-size">${fmtBytes(q.file.size)}</span>
            ${statusBadge}
            <span class="q-actions">${actions.join('')}</span>
            ${q.status === 'processing' || (q.status === 'done' && q.progress < 100) ? `<span class="q-progress"><span class="q-progress-fill" style="width:${q.progress || 0}%"></span></span>` : ''}
            ${q.contactsFound != null && q.status === 'done' ? `<span class="q-error" style="color:var(--text-secondary)">${fmtInt(q.contactsFound)} contacts found</span>` : ''}
            ${q.error ? `<span class="q-error">${esc(q.error)}</span>` : ''}
        </div>`;
    }).join('');
    syncExtractButtons();
}

function removeFromQueue(i) {
    const removed = fileQueue[i];
    fileQueue.splice(i, 1);
    renderFileQueue();
    if (removed) {
        toast(`${removed.file.name} removed from queue`, {
            type: 'info', timeout: 5000,
            actions: [{ label: 'Undo', onClick: () => { fileQueue.splice(Math.min(i, fileQueue.length), 0, removed); renderFileQueue(); } }],
        });
    }
}

function clearQueue() {
    if (!fileQueue.length) return;
    const prev = fileQueue;
    fileQueue = [];
    renderFileQueue();
    toast('Queue cleared', {
        type: 'info', timeout: 5000,
        actions: [{ label: 'Undo', onClick: () => { fileQueue = prev; renderFileQueue(); } }],
    });
}

async function retryFile(i) {
    const q = fileQueue[i];
    if (!q) return;
    q.status = 'processing'; q.error = ''; q.progress = 0;
    renderFileQueue();
    try {
        const fd = new FormData();
        fd.append('files', q.file);
        const resp = await apiFormData('/api/intake', fd);
        const r = (resp.results && resp.results[0]) || {};
        q.status = r.status === 'OK' ? 'done' : 'failed';
        q.error = r.error || '';
        q.contactsFound = r.contacts_found != null ? r.contacts_found : null;
        q.progress = 100;
    } catch (e) {
        q.status = 'failed';
        q.error = e.message;
    }
    renderFileQueue();
    loadOverview();
}

async function startExtraction() {
    const valid = fileQueue.filter(q => q.status === 'queued');
    if (!valid.length) return;
    const btn = document.getElementById('extractBtn');
    const progress = document.getElementById('progress');
    const fill = document.getElementById('progressFill');
    const text = document.getElementById('progressText');
    const results = document.getElementById('extractResults');
    const dz = document.getElementById('dropZone');
    btn.disabled = true;
    if (dz) dz.classList.add('is-disabled');
    results.innerHTML = '';
    progress.hidden = false;
    fill.style.width = '0%';
    text.textContent = `0/${valid.length}`;
    valid.forEach(q => { q.status = 'processing'; });
    renderFileQueue();

    try {
        const fd = new FormData();
        valid.forEach(q => fd.append('files', q.file));
        const resp = await apiFormData('/api/intake', fd);

        const respResults = (resp && resp.results) || [];
        let okCount = 0, failCount = 0;
        valid.forEach((q, idx) => {
            const r = respResults.find(x => (x.file || '') === q.file.name) || respResults[idx] || {};
            const ok = String(r.status || '').toUpperCase() === 'OK';
            q.status = ok ? 'done' : 'failed';
            q.error = r.error || (ok ? '' : r.status || 'Extraction failed');
            q.contactsFound = r.contacts_found != null ? r.contacts_found : null;
            q.progress = 100;
            if (ok) okCount++; else failCount++;
        });

        fill.style.width = '100%';
        text.textContent = `${okCount + failCount}/${valid.length}`;

        results.innerHTML =
            respResults.map(r => {
                const ok = String(r.status || '').toUpperCase() === 'OK';
                return `<div class="result-item ${ok ? 'success' : 'error'}">
                    <svg class="icon" aria-hidden="true"><use href="#${ok ? 'i-check-circle' : 'i-x-circle'}"/></svg>
                    <span><strong>${esc(r.file || '')}</strong>: ${esc(r.status || '')} (${fmtInt(r.contacts_found || 0)} contacts)${r.error ? ' — ' + esc(r.error) : ''}</span>
                </div>`;
            }).join('') +
            (resp.counts ? `<div class="result-summary">New: ${fmtInt(resp.counts.new)} · Merged: ${fmtInt(resp.counts.merged)} · Skipped: ${fmtInt(resp.counts.skipped)} · Errors: ${fmtInt(resp.counts.error)}</div>` : '') +
            `<div class="actions"><button type="button" class="btn-link" onclick="showView('staged')">Review staged contacts →</button></div>`;

        toast(`${okCount} file${okCount === 1 ? '' : 's'} extracted${failCount ? `, ${failCount} failed` : ''}`, { type: failCount ? 'error' : 'success' });
        renderFileQueue();
        loadOverview();
    } catch (e) {
        valid.forEach(q => { q.status = 'failed'; q.error = e.message; });
        results.innerHTML = `<div class="result-item error">
            <svg class="icon" aria-hidden="true"><use href="#i-x-circle"/></svg>
            <span><strong>Extraction failed.</strong> ${esc(e.message)} — check that the local service is running, then try again.</span>
        </div>`;
        renderFileQueue();
    } finally {
        btn.disabled = false;
        if (dz) dz.classList.remove('is-disabled');
        syncExtractButtons();
    }
}

// ── Contacts ────────────────────────────────────────────────────────────────

async function loadContacts() {
    hideBanner('contactsBanner');
    skeletonRows('contactsBody', 6);
    try {
        const data = await api('/api/contacts?page=' + S.contactsPage + '&size=' + S.contactsPageSize + '&sort=' + encodeURIComponent(S.sort) + '&dir=' + S.dir);
        S.contacts = data.rows || [];
        S.contactsTotal = data.total != null ? Number(data.total) : S.contacts.length;
        S.page = S.contactsPage; S.pageSize = S.contactsPageSize;
        applyContactFilter();
        renderPagination('contactsPagination', S.contactsTotal, S.contactsPage, S.contactsPageSize, (p) => {
            S.contactsPage = p; S.page = p;
            loadContacts();
        });
        const info = document.getElementById('contactsInfo');
        if (info) info.textContent = paginationInfo(S.contactsTotal, S.contactsPage, S.contactsPageSize);
    } catch (e) {
        showBanner('contactsBanner', 'error', 'Could not load contacts', e.message + ' — check that the local service is running.');
        document.getElementById('contactsBody').innerHTML =
            `<tr><td colspan="6">${emptyStateHTML({ icon: 'i-alert-circle', title: 'Contacts unavailable', hint: 'The API did not answer. Press Refresh once the service is up.' })}</td></tr>`;
    }
}

function applyContactFilter() {
    const f = (document.getElementById('contactFilter') || {}).value || '';
    let rows = S.contacts;
    if (f === 'has_email') rows = rows.filter(c => c.email_primary);
    else if (f === 'has_phone') rows = rows.filter(c => c.phone_primary);
    else if (f === 'no_company') rows = rows.filter(c => !c.company);
    S.contactsFiltered = rows;
    renderContactsTable();
}

function renderContactsTable() {
    const tbody = document.getElementById('contactsBody');
    if (!tbody) return;
    const rows = S.contactsFiltered;
    if (!rows.length) {
        const searched = (document.getElementById('contactSearch') || {}).value;
        tbody.innerHTML = `<tr><td colspan="6">${emptyStateHTML({
            icon: 'i-users',
            title: searched ? 'No contacts match' : 'No contacts yet',
            hint: searched ? 'Try a different search term, or clear the filter.' : 'Extract a spreadsheet or mailbox to fill your CRM.',
            ctaLabel: searched ? null : 'Go to Extract',
            ctaFn: "showView('extract')",
        })}</td></tr>`;
        updateBulkBar();
        return;
    }
    tbody.innerHTML = rows.map(c => {
        const name = c.name || '(no name)';
        return `<tr data-id="${c.id}">
            <td class="c-check"><input type="checkbox" class="row-check" data-id="${c.id}" aria-label="Select ${esc(name)}"></td>
            <td class="c-name"><span class="name-cell"><span class="avatar" aria-hidden="true">${esc(initials(name))}</span><span class="cell" title="${esc(name)}">${esc(name)}</span></span></td>
            <td class="c-email"><span class="cell mono" title="${esc(c.email_primary || '')}">${esc(c.email_primary || '—')}</span></td>
            <td class="c-phone"><span class="cell mono" title="${esc(c.phone_primary || '')}">${esc(c.phone_primary || '—')}</span></td>
            <td class="c-company"><span class="cell" title="${esc(c.company || '')}">${esc(c.company || '—')}</span></td>
            <td class="c-actions"><span class="row-actions">
                <button type="button" class="row-btn" title="Open profile" aria-label="Open profile of ${esc(name)}" onclick="viewContactProfile(${c.id})"><svg class="icon" aria-hidden="true"><use href="#i-eye"/></svg></button>
                <button type="button" class="row-btn" title="Edit" aria-label="Edit ${esc(name)}" onclick="editContact(${c.id})"><svg class="icon" aria-hidden="true"><use href="#i-pencil"/></svg></button>
                <button type="button" class="row-btn danger" title="Delete" aria-label="Delete ${esc(name)}" onclick="deleteContact(${c.id})"><svg class="icon" aria-hidden="true"><use href="#i-trash"/></svg></button>
            </span></td>
        </tr>`;
    }).join('');
    updateBulkBar();
}

let _searchTimer = null;
async function searchContacts() {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(async () => { await _searchContactsNow(); }, 250);
}
async function _searchContactsNow() {
    const q = ((document.getElementById('contactSearch') || {}).value || '');
    try {
        const data = await api('/api/contacts?q=' + encodeURIComponent(q) + '&page=1&size=' + S.contactsPageSize + '&sort=' + encodeURIComponent(S.sort) + '&dir=' + S.dir);
        S.contacts = data.rows || [];
        S.contactsTotal = data.total != null ? Number(data.total) : S.contacts.length;
        S.contactsPage = 1; S.page = 1;
        applyContactFilter();
        renderPagination('contactsPagination', S.contactsTotal, 1, S.contactsPageSize, (p) => { S.contactsPage = p; S.page = p; loadContacts(); });
        const info = document.getElementById('contactsInfo');
        if (info) info.textContent = paginationInfo(S.contactsTotal, 1, S.contactsPageSize);
    } catch (e) { console.error(e); }
}

function filterContacts() {
    S.contactsPage = 1; S.page = 1;
    applyContactFilter();
    const info = document.getElementById('contactsInfo');
    if (info) info.textContent = paginationInfo(S.contactsTotal, S.contactsPage, S.contactsPageSize);
}

function sortContacts(field) {
    if (S.sort === field) S.dir = S.dir === 'asc' ? 'desc' : 'asc';
    else { S.sort = field; S.dir = 'asc'; }
    updateSortUI('contactsTable', field, S.dir);
    S.contactsPage = 1; S.page = 1;
    loadContacts();
}

function updateSortUI(tableId, activeField, dir) {
    const table = document.getElementById(tableId);
    if (!table) return;
    $$('th[aria-sort]', table).forEach(th => {
        const btn = th.querySelector('.th-btn');
        if (!btn) return;
        const field = btn.getAttribute('data-sort');
        const isIt = field === activeField;
        th.setAttribute('aria-sort', isIt ? (dir === 'asc' ? 'ascending' : 'descending') : 'none');
    });
}

function paginationInfo(total, page, size) {
    if (!total) return 'No rows';
    const from = (page - 1) * size + 1;
    const to = Math.min(total, page * size);
    return `Showing ${fmtInt(from)}–${fmtInt(to)} of ${fmtInt(total)}`;
}

function renderPagination(elId, total, page, size, onPage) {
    const el = document.getElementById(elId);
    if (!el) return;
    const totalPages = Math.max(1, Math.ceil((total || 0) / size));
    if (totalPages <= 1) { el.innerHTML = ''; return; }

    const maxVisible = 5;
    let start = Math.max(1, page - Math.floor(maxVisible / 2));
    let end = Math.min(totalPages, start + maxVisible - 1);
    start = Math.max(1, end - maxVisible + 1);

    const btn = (label, target, opts) => {
        opts = opts || {};
        return `<button type="button" ${opts.disabled ? 'disabled' : ''} data-page="${target}" aria-label="${opts.aria || 'Page ' + target}" class="${opts.active ? 'active' : ''}">${label}</button>`;
    };
    let html = '';
    html += btn('«', 1, { disabled: page === 1, aria: 'First page' });
    html += btn('‹', page - 1, { disabled: page === 1, aria: 'Previous page' });
    for (let i = start; i <= end; i++) html += btn(String(i), i, { active: i === page, aria: 'Page ' + i });
    html += btn('›', page + 1, { disabled: page === totalPages, aria: 'Next page' });
    html += btn('»', totalPages, { disabled: page === totalPages, aria: 'Last page' });
    el.innerHTML = html;

    $$('#' + elId + ' button[data-page]').forEach(b => {
        b.addEventListener('click', () => onPage(Number(b.dataset.page)));
    });
}

function changeContactsPageSize(v) {
    const n = Number(v) || 50;
    S.contactsPageSize = n; S.pageSize = n;
    S.contactsPage = 1; S.page = 1;
    loadContacts();
}

function exportContacts() {
    exportRowsCSV(S.contactsFiltered.length ? S.contactsFiltered : S.contacts, 'contacts.csv', 'contacts');
}

function exportRowsCSV(rows, filename, label) {
    if (!rows || !rows.length) { toast(`Nothing to export yet — no ${label} loaded.`, { type: 'info' }); return; }
    const header = ['ID', 'Name', 'Email', 'Phone', 'Company'];
    const lines = [header.join(',')];
    rows.forEach(c => {
        lines.push([
            c.id,
            c.name || '',
            c.email_primary || c.email || '',
            c.phone_primary || '',
            c.company || '',
        ].map(csvCell).join(','));
    });
    downloadFile(filename, '\ufeff' + lines.join('\r\n'));
    toast(`Exported ${fmtInt(rows.length)} ${label} to ${filename}`, { type: 'success' });
}

function getSelectedIds(scopeId) {
    return $$(`#${scopeId} .row-check:checked`).map(cb => Number(cb.dataset.id));
}

function updateBulkBar() {
    const bar = document.getElementById('contactsBulkbar');
    const count = document.getElementById('contactsBulkCount');
    if (!bar) return;
    const ids = getSelectedIds('contactsBody');
    if (count) count.textContent = `${ids.length} selected`;
    bar.hidden = ids.length === 0;   // :has() drives this too; kept for old browsers
    const all = document.getElementById('contactsCheckAll');
    if (all) {
        const boxes = $$('#contactsBody .row-check');
        all.checked = boxes.length > 0 && ids.length === boxes.length;
        all.indeterminate = ids.length > 0 && ids.length < boxes.length;
    }
}

async function deleteContact(id) {
    const c = S.contacts.find(x => x.id === id);
    const name = c && c.name ? `“${c.name}”` : 'this contact';
    const yes = await confirmDialog({
        title: 'Delete contact?',
        message: `${name} will be permanently removed from your CRM. This cannot be undone.`,
        confirmLabel: 'Delete',
    });
    if (!yes) return;
    try {
        await api('/api/contacts/' + id, { method: 'DELETE' });
        toast('Contact deleted', { type: 'success' });
        loadContacts();
        loadOverview();
    } catch (e) {
        toast('Could not delete contact: ' + e.message, { type: 'error' });
    }
}

async function deleteSelectedContacts() {
    const ids = getSelectedIds('contactsBody');
    if (!ids.length) return;
    const yes = await confirmDialog({
        title: `Delete ${ids.length} contact${ids.length > 1 ? 's' : ''}?`,
        message: 'The selected contacts will be permanently removed from your CRM. This cannot be undone.',
        confirmLabel: 'Delete',
    });
    if (!yes) return;
    let failed = 0;
    for (const id of ids) {
        try { await api('/api/contacts/' + id, { method: 'DELETE' }); }
        catch (e) { failed++; }
    }
    if (failed) toast(`${ids.length - failed} deleted, ${failed} failed`, { type: 'error' });
    else toast(`${ids.length} contact${ids.length > 1 ? 's' : ''} deleted`, { type: 'success' });
    loadContacts();
    loadOverview();
}

function exportSelectedContacts() {
    const ids = getSelectedIds('contactsBody');
    const rows = (S.contactsFiltered.length ? S.contactsFiltered : S.contacts).filter(c => ids.includes(c.id));
    exportRowsCSV(rows, 'contacts-selection.csv', 'selected contacts');
}

// ── Drawer (contact / staged detail) ─────────────────────────────────────────

let drawerOnClose = null;
let drawerOpener = null;

function openDrawer(html, opts) {
    opts = opts || {};
    const drawer = document.getElementById('drawer');
    if (!drawer) return;
    drawerOpener = document.activeElement;
    drawerOnClose = opts.onClose || null;
    document.getElementById('drawerTitle').textContent = opts.title || 'Details';
    document.getElementById('drawerSub').textContent = opts.sub || '';
    document.getElementById('drawerBody').innerHTML = html;
    drawer.hidden = false;
    requestAnimationFrame(() => requestAnimationFrame(() => drawer.classList.add('is-open')));
    const closeBtn = drawer.querySelector('[data-close-drawer].btn-icon');
    if (closeBtn) closeBtn.focus();
}

function closeDrawer() {
    const drawer = document.getElementById('drawer');
    if (!drawer || drawer.hidden) return;
    drawer.classList.remove('is-open');
    drawer.classList.add('is-closing');
    const finish = () => {
        drawer.classList.remove('is-closing');
        drawer.hidden = true;
        document.getElementById('drawerBody').innerHTML = '';
        if (drawerOnClose) { drawerOnClose(); drawerOnClose = null; }
        if (drawerOpener && typeof drawerOpener.focus === 'function') drawerOpener.focus();
        drawerOpener = null;
    };
    setTimeout(finish, REDUCED.matches ? 0 : 240);
}

function contactFormFields(c) {
    return `
        <label class="field">Name<input type="text" id="dF-name" value="${esc(c.name || '')}"></label>
        <label class="field">Email<input type="text" id="dF-email" class="mono" value="${esc(c.email_primary || c.email || '')}"></label>
        <label class="field">Phone<input type="text" id="dF-phone" class="mono" value="${esc(c.phone_primary || '')}"></label>
        <label class="field">Company<input type="text" id="dF-company" value="${esc(c.company || '')}"></label>`;
}

function provenanceHTML(obj) {
    const fields = [
        ['Source file', obj.source_file || obj.source],
        ['Sheet', obj.sheet],
        ['Row', obj.row_number],
        ['Extracted at', obj.extracted_at],
        ['Created', obj.created_at],
        ['Confidence', obj.confidence],
    ].filter(([, v]) => v !== undefined && v !== null && v !== '');
    if (!fields.length) return '';
    return `<div class="dsec"><h3>Provenance</h3><dl class="dgrid">
        ${fields.map(([k, v]) => `<dt>${esc(k)}</dt><dd class="mono">${esc(typeof v === 'number' ? fmtInt(v) : v)}</dd>`).join('')}
    </dl></div>`;
}

function contactCompleteness(c) {
    const fields = [c.name, c.email_primary || c.email, c.phone_primary, c.company];
    const filled = fields.filter(Boolean).length;
    return { filled, total: 4, pct: Math.round((filled / 4) * 100) };
}

function viewContactProfile(id, row) {
    let c = row || S.contacts.find(x => x.id === id) || (S.profileContacts || []).find(x => x.id === id) || stagedContactsCache.find(x => x.id === id);
    if (!c) { toast('Contact details are not loaded right now — open it from the Contacts list.', { type: 'info' }); return; }
    const comp = contactCompleteness(c);
    const name = c.name || '(no name)';
    const html = `
        <div class="dsec">
            <div class="profile-top">
                <span class="profile-avatar" aria-hidden="true">${esc(initials(name))}</span>
                <div><div class="profile-name">${esc(name)}</div><div class="profile-company">${esc(c.company || 'No company')}</div></div>
            </div>
            <div class="completeness">
                <span class="completeness-track"><span class="completeness-fill" style="width:${comp.pct}%"></span></span>
                <span class="completeness-label">${comp.pct}% complete</span>
            </div>
        </div>
        <div class="dsec"><h3>Contact details</h3><dl class="dgrid">
            <dt>Name</dt><dd>${esc(c.name || '—')}</dd>
            <dt>Email</dt><dd class="mono">${esc(c.email_primary || c.email || '—')}</dd>
            <dt>Phone</dt><dd class="mono">${esc(c.phone_primary || '—')}</dd>
            <dt>Company</dt><dd>${esc(c.company || '—')}</dd>
            <dt>ID</dt><dd class="mono">${esc(c.id)}</dd>
        </dl></div>
        ${provenanceHTML(c)}
        <div class="drawer-actions">
            <button type="button" class="btn btn-secondary btn-sm" onclick="closeDrawer(); editContact(${c.id})"><svg class="icon" aria-hidden="true"><use href="#i-pencil"/></svg>Edit</button>
            <button type="button" class="btn btn-danger btn-sm" onclick="closeDrawer(); deleteContact(${c.id})"><svg class="icon" aria-hidden="true"><use href="#i-trash"/></svg>Delete</button>
        </div>`;
    openDrawer(html, { title: 'Contact profile', sub: 'All data stays on this machine' });
}

async function editContact(id) {
    const c = S.contacts.find(x => x.id === id);
    if (!c) { toast('Contact not found in the loaded page.', { type: 'error' }); return; }
    const html = `
        <form class="drawer-form" id="drawerEditForm">
            ${contactFormFields(c)}
            <div class="drawer-actions">
                <button type="button" class="btn btn-secondary btn-sm" onclick="closeDrawer()">Cancel</button>
                <button type="submit" class="btn btn-primary btn-sm">Save changes</button>
            </div>
        </form>`;
    openDrawer(html, { title: 'Edit contact', sub: 'Changes are saved to your local database' });
    $('#drawerEditForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fields = {
            name: $('#dF-name').value,
            email_primary: $('#dF-email').value,
            phone_primary: $('#dF-phone').value,
            company: $('#dF-company').value,
        };
        try {
            await api('/api/contacts/' + id, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fields: fields }),
            });
            closeDrawer();
            toast('Contact updated', { type: 'success' });
            loadContacts();
        } catch (err) {
            toast('Could not save changes: ' + err.message, { type: 'error' });
        }
    });
}

// ── Emails ───────────────────────────────────────────────────────────────────

async function loadEmails() {
    skeletonRows('emailsBody', 4);
    try {
        const data = await api('/api/emails?page=' + S.emailsPage + '&size=' + S.emailsPageSize);
        S.emails = data.rows || [];
        S.emailsTotal = data.total != null ? Number(data.total) : S.emails.length;
        renderEmailsTable();
        renderPagination('emailsPagination', S.emailsTotal, S.emailsPage, S.emailsPageSize, (p) => {
            S.emailsPage = p;
            loadEmails();
        });
        const info = document.getElementById('emailsInfo');
        if (info) info.textContent = paginationInfo(S.emailsTotal, S.emailsPage, S.emailsPageSize);
    } catch (e) {
        document.getElementById('emailsBody').innerHTML =
            `<tr><td colspan="4">${emptyStateHTML({ icon: 'i-alert-circle', title: 'Emails unavailable', hint: e.message })}</td></tr>`;
    }
}

function renderEmailsTable() {
    const tbody = document.getElementById('emailsBody');
    if (!tbody) return;
    const q = ((document.getElementById('emailSearch') || {}).value || '').toLowerCase();
    let rows = S.emails;
    if (q) rows = rows.filter(e =>
        String(e.subject || '').toLowerCase().includes(q) ||
        String(e.sender_name || '').toLowerCase().includes(q));
    if (emailsSort.key) {
        rows = rows.slice().sort((a, b) => {
            const av = a[emailsSort.key], bv = b[emailsSort.key];
            const cmp = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av || '').localeCompare(String(bv || ''));
            return emailsSort.dir === 'asc' ? cmp : -cmp;
        });
    }
    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="4">${emptyStateHTML({
            icon: 'i-mail',
            title: q ? 'No emails match' : 'No emails yet',
            hint: q ? 'Try a different search term.' : 'Emails appear here after you extract .eml files or mailboxes.',
            ctaLabel: q ? null : 'Go to Extract',
            ctaFn: "showView('extract')",
        })}</td></tr>`;
        return;
    }
    tbody.innerHTML = rows.map(e => `<tr>
        <td class="c-subject"><span class="cell" title="${esc(e.subject || '')}">${esc(e.subject || '(no subject)')}</span></td>
        <td class="c-sender"><span class="cell" title="${esc(e.sender_name || '')}">${esc(e.sender_name || '—')}</span></td>
        <td class="c-date"><span class="cell mono" title="${esc(e.date || '')}">${esc(fmtDateTime(e.date))}</span></td>
        <td class="c-count td-num">${fmtInt(e.contact_count || 0)}</td>
    </tr>`).join('');
}

async function searchEmails() { renderEmailsTable(); }

function sortEmails(field) {
    if (emailsSort.key === field) emailsSort.dir = emailsSort.dir === 'asc' ? 'desc' : 'asc';
    else emailsSort = { key: field, dir: 'asc' };
    updateSortUI('emailsTable', field, emailsSort.dir);
    renderEmailsTable();
}

function exportEmails() {
    const rows = S.emails || [];
    if (!rows.length) { toast('Nothing to export yet — no emails loaded.', { type: 'info' }); return; }
    const lines = [['Subject', 'Sender', 'Date', 'Contacts'].join(',')];
    rows.forEach(e => lines.push([e.subject || '', e.sender_name || '', e.date || '', e.contact_count || 0].map(csvCell).join(',')));
    downloadFile('emails.csv', '\ufeff' + lines.join('\r\n'));
    toast(`Exported ${fmtInt(rows.length)} emails to emails.csv`, { type: 'success' });
}

// ── Customer Profiles ────────────────────────────────────────────────────────

async function loadCustomerProfiles() {
    const el = document.getElementById('profilesList');
    el.innerHTML = `<div class="card"><span class="skel" style="width:30%"></span></div>
        <div class="card"><span class="skel" style="width:45%"></span></div>
        <div class="card"><span class="skel" style="width:38%"></span></div>`;
    try {
        const data = await api('/api/contacts?page=1&size=' + S.contactsPageSize);
        S.profileContacts = data.rows || [];
        renderCustomerProfiles();
    } catch (e) {
        el.innerHTML = `<div class="banner error"><svg class="icon" aria-hidden="true"><use href="#i-alert-circle"/></svg><div><strong>Could not load profiles.</strong> ${esc(e.message)}</div></div>`;
    }
}

function renderCustomerProfiles() {
    const el = document.getElementById('profilesList');
    const q = ((document.getElementById('profileSearch') || {}).value || '').toLowerCase();
    let rows = S.profileContacts || [];
    if (q) rows = rows.filter(c =>
        String(c.name || '').toLowerCase().includes(q) ||
        String(c.company || '').toLowerCase().includes(q) ||
        String(c.email_primary || '').toLowerCase().includes(q));
    if (!rows.length) {
        el.innerHTML = `<div class="card">${emptyStateHTML({
            icon: 'i-contact',
            title: q ? 'No profiles match' : 'No customer profiles yet',
            hint: q ? 'Try a different filter.' : 'Profiles are built from your approved contacts.',
            ctaLabel: q ? null : 'Go to Contacts',
            ctaFn: "showView('contacts')",
        })}</div>`;
        return;
    }
    el.innerHTML = rows.map(c => {
        const comp = contactCompleteness(c);
        const name = c.name || '(no name)';
        return `<article class="profile-card">
            <div class="profile-top">
                <span class="profile-avatar" aria-hidden="true">${esc(initials(name))}</span>
                <div style="min-width:0">
                    <div class="profile-name" title="${esc(name)}">${esc(name)}</div>
                    <div class="profile-company">${esc(c.company || 'No company')}</div>
                </div>
            </div>
            <div class="profile-fields">
                <div class="row"><span class="k">Email</span><span class="v" title="${esc(c.email_primary || '')}">${esc(c.email_primary || '—')}</span></div>
                <div class="row"><span class="k">Phone</span><span class="v" title="${esc(c.phone_primary || '')}">${esc(c.phone_primary || '—')}</span></div>
            </div>
            <div class="completeness">
                <span class="completeness-track"><span class="completeness-fill" style="width:${comp.pct}%"></span></span>
                <span class="completeness-label">${comp.pct}%</span>
            </div>
            <button type="button" class="btn btn-secondary btn-sm" onclick="viewContactProfile(${c.id})">
                <svg class="icon" aria-hidden="true"><use href="#i-eye"/></svg>View profile
            </button>
        </article>`;
    }).join('');
}

// ── Staged contacts workflow ─────────────────────────────────────────────────

async function loadStagedContacts(page) {
    const target = page || S.stagedReviewPage || 1;
    S.stagedReviewPage = target;
    skeletonRows('stagedContactsBody', 10);
    try {
        const data = await api(`/api/staged-contacts?page=${target}&size=${S.stagedPageSize || 20}`);
        stagedContactsCache = data.rows || [];
        S.stagedCache = stagedContactsCache;
        S.stagedTotal = data.total != null ? Number(data.total) : stagedContactsCache.length;
        renderStagedContactsTable(stagedContactsCache, S.stagedTotal, data.page || target, data.pageSize || S.stagedPageSize || 20, (p) => {
            S.stagedReviewPage = p;
            loadStagedContacts(p);
        });
    } catch (e) {
        document.getElementById('stagedContactsBody').innerHTML =
            `<tr><td colspan="10">${emptyStateHTML({ icon: 'i-alert-circle', title: 'Staged contacts unavailable', hint: e.message })}</td></tr>`;
    }
}

function stagedBadge(reviewStatus, dedupStatus, importStatus) {
    let reviewBadge = '<span class="badge badge-neutral">New</span>';
    switch (reviewStatus) {
        case 'NEEDS_REVIEW': reviewBadge = '<span class="badge badge-warning">Needs review</span>'; break;
        case 'READY': reviewBadge = '<span class="badge badge-info">Ready</span>'; break;
        case 'APPROVED': reviewBadge = '<span class="badge badge-success"><svg class="icon" aria-hidden="true"><use href="#i-check"/></svg>Approved</span>'; break;
        case 'REJECTED': reviewBadge = '<span class="badge badge-error"><svg class="icon" aria-hidden="true"><use href="#i-x"/></svg>Rejected</span>'; break;
        case 'DISMISSED': reviewBadge = '<span class="badge badge-neutral">Dismissed</span>'; break;
    }
    let dedupBadge = '<span class="badge badge-neutral">Not checked</span>';
    switch (dedupStatus) {
        case 'UNIQUE': dedupBadge = '<span class="badge badge-success">Unique</span>'; break;
        case 'EXACT_DUPLICATE': dedupBadge = '<span class="badge badge-error">Exact duplicate</span>'; break;
        case 'PROBABLE_DUPLICATE': dedupBadge = '<span class="badge badge-warning">Probable duplicate</span>'; break;
        case 'CONFLICT': dedupBadge = '<span class="badge badge-error">Conflict</span>'; break;
    }
    let importBadge = '<span class="badge badge-neutral">Not imported</span>';
    switch (importStatus) {
        case 'NEW_CONTACT_CREATED': importBadge = '<span class="badge badge-success">New contact</span>'; break;
        case 'EXISTING_CONTACT_ENRICHED': importBadge = '<span class="badge badge-warning">Existing contact</span>'; break;
        case 'IMPORT_FAILED': importBadge = '<span class="badge badge-error">Import failed</span>'; break;
    }
    return { reviewBadge, dedupBadge, importBadge };
}

function visibleStagedRows() {
    const q = ((document.getElementById('stagedSearch') || {}).value || '').toLowerCase();
    const f = (document.getElementById('stagedFilter') || {}).value || '';
    let rows = stagedContactsCache;
    if (f) rows = rows.filter(r => (r.review_status || 'NEW') === f);
    if (q) rows = rows.filter(r =>
        String(r.name || '').toLowerCase().includes(q) ||
        String(r.email || '').toLowerCase().includes(q) ||
        String(r.company || '').toLowerCase().includes(q));
    return rows;
}

function renderStagedContactsTable(staged, total, page, pageSize, onPageChange) {
    const tbody = document.getElementById('stagedContactsBody');
    if (!tbody) return;
    const rows = visibleStagedRows();
    if (!rows.length) {
        const filtered = staged && staged.length;
        tbody.innerHTML = `<tr><td colspan="10">${emptyStateHTML({
            icon: 'i-inbox',
            title: filtered ? 'Nothing matches these filters' : 'No staged contacts awaiting review',
            hint: filtered ? 'Adjust the search or status filter.' : 'Newly extracted contacts land here for a quick decision.',
            ctaLabel: filtered ? null : 'Extract a file',
            ctaFn: "showView('extract')",
        })}</td></tr>`;
        if (onPageChange) renderStagedPagination(total, page, pageSize, onPageChange);
        const info = document.getElementById('stagedInfo');
        if (info) info.textContent = paginationInfo(total || 0, page || 1, pageSize || 20);
        return;
    }

    tbody.innerHTML = rows.map((sc, idx) => {
        const reviewStatus = sc.review_status || 'NEW';
        const dedupStatus = sc.dedup_status || 'NOT_CHECKED';
        const importStatus = sc.import_status || 'NOT_IMPORTED';
        const b = stagedBadge(reviewStatus, dedupStatus, importStatus);
        const name = sc.name || '(no name)';
        return `<tr data-id="${sc.id}" data-idx="${idx}" class="${idx === stagedCursor ? 'is-kbd-target' : ''}">
            <td class="c-check"><input type="checkbox" class="row-check" data-id="${sc.id}" aria-label="Select ${esc(name)}"></td>
            <td class="c-name"><span class="name-cell"><span class="avatar" aria-hidden="true">${esc(initials(name))}</span><span class="cell" title="${esc(name)}">${esc(name)}</span></span></td>
            <td class="c-email"><span class="cell mono" title="${esc(sc.email || '')}">${esc(sc.email || '—')}</span></td>
            <td class="c-phone"><span class="cell mono" title="${esc(sc.phone_primary || '')}">${esc(sc.phone_primary || '—')}</span></td>
            <td class="c-company"><span class="cell" title="${esc(sc.company || '')}">${esc(sc.company || '—')}</span></td>
            <td class="c-review">${b.reviewBadge}</td>
            <td class="c-dedup">${b.dedupBadge}</td>
            <td class="c-import">${b.importBadge}</td>
            <td class="c-conf td-num">${sc.confidence !== undefined && sc.confidence !== null && sc.confidence !== '' ? esc(sc.confidence) : '—'}</td>
            <td class="c-actions"><span class="row-actions">
                <button type="button" class="row-btn" title="Open" aria-label="Open ${esc(name)}" onclick="viewStagedDetail(${sc.id})"><svg class="icon" aria-hidden="true"><use href="#i-eye"/></svg></button>
                <button type="button" class="row-btn" title="Approve" aria-label="Approve ${esc(name)}" onclick="approveContact(${sc.id})"><svg class="icon" aria-hidden="true"><use href="#i-check"/></svg></button>
                <button type="button" class="row-btn danger" title="Reject" aria-label="Reject ${esc(name)}" onclick="rejectContact(${sc.id})"><svg class="icon" aria-hidden="true"><use href="#i-x"/></svg></button>
                <button type="button" class="row-btn" title="Dismiss" aria-label="Dismiss ${esc(name)}" onclick="dismissContact(${sc.id})"><svg class="icon" aria-hidden="true"><use href="#i-ban"/></svg></button>
            </span></td>
        </tr>`;
    }).join('');

    renderStagedPagination(total, page, pageSize, onPageChange);
    const info = document.getElementById('stagedInfo');
    if (info) info.textContent = paginationInfo(total || 0, page || 1, pageSize || 20);
    syncStagedBulk();
}

function renderStagedPagination(total, page, pageSize, onPageChange) {
    renderPagination('stagedPagination', total, page, pageSize, onPageChange || ((p) => { S.stagedReviewPage = p; loadStagedContacts(p); }));
}

function filterStaged() {
    stagedCursor = -1;
    renderStagedContactsTable(stagedContactsCache, S.stagedTotal, S.stagedReviewPage, S.stagedPageSize, (p) => {
        S.stagedReviewPage = p;
        loadStagedContacts(p);
    });
}

function syncStagedBulk() {
    const ids = $$('#stagedContactsBody .row-check:checked');
    const btn = document.getElementById('stagedBulkApprove');
    if (btn) btn.disabled = ids.length === 0;
}

async function bulkApproveStaged() {
    const ids = $$('#stagedContactsBody .row-check:checked').map(cb => Number(cb.dataset.id));
    if (!ids.length) return;
    let ok = 0, failed = 0;
    for (const id of ids) {
        try { await api(`/api/staged-contacts/${id}/approve`, { method: 'POST' }); ok++; }
        catch (e) { failed++; }
    }
    toast(`${ok} contact${ok === 1 ? '' : 's'} approved${failed ? `, ${failed} failed` : ''}`, { type: failed ? 'error' : 'success' });
    loadStagedContacts();
    loadOverview();
}

// Optimistic approve / reject / dismiss: row updates immediately, real POST
// follows. Only permanent deletes ask for confirmation.
async function stagedDecide(stagedId, action, opts) {
    opts = opts || {};
    const row = stagedContactsCache.find(x => x.id === stagedId);
    const prevState = row ? { review_status: row.review_status } : null;
    const labels = { approve: 'approved', reject: 'rejected', dismiss: 'dismissed' };
    if (row && !opts.silent) row.review_status = action === 'approve' ? 'APPROVED' : (action === 'reject' ? 'REJECTED' : 'DISMISSED');
    renderStagedContactsTable(stagedContactsCache, S.stagedTotal, S.stagedReviewPage, S.stagedPageSize, null);
    try {
        await api(`/api/staged-contacts/${stagedId}/${action}`, { method: 'POST' });
        toast(`Contact ${labels[action]}`, { type: 'success' });
        loadOverview();
        loadStagedContacts();
    } catch (e) {
        if (row && prevState) row.review_status = prevState.review_status;
        renderStagedContactsTable(stagedContactsCache, S.stagedTotal, S.stagedReviewPage, S.stagedPageSize, null);
        toast(`Could not ${action} contact: ${e.message}`, { type: 'error' });
    }
}

async function approveContact(stagedId) { return stagedDecide(stagedId, 'approve'); }
async function rejectContact(stagedId) { return stagedDecide(stagedId, 'reject'); }
async function dismissContact(stagedId) { return stagedDecide(stagedId, 'dismiss'); }

function viewStagedDetail(stagedId) {
    const c = stagedContactsCache.find(x => x.id === stagedId);
    if (!c) return;
    const name = c.name || '(no name)';
    const b = stagedBadge(c.review_status || 'NEW', c.dedup_status || 'NOT_CHECKED', c.import_status || 'NOT_IMPORTED');
    const html = `
        <div class="dsec">
            <div class="profile-top">
                <span class="profile-avatar" aria-hidden="true">${esc(initials(name))}</span>
                <div><div class="profile-name">${esc(name)}</div><div class="profile-company">${esc(c.company || 'No company')}</div></div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">${b.reviewBadge}${b.dedupBadge}${b.importBadge}</div>
        </div>
        <div class="dsec"><h3>Extracted fields</h3><dl class="dgrid">
            <dt>Name</dt><dd>${esc(c.name || '—')}</dd>
            <dt>Email</dt><dd class="mono">${esc(c.email || '—')}</dd>
            <dt>Phone</dt><dd class="mono">${esc(c.phone_primary || '—')}</dd>
            <dt>Company</dt><dd>${esc(c.company || '—')}</dd>
            <dt>Confidence</dt><dd class="mono">${c.confidence !== undefined && c.confidence !== null && c.confidence !== '' ? esc(c.confidence) : '—'}</dd>
        </dl></div>
        ${provenanceHTML(c)}
        <div class="drawer-actions">
            <button type="button" class="btn btn-secondary btn-sm" onclick="closeDrawer(); editStagedContact(${c.id})"><svg class="icon" aria-hidden="true"><use href="#i-pencil"/></svg>Edit</button>
            <button type="button" class="btn btn-primary btn-sm" onclick="approveContact(${c.id}); closeDrawer()"><svg class="icon" aria-hidden="true"><use href="#i-check"/></svg>Approve</button>
            <button type="button" class="btn btn-danger btn-sm" onclick="dismissContact(${c.id}); closeDrawer()"><svg class="icon" aria-hidden="true"><use href="#i-ban"/></svg>Dismiss</button>
        </div>`;
    openDrawer(html, { title: 'Staged contact', sub: 'Evidence and provenance from the source file' });
}

async function editStagedContact(stagedId) {
    const c = stagedContactsCache.find(x => x.id === stagedId);
    if (!c) return;
    const html = `
        <form class="drawer-form" id="drawerEditForm">
            ${contactFormFields(c)}
            <div class="drawer-actions">
                <button type="button" class="btn btn-secondary btn-sm" onclick="closeDrawer()">Cancel</button>
                <button type="submit" class="btn btn-primary btn-sm">Save changes</button>
            </div>
        </form>`;
    openDrawer(html, { title: 'Edit staged contact', sub: 'Fix fields before approving into the CRM' });
    $('#drawerEditForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fields = {
            name: $('#dF-name').value,
            email: $('#dF-email').value,
            phone_primary: $('#dF-phone').value,
            company: $('#dF-company').value,
        };
        try {
            await api(`/api/staged-contacts/${stagedId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fields: fields }),
            });
            closeDrawer();
            toast('Staged contact updated', { type: 'success' });
            loadStagedContacts();
        } catch (err) {
            toast('Could not save changes: ' + err.message, { type: 'error' });
        }
    });
}

// Keyboard-first triage: J/K or ↑/↓ move, A approve, R reject, D dismiss,
// Enter opens the drawer. Active only on the staged view and never while
// typing in a field.
function stagedKeydown(e) {
    if (S.currentView !== 'staged') return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
    if (document.getElementById('palette') && !document.getElementById('palette').hidden) return;
    const drawer = document.getElementById('drawer');
    if (drawer && !drawer.hidden && e.key !== 'Escape') return;
    const rows = visibleStagedRows();
    if (!rows.length) return;
    const move = (delta) => {
        stagedCursor = Math.max(0, Math.min(rows.length - 1, (stagedCursor < 0 ? (delta > 0 ? -1 : 0) : stagedCursor) + delta));
        renderStagedContactsTable(stagedContactsCache, S.stagedTotal, S.stagedReviewPage, S.stagedPageSize, null);
        const tr = $(`#stagedContactsBody tr[data-idx="${stagedCursor}"]`);
        if (tr) {
            tr.scrollIntoView({ block: 'nearest' });
            const btn = tr.querySelector('.row-btn');
            if (btn) btn.focus({ preventScroll: true });
        }
    };
    switch (e.key) {
        case 'j': case 'J': case 'ArrowDown': e.preventDefault(); move(1); break;
        case 'k': case 'K': case 'ArrowUp': e.preventDefault(); move(-1); break;
        case 'a': case 'A': e.preventDefault(); stagedDecide(rows[stagedCursor < 0 ? 0 : stagedCursor].id, 'approve'); break;
        case 'r': case 'R': e.preventDefault(); stagedDecide(rows[stagedCursor < 0 ? 0 : stagedCursor].id, 'reject'); break;
        case 'd': case 'D': e.preventDefault(); stagedDecide(rows[stagedCursor < 0 ? 0 : stagedCursor].id, 'dismiss'); break;
        case 'Enter': {
            const idx = stagedCursor < 0 ? 0 : stagedCursor;
            e.preventDefault();
            viewStagedDetail(rows[idx].id);
            break;
        }
    }
}

// ── Data Quality ────────────────────────────────────────────────────────────

async function loadDataQuality() {
    try {
        const status = await api('/api/status');
        const counts = status.counts || {};
        document.getElementById('quality-invalid-emails').textContent = fmtInt(counts.invalid_emails || 0);
        document.getElementById('quality-invalid-phones').textContent = fmtInt(counts.invalid_phones || 0);
        document.getElementById('quality-missing').textContent = fmtInt(counts.incomplete_records || 0);
        document.getElementById('quality-dupes').textContent = fmtInt(counts.duplicates || 0);

        // Detailed rule results (same endpoint as the previous build).
        const dqList = document.getElementById('quality-detail-list');
        try {
            const dq = await api('/api/dedup-rules');
            if (dq && dq.rows && dq.rows.length) {
                dqList.innerHTML = dq.rows.map(r => `
                    <div class="quality-rule">
                        <span class="quality-rule-field">${esc(r.field)}</span>
                        <span class="badge badge-${r.severity === 'error' ? 'error' : r.severity === 'warning' ? 'warning' : 'neutral'}">${esc(r.status)}</span>
                    </div>`).join('');
            } else {
                dqList.innerHTML = '<p class="card-sub">No detailed data quality data available.</p>';
            }
        } catch (e) {
            dqList.innerHTML = '<p class="card-sub">Detailed rule results are not available from the backend yet.</p>';
        }
    } catch (e) {
        ['quality-invalid-emails', 'quality-invalid-phones', 'quality-missing', 'quality-dupes'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = '—';
        });
        const card = document.getElementById('quality-detail-card');
        if (card) showBanner('settingsBanner', 'error', 'Could not load data quality', e.message);
    }
}

// ── History ─────────────────────────────────────────────────────────────────

async function loadHistory() {
    skeletonRows('historyBody', 4);
    try {
        const runs = await api('/api/history');
        S.historyRows = (runs && runs.results) || [];
        renderHistoryTable();
        const info = document.getElementById('historyInfo');
        if (info) info.textContent = `${fmtInt(S.historyRows.length)} file${S.historyRows.length === 1 ? '' : 's'} processed`;
    } catch (e) {
        document.getElementById('historyBody').innerHTML =
            `<tr><td colspan="4">${emptyStateHTML({ icon: 'i-alert-circle', title: 'History unavailable', hint: e.message })}</td></tr>`;
    }
}

function renderHistoryTable() {
    const tbody = document.getElementById('historyBody');
    if (!tbody) return;
    const q = ((document.getElementById('historySearch') || {}).value || '').toLowerCase();
    let rows = S.historyRows;
    if (q) rows = rows.filter(r => String(r.file || '').toLowerCase().includes(q));
    if (historySort.key) {
        rows = rows.slice().sort((a, b) => {
            const av = a[historySort.key], bv = b[historySort.key];
            const cmp = typeof av === 'number' && typeof bv === 'number'
                ? av - bv
                : String(av || '').localeCompare(String(bv || ''));
            return historySort.dir === 'asc' ? cmp : -cmp;
        });
    }
    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="4">${emptyStateHTML({
            icon: 'i-history',
            title: q ? 'No files match' : 'No extraction history yet',
            hint: q ? 'Try a different filter.' : 'Processed files will be listed here.',
            ctaLabel: q ? null : 'Go to Extract',
            ctaFn: "showView('extract')",
        })}</td></tr>`;
        return;
    }
    tbody.innerHTML = rows.map(r => {
        const ok = String(r.status || '').toUpperCase() === 'OK';
        const badge = ok
            ? '<span class="badge badge-success"><svg class="icon" aria-hidden="true"><use href="#i-check"/></svg>OK</span>'
            : `<span class="badge badge-error"><svg class="icon" aria-hidden="true"><use href="#i-x-circle"/></svg>${esc(r.status || 'unknown')}</span>`;
        return `<tr>
            <td class="c-file"><span class="cell mono" title="${esc(r.file || '')}">${esc(r.file || 'unknown')}</span></td>
            <td class="c-status">${badge}</td>
            <td class="c-count td-num">${fmtInt(r.contacts_found || 0)}</td>
            <td class="c-date"><span class="cell mono" title="${esc(r.processed_at || '')}">${esc(fmtDateTime(r.processed_at))}</span></td>
        </tr>`;
    }).join('');
}

function filterHistory() { renderHistoryTable(); }

function sortHistory(field) {
    if (historySort.key === field) historySort.dir = historySort.dir === 'asc' ? 'desc' : 'asc';
    else historySort = { key: field, dir: 'asc' };
    updateSortUI('historyTable', field, historySort.dir);
    renderHistoryTable();
}

// ── Settings ────────────────────────────────────────────────────────────────

let PROVIDER_CATALOG = [];
const MODEL_LISTS = {};  // per-row discovered model ids (session cache)
const promptsWorking = {};
const RELIABILITY_HINTS = {
    timeout_s: 'Seconds before a single provider request times out.',
    attempts: 'Retry rounds per provider entry before falling over.',
    backoff_initial_s: 'Wait before the first retry; doubles each round.',
    backoff_max_s: 'Cap on a single retry wait.',
    deadline_s: 'Total seconds an extraction may spend across all providers.',
    repair_attempts: 'Rounds asking a provider to fix malformed JSON.',
    cooldown_s: 'How long a failing entry is paused after repeated errors.',
    fail_threshold: 'Failures before an entry is paused automatically.',
};

async function loadSettings() {
    hideBanner('settingsBanner');
    try {
        const [settings, catalog, rel] = await Promise.all([
            api('/api/settings'),
            api('/api/providers/catalog').catch(() => ({ catalog: [] })),
            api('/api/reliability').catch(() => ({ reliability: null })),
        ]);
        window.CRM_SETTINGS = settings;
        PROVIDER_CATALOG = (catalog && catalog.catalog) || [];
        settingsWorking = (settings.chain || []).map(x => Object.assign({}, x));
        renderSettings({ chain: settingsWorking });
        renderReliability((rel && rel.reliability) || null);
        try { await loadPrompts(); } catch (e) { /* prompts are optional */ }
        // populate optional fields only when the API provides them
        if (settings.crm_dir !== undefined) document.getElementById('crmDir').value = settings.crm_dir || '';
        if (settings.eml_dir !== undefined) document.getElementById('emlDir').value = settings.eml_dir || '';
        if (settings.watch_interval !== undefined) document.getElementById('watchInterval').value = settings.watch_interval;
        if (settings.watch_enabled !== undefined) document.getElementById('watchEnabled').checked = !!settings.watch_enabled;
        markSettingsDirty(false);
    } catch (e) {
        document.getElementById('providerChain').innerHTML = '';
        showBanner('settingsBanner', 'error', 'Could not load settings', e.message + ' — provider settings need the local API.');
    }
}

function providerOptions(selected) {
    const opts = PROVIDER_CATALOG.map(p =>
        `<option value="${esc(p.id)}" ${p.id === selected ? 'selected' : ''}>${esc(p.name)}</option>`);
    opts.push(`<option value="custom" ${selected === 'custom' ? 'selected' : ''}>Custom OpenAI-compatible</option>`);
    return opts.join('');
}

function renderSettings(settings) {
    const providerChain = document.getElementById('providerChain');
    if (!providerChain) return;
    const chain = (settings && settings.chain) || [];

    providerChain.innerHTML = chain.map((entry, i) => {
        const enabled = entry.enabled !== false;
        const provider = entry.provider || '';
        const spec = PROVIDER_CATALOG.find(p => p.id === provider);
        const showBase = provider === 'custom' || provider === 'ollama';
        const keyHint = (spec && spec.key_url) ? ` <a class="link" href="${esc(spec.key_url)}" target="_blank" rel="noopener">get a key</a>` : '';
        return `<li class="provider-row">
            <span class="provider-order" aria-label="Priority ${i + 1}">${i + 1}</span>
            <div class="provider-fields">
                <select aria-label="Provider ${i + 1} type"
                        onchange="providerChanged(${i}, this.value)">${providerOptions(provider)}</select>
                <span class="model-row">
                    <input type="text" value="${esc(entry.model || '')}" placeholder="Model id (e.g. llama3)" list="models-${i}"
                           aria-label="Provider ${i + 1} model (type or pick — manual entry allowed)"
                           onchange="updateProviderSetting(${i}, 'model', this.value)">
                    <button type="button" class="icon-btn-sm" title="Refresh model list" aria-label="Refresh model list ${i + 1}"
                            onclick="refreshModels(${i})"><svg class="icon"><use href="#i-refresh"/></svg></button>
                    <datalist id="models-${i}">${(MODEL_LISTS[i] || []).map(m => `<option value="${esc(m)}">`).join('')}</datalist>
                </span>
                ${showBase ? `<input type="text" class="mono" value="${esc(entry.base_url || '')}"
                        placeholder="${provider === 'ollama' ? 'http://localhost:11434' : 'Required: http://localhost:1234/v1'}"
                        aria-label="Provider ${i + 1} base URL"
                        onchange="updateProviderSetting(${i}, 'base_url', this.value)">` : ''}
                <span class="key-row">
                    <input type="password" value="${entry.api_key_set ? '********' : esc(entry.api_key || '')}" placeholder="${spec && !spec.requires_key ? 'No API key needed' : 'API key'}"
                           aria-label="Provider ${i + 1} API key" autocomplete="off"
                           onchange="updateProviderSetting(${i}, 'api_key', this.value)">
                    ${keyHint}
                </span>
            </div>
            <span class="dot ${enabled ? 'is-on' : 'is-off'}" title="${enabled ? 'Enabled' : 'Disabled'}" aria-hidden="true"></span>
            <label class="switch" data-tipdir="right" data-tip="${enabled ? 'Enabled' : 'Disabled'}">
                <input type="checkbox" ${enabled ? 'checked' : ''} aria-label="Enable provider ${i + 1}"
                       onchange="updateProviderSetting(${i}, 'enabled', this.checked)">
                <span class="switch-track" aria-hidden="true"></span>
            </label>
            <span class="provider-tools">
                <button type="button" class="icon-btn-sm" title="Test connection" aria-label="Test connection ${i + 1}"
                        onclick="testProvider(${i})"><svg class="icon"><use href="#i-check"/></svg></button>
                <button type="button" class="icon-btn-sm" title="Move up" aria-label="Move provider ${i + 1} up" ${i === 0 ? 'disabled' : ''} onclick="moveProvider(${i}, -1)"><svg class="icon" aria-hidden="true"><use href="#i-chevron-up"/></svg></button>
                <button type="button" class="icon-btn-sm" title="Move down" aria-label="Move provider ${i + 1} down" ${i === chain.length - 1 ? 'disabled' : ''} onclick="moveProvider(${i}, 1)"><svg class="icon" aria-hidden="true"><use href="#i-chevron-down"/></svg></button>
                <button type="button" class="icon-btn-sm" title="Remove" aria-label="Remove provider ${i + 1}" onclick="removeProviderSetting(${i})"><svg class="icon" aria-hidden="true"><use href="#i-trash"/></svg></button>
            </span>
            <span class="provider-test" id="testResult-${i}" role="status" aria-live="polite"></span>
        </li>`;
    }).join('');
}

async function refreshModels(i) {
    const entry = (settingsWorking || [])[i];
    if (!entry) return;
    if (!entry.provider) { toast('Pick a provider first.', { type: 'info' }); return; }
    const out = document.getElementById(`testResult-${i}`);
    if (out) out.textContent = 'Loading models…';
    try {
        // key payloads must NOT be esc()'d (JSON body, not HTML) — extract
        // the variable so render code stays visibly separate from key material.
        const apiKey = entry.api_key_set ? '' : (entry['api_key'] || '');
        const res = await api('/api/providers/models', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: entry.id, provider: entry.provider,
                base_url: entry.base_url || '', api_key: apiKey,
            }),
        });
        MODEL_LISTS[i] = res.models || [];
        if (MODEL_LISTS[i].length) {
            renderSettings({ chain: settingsWorking });
            if (out) out.textContent = `${MODEL_LISTS[i].length} models found (pick or type your own id).`;
        } else if (res.error) {
            if (out) out.textContent = res.error + ' — type the model id manually.';
        } else {
            if (out) out.textContent = 'Model list unavailable — type the model id manually.';
        }
    } catch (e) {
        if (out) out.textContent = e.message + ' — type the model id manually.';
    }
}

async function testProvider(i) {
    const entry = (settingsWorking || [])[i];
    if (!entry) return;
    const row = {
        id: entry.id, provider: entry.provider || '', model: entry.model || '',
        base_url: entry.base_url || '',
        api_key: entry.api_key_set ? '' : (entry['api_key'] || ''),
    };
    const out = document.getElementById(`testResult-${i}`);
    if (out) out.textContent = 'Testing…';
    try {
        const res = await api('/api/providers/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(row),
        });
        if (out) out.textContent = res.message || (res.ok ? 'OK' : 'failed');
    } catch (e) {
        if (out) out.textContent = e.message;
    }
}

function providerChanged(i, value) {
    updateProviderSetting(i, 'provider', value);
    // base URL visibility depends on provider; re-render keeps rows honest
    if (value === 'custom' || value === 'ollama') {
        settingsWorking[i].base_url = settingsWorking[i].base_url || '';
    }
    renderSettings({ chain: settingsWorking });
}

function renderReliability(rel) {
    const host = document.getElementById('reliabilityFields');
    if (!host) return;
    reliabilityWorking = rel || {
        timeout_s: 120, attempts: 3, backoff_initial_s: 1, backoff_max_s: 16,
        deadline_s: 300, repair_attempts: 1, cooldown_s: 120, fail_threshold: 4,
    };
    host.innerHTML = Object.entries(reliabilityWorking).map(([key, value]) => `
        <div class="field">
            <label for="rel-${key}">${esc(key.replace(/_/g, ' '))}</label>
            <input type="number" id="rel-${key}" class="num" step="any" min="0" value="${esc(value)}"
                   aria-label="${esc(key.replace(/_/g, ' '))}"
                   onchange="updateSettingReliability('${key}', this.value)">
            <p class="field-help">${esc(RELIABILITY_HINTS[key] || '')}</p>
        </div>`).join('');
}

function updateSettingReliability(key, value) {
    reliabilityWorking = reliabilityWorking || {};
    reliabilityWorking[key] = Number(value);
    markSettingsDirty(true);
}

function renderPrompts() {
    const host = document.getElementById('promptEditors');
    if (!host) return;
    host.innerHTML = ['contact', 'eml'].map(kind => {
        const p = promptsWorking[kind] || {};
        const meta = p.customised
            ? `Customised${p.updated_at ? ' · saved ' + esc(p.updated_at) : ''}`
            : `Default (v${esc(p.default_version || '1.0.0')})`;
        const chars = (p.text || '').length;
        return `<div class="prompt-editor" data-kind="${kind}">
            <div class="prompt-head">
                <h4>${esc(p.title || kind)}</h4>
                <span class="prompt-meta">${meta} · ${chars} chars</span>
            </div>
            <p class="field-help">${esc(p.purpose || '')}</p>
            <textarea id="promptText-${kind}" class="mono prompt-text" rows="12"
                      aria-label="${esc(p.title || kind)} prompt"
                      oninput="markPromptDirty('${kind}')">${esc(p.text || '')}</textarea>
            <span class="prompt-status" id="promptStatus-${kind}" role="status" aria-live="polite"></span>
            <div class="prompt-actions">
                <button type="button" class="btn btn-sm btn-primary" onclick="savePrompt('${kind}')">Save prompt</button>
                <button type="button" class="btn btn-sm btn-secondary" onclick="resetPrompt('${kind}')">Reset to default</button>
            </div>
        </div>`;
    }).join('');
}

async function loadPrompts() {
    const list = await api('/api/prompts');
    for (const kind of ['contact', 'eml']) {
        const detail = await api(`/api/prompts/${kind}`);
        promptsWorking[kind] = detail;
    }
    void list;
    renderPrompts();
}

function markPromptDirty(kind) {
    const detail = promptsWorking[kind];
    const el = document.getElementById(`promptText-${kind}`);
    if (!detail || !el) return;
    const dirty = el.value !== detail.text;
    const status = document.getElementById(`promptStatus-${kind}`);
    if (status) status.textContent = dirty ? 'Unsaved changes' : '';
}

async function savePrompt(kind) {
    const el = document.getElementById(`promptText-${kind}`);
    if (!el) return;
    try {
        const res = await api(`/api/prompts/${kind}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: el.value }),
        });
        const detail = await api(`/api/prompts/${kind}`);
        promptsWorking[kind] = detail;
        renderPrompts();
        toast(`${detail.title} saved (${res.chars} chars).`, { type: 'success' });
    } catch (e) {
        showBanner('settingsBanner', 'error', `${kind} prompt was not saved`, e.message);
    }
}

async function resetPrompt(kind) {
    const yes = await confirmDialog({
        title: 'Reset prompt to default?',
        message: 'Your custom edits to this prompt are removed. The other prompt is untouched.',
        confirmLabel: 'Reset',
    });
    if (!yes) return;
    try {
        await api(`/api/prompts/${kind}/reset`, { method: 'POST' });
        const detail = await api(`/api/prompts/${kind}`);
        promptsWorking[kind] = detail;
        renderPrompts();
        toast('Prompt reset to default.', { type: 'success' });
    } catch (e) {
        showBanner('settingsBanner', 'error', 'Could not reset prompt', e.message);
    }
}

function addProvider() {
    if (!settingsWorking) settingsWorking = [];
    settingsWorking.push({ provider: '', model: '', api_key: '', enabled: true });
    window.CRM_SETTINGS_CHAIN = settingsWorking; // legacy global kept in sync
    renderSettings({ chain: settingsWorking });
    markSettingsDirty(true);
}

// Legacy name kept working
function addProviderSetting() { addProvider(); }

function updateProviderSetting(idx, field, value) {
    if (!settingsWorking || !settingsWorking[idx]) return;
    settingsWorking[idx][field] = value;
    window.CRM_SETTINGS_CHAIN = settingsWorking;
    if (field === 'enabled') renderSettings({ chain: settingsWorking });
    markSettingsDirty(true);
}

function removeProviderSetting(idx) {
    if (!settingsWorking || !settingsWorking[idx]) return;
    confirmDialog({
        title: 'Remove provider?',
        message: `Provider “${settingsWorking[idx].provider || 'unnamed'}” will be removed from the chain when you save.`,
        confirmLabel: 'Remove',
    }).then((yes) => {
        if (!yes) return;
        settingsWorking.splice(idx, 1);
        renderSettings({ chain: settingsWorking });
        markSettingsDirty(true);
    });
}

function moveProvider(idx, dir) {
    if (!settingsWorking) return;
    const j = idx + dir;
    if (j < 0 || j >= settingsWorking.length) return;
    const tmp = settingsWorking[idx];
    settingsWorking[idx] = settingsWorking[j];
    settingsWorking[j] = tmp;
    renderSettings({ chain: settingsWorking });
    markSettingsDirty(true);
}

function markSettingsDirty(dirty) {
    settingsDirtyFlag = dirty !== false;
    const pill = document.getElementById('settingsDirty');
    if (pill) pill.hidden = !settingsDirtyFlag;
}

function pickFolder(target) {
    const input = document.getElementById(target === 'crm' ? 'crmDir' : 'emlDir');
    if (input) input.focus();
    toast('Type the folder path here — the native folder picker is provided by the desktop service, which this build does not expose.', { type: 'info', timeout: 5000 });
}

async function saveSettings() {
    const payload = {
        chain: settingsWorking || [],
        crm_dir: (document.getElementById('crmDir') || {}).value || '',
        eml_dir: (document.getElementById('emlDir') || {}).value || '',
        watch_interval: Number((document.getElementById('watchInterval') || {}).value) || 30,
        watch_enabled: !!(document.getElementById('watchEnabled') || {}).checked,
        reliability: reliabilityWorking || {},
    };
    // Client preferences are safe to persist locally regardless of backend support.
    try { localStorage.setItem('crm-settings-local', JSON.stringify(payload)); } catch (e) { /* ignore */ }
    try {
        await api('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        markSettingsDirty(false);
        toast('Settings saved', { type: 'success' });
    } catch (e) {
        showBanner('settingsBanner', 'error', 'Settings were kept for this session only',
            'The backend did not accept a settings save (' + e.message + '). Nothing was lost in this window — see Issues in the release notes.');
        markSettingsDirty(true);
    }
}

// ── Analytics (plain data tables only — D-012: no charts or graphs) ──────────

function setTakeaway(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function tallyBy(rows, key) {
    const map = new Map();
    rows.forEach(r => {
        const v = r[key];
        if (v === undefined || v === null || v === '') return;
        const k = String(v);
        map.set(k, (map.get(k) || 0) + 1);
    });
    return Array.from(map, ([label, value]) => ({ label, value }));
}

function renderAnalyticsTable(hostId, headers, rows, empty) {
    const host = document.getElementById(hostId);
    if (!host) return;
    if (!rows.length) {
        const icon = empty && empty.icon || 'i-chart';
        host.innerHTML = `<div class="empty"><span class="empty-ic"><svg class="icon" aria-hidden="true"><use href="#${icon}"/></svg></span>
            <strong>${esc((empty && empty.title) || 'No data yet')}</strong><p>${esc((empty && empty.hint) || 'This table fills in as contacts are extracted.')}</p></div>`;
        return;
    }
    host.innerHTML = `<table class="analytics-table">
        <thead><tr>${headers.map(h => `<th scope="col">${esc(h)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody>
    </table>`;
}

function setAnalyticsSub(takeawayId, text) {
    const el = document.getElementById(takeawayId);
    if (!el) return;
    const card = el.closest('.card');
    const sub = card && card.querySelector('.card-sub');
    if (sub) sub.textContent = text;
}

async function loadAnalytics() {
    let rows = [];
    try {
        const d = await api('/api/contacts?page=1&size=1000');
        rows = d.rows || [];
    } catch (e) { rows = []; }

    let historyRows = [];
    try {
        const j = await api('/api/history');
        historyRows = (j && j.results) || [];
    } catch (e) { historyRows = []; }

    // Geographic distribution — from real location fields only; otherwise an
    // honest empty state (nothing fabricated).
    const geoKey = ['country', 'country_code', 'geo', 'region', 'state', 'city']
        .find(k => rows.some(r => r[k] !== undefined && r[k] !== null && r[k] !== ''));
    if (geoKey) {
        const geoRows = tallyBy(rows, geoKey).sort((a, b) => b.value - a.value);
        const total = geoRows.reduce((a, d) => a + d.value, 0);
        const top = geoRows[0];
        setTakeaway('analytics-geo-takeaway', `${top.label} leads with ${Math.round(top.value / Math.max(1, rows.length) * 100)}% of contacts`);
        renderAnalyticsTable('analytics-geo',
            [geoKey[0].toUpperCase() + geoKey.slice(1), 'Contacts', 'Share'],
            geoRows.map(d => [d.label, fmtInt(d.value), Math.round(d.value / total * 100) + '%']));
    } else {
        setTakeaway('analytics-geo-takeaway', 'No geographic data available yet');
        renderAnalyticsTable('analytics-geo', ['Category', 'Contacts', 'Share'], [],
            { title: 'Waiting for location fields', hint: 'Your contacts do not include a country or region field, so there is nothing to summarize yet.', icon: 'i-globe' });
    }

    // Field completeness — real fill rates over the fetched contacts.
    const fields = [
        { key: 'name', label: 'Name' },
        { key: 'email_primary', label: 'Email' },
        { key: 'phone_primary', label: 'Phone' },
        { key: 'company', label: 'Company' },
    ];
    const completeness = fields.map(f => ({
        label: f.label,
        value: rows.length ? Math.round(rows.filter(r => r[f.key]).length / rows.length * 100) : 0,
    })).sort((a, b) => b.value - a.value);
    if (rows.length) {
        const best = completeness[0];
        setTakeaway('analytics-completeness-takeaway', `${best.value}% of contacts have a ${best.label.toLowerCase()}`);
        setAnalyticsSub('analytics-completeness-takeaway', `Field completeness · ${fmtInt(rows.length)} contacts sampled`);
        renderAnalyticsTable('analytics-completeness', ['Field', 'Filled'],
            completeness.map(d => [d.label, d.value + '%']));
    } else {
        setTakeaway('analytics-completeness-takeaway', 'No contacts to measure yet');
        setAnalyticsSub('analytics-completeness-takeaway', 'Field completeness');
        renderAnalyticsTable('analytics-completeness', ['Field', 'Filled'], [],
            { title: 'Waiting for contacts', hint: 'Extract a file to see field completeness.', icon: 'i-gauge' });
    }

    // Reachability — share of contacts reachable by email and/or phone.
    if (rows.length) {
        const both = rows.filter(r => (r.email_primary || r.email) && r.phone_primary).length;
        const emailOnly = rows.filter(r => (r.email_primary || r.email) && !r.phone_primary).length;
        const phoneOnly = rows.filter(r => !(r.email_primary || r.email) && r.phone_primary).length;
        const none = rows.length - both - emailOnly - phoneOnly;
        const reachablePct = Math.round((both + emailOnly + phoneOnly) / rows.length * 100);
        setTakeaway('analytics-reachability-takeaway', `${reachablePct}% of contacts are reachable`);
        setAnalyticsSub('analytics-reachability-takeaway', 'Reachability');
        renderAnalyticsTable('analytics-reachability', ['Reachability', 'Contacts', 'Share'], [
            ['Email & phone', fmtInt(both), Math.round(both / rows.length * 100) + '%'],
            ['Email only', fmtInt(emailOnly), Math.round(emailOnly / rows.length * 100) + '%'],
            ['Phone only', fmtInt(phoneOnly), Math.round(phoneOnly / rows.length * 100) + '%'],
            ['Unreachable', fmtInt(none), Math.round(none / rows.length * 100) + '%'],
        ]);
    } else {
        setTakeaway('analytics-reachability-takeaway', 'No contacts to measure yet');
        setAnalyticsSub('analytics-reachability-takeaway', 'Reachability');
        renderAnalyticsTable('analytics-reachability', ['Reachability', 'Contacts', 'Share'], [],
            { title: 'Waiting for contacts', hint: 'Reachability shows how many contacts have an email or phone.', icon: 'i-users' });
    }

    // Extraction sources — file types processed, from real history rows.
    if (historyRows.length) {
        const src = tallyBy(historyRows.map(j => ({ ext: (String(j.file || '').match(/\.([a-z0-9]+)$/i) || [,'other'])[1].toLowerCase() })), 'ext')
            .sort((a, b) => b.value - a.value);
        setTakeaway('analytics-sources-takeaway', `${src[0].label.toUpperCase()} files dominate extractions`);
        setAnalyticsSub('analytics-sources-takeaway', 'Extraction sources · ' + fmtInt(historyRows.length) + ' files');
        const total = src.reduce((a, d) => a + d.value, 0);
        renderAnalyticsTable('analytics-sources', ['File type', 'Files', 'Share'],
            src.map(d => ['.' + d.label, fmtInt(d.value), Math.round(d.value / total * 100) + '%']));
    } else {
        setTakeaway('analytics-sources-takeaway', 'No extractions yet');
        setAnalyticsSub('analytics-sources-takeaway', 'Extraction sources');
        renderAnalyticsTable('analytics-sources', ['File type', 'Files', 'Share'], [],
            { title: 'Waiting for extractions', hint: 'File types appear here after your first extraction.', icon: 'i-layers' });
    }
}

// ── Density toggle (comfortable / compact) ───────────────────────────────────

function toggleDensity(tableId) {
    const target = tableId ? document.getElementById(tableId) : null;
    const container = target ? target.closest('.table-container') : null;
    const btn = tableId ? document.querySelector(`[onclick="toggleDensity('${tableId}')"]`) : null;
    if (container) {
        const cur = container.getAttribute('data-density') === 'compact' ? 'comfortable' : 'compact';
        container.setAttribute('data-density', cur);
        try { localStorage.setItem('crm-density-' + tableId, cur); } catch (e) { /* ignore */ }
        if (btn) btn.setAttribute('aria-pressed', cur === 'compact' ? 'true' : 'false');
        return;
    }
    const cur = document.documentElement.getAttribute('data-density') === 'compact' ? 'comfortable' : 'compact';
    document.documentElement.setAttribute('data-density', cur);
    try { localStorage.setItem('crm-density', cur); } catch (e) { /* ignore */ }
    $$('.table-container').forEach(c => { c.setAttribute('data-density', cur); });
    $$('[id$="Density"]').forEach(b => b.setAttribute('aria-pressed', cur === 'compact' ? 'true' : 'false'));
}

// ── Ctrl+K command palette ───────────────────────────────────────────────────

const palette = {
    el: null, input: null, list: null,
    open: false, items: [], view: [], active: 0,
    contactTimer: null, built: false,
};

function paletteBuildStatic() {
    const views = [
        ['overview', 'Overview', 'i-dashboard'], ['extract', 'Extract', 'i-upload'],
        ['staged', 'Staged review', 'i-inbox'], ['contacts', 'Contacts', 'i-users'],
        ['emails', 'Emails', 'i-mail'], ['profiles', 'Customer Profiles', 'i-contact'],
        ['analytics', 'Analytics', 'i-chart'], ['quality', 'Data Quality', 'i-shield'],
        ['history', 'History', 'i-history'], ['settings', 'Settings', 'i-settings'],
    ];
    const items = views.map(([id, label, icon]) => ({
        group: 'Go to view', icon, label, type: 'View', kbd: '',
        run: () => showView(id),
    }));
    const actions = [
        { group: 'Actions', icon: 'i-refresh', label: 'Refresh data', type: 'Action', run: () => refreshData() },
        { group: 'Actions', icon: 'i-sun', label: 'Theme: Light', type: 'Action', run: () => setTheme('light') },
        { group: 'Actions', icon: 'i-moon', label: 'Theme: Dark', type: 'Action', run: () => setTheme('dark') },
        { group: 'Actions', icon: 'i-monitor', label: 'Theme: System', type: 'Action', run: () => setTheme('system') },
        { group: 'Actions', icon: 'i-download', label: 'Export contacts (CSV)', type: 'Action', run: () => { showView('contacts'); exportContacts(); } },
        { group: 'Actions', icon: 'i-x', label: 'Clear file queue', type: 'Action', run: () => { showView('extract'); clearQueue(); } },
        { group: 'Actions', icon: 'i-chevrons-left', label: 'Toggle sidebar', type: 'Action', run: () => toggleSidebar() },
        { group: 'Actions', icon: 'i-upload', label: 'Start new extraction', type: 'Action', run: () => showView('extract') },
    ];
    palette.items = items.concat(actions);
}

function fuzzyScore(query, text) {
    const q = query.toLowerCase(), s = text.toLowerCase();
    if (!q) return 1;
    let qi = 0, score = 0, streak = 0, prev = -2;
    for (let i = 0; i < s.length && qi < q.length; i++) {
        if (s[i] === q[qi]) {
            streak = prev === i - 1 ? streak + 1 : 1;
            score += 2 + streak + (i === 0 || /[\s\-_./]/.test(s[i - 1]) ? 3 : 0);
            prev = i; qi++;
        }
    }
    return qi === q.length ? score : -1;
}

function paletteRender() {
    const q = palette.input.value.trim();
    const scored = palette.items.map(it => ({ it, s: fuzzyScore(q, it.label + ' ' + it.type) }))
        .filter(x => x.s >= 0)
        .sort((a, b) => b.s - a.s);
    const contactResults = palette.contactResults || [];
    palette.view = scored.map(x => x.it).concat(contactResults);

    if (!palette.view.length) {
        palette.list.innerHTML = `<li class="palette-empty">No matches for “${esc(q)}”</li>`;
        palette.input.setAttribute('aria-activedescendant', '');
        return;
    }
    let html = '', lastGroup = null, idx = 0;
    palette.view.forEach((it) => {
        if (it.group !== lastGroup) {
            html += `<li class="palette-group" role="presentation">${esc(it.group)}</li>`;
            lastGroup = it.group;
        }
        html += `<li class="palette-opt${idx === palette.active ? ' is-active' : ''}" role="option" id="palette-opt-${idx}" aria-selected="${idx === palette.active}" data-idx="${idx}">
            <svg class="icon" aria-hidden="true"><use href="#${it.icon}"/></svg>
            <span class="palette-label">${esc(it.label)}</span>
            <span class="palette-type">${esc(it.type || '')}</span>
            ${it.kbd ? `<kbd class="palette-kbd">${esc(it.kbd)}</kbd>` : ''}
        </li>`;
        idx++;
    });
    palette.list.innerHTML = html;
    const activeEl = document.getElementById('palette-opt-' + palette.active);
    if (activeEl) {
        activeEl.scrollIntoView({ block: 'nearest' });
        palette.input.setAttribute('aria-activedescendant', 'palette-opt-' + palette.active);
    }
    $$('.palette-opt', palette.list).forEach(el => {
        el.addEventListener('click', () => paletteRun(Number(el.dataset.idx)));
        el.addEventListener('mousemove', () => {
            const i = Number(el.dataset.idx);
            if (palette.active !== i) { palette.active = i; paletteRender(); }
        });
    });
}

function paletteRun(idx) {
    const it = palette.view[idx];
    if (!it) return;
    paletteClose();
    if (it.run) it.run();
}

function paletteSearchContacts(q) {
    clearTimeout(palette.contactTimer);
    palette.contactTimer = setTimeout(async () => {
        try {
            const data = await api('/api/contacts?q=' + encodeURIComponent(q) + '&page=1&size=5');
            const rows = data.rows || [];
            palette.contactResults = rows.map(c => ({
                group: 'Contacts', icon: 'i-users', type: 'Contact',
                label: `${c.name || '(no name)'} — ${c.email_primary || c.email || 'no email'}`,
                run: () => viewContactProfile(c.id, c),
            }));
        } catch (e) { palette.contactResults = []; }
        paletteRender();
    }, 150);
}

function openPalette() {
    // Never open the palette under an open native modal <dialog> (e.g. the
    // confirm dialog) — focus is trapped by the modal and the state would
    // desync. Re-opening after the dialog closes is always possible via Ctrl+K.
    if (document.querySelector('dialog[open]')) return;
    const p = document.getElementById('palette');
    if (!p) return;
    palette.open = true;
    p.hidden = false;
    palette.input.value = '';
    palette.active = 0;
    palette.contactResults = [];
    paletteRender();
    palette.input.focus();
}

function paletteClose() {
    const p = document.getElementById('palette');
    if (!p) return;
    palette.open = false;
    p.hidden = true;
}

function initPalette() {
    palette.el = document.getElementById('palette');
    palette.input = document.getElementById('paletteInput');
    palette.list = document.getElementById('paletteList');
    if (!palette.el || !palette.input || !palette.list) return;
    paletteBuildStatic();
    // Native <dialog> dismissed (Esc, backdrop close, or programmatic close)
    // while the palette is open → palette state must follow the same close
    // event, not a stale in-memory flag.
    const confirmDlg = document.getElementById('confirmDialog');
    if (confirmDlg) confirmDlg.addEventListener('close', () => { if (palette.open) paletteClose(); });
    palette.input.addEventListener('input', () => {
        palette.active = 0;
        paletteRender();
        const q = palette.input.value.trim();
        if (q.length >= 2) paletteSearchContacts(q);
        else { palette.contactResults = []; paletteRender(); }
    });
    palette.input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); palette.active = Math.min(palette.view.length - 1, palette.active + 1); paletteRender(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); palette.active = Math.max(0, palette.active - 1); paletteRender(); }
        else if (e.key === 'Enter') { e.preventDefault(); paletteRun(palette.active); }
        else if (e.key === 'Escape') { e.preventDefault(); paletteClose(); }
    });
    palette.el.querySelector('[data-close-palette]').addEventListener('click', paletteClose);
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            if (palette.open) paletteClose(); else openPalette();
        } else if (e.key === 'Escape' && palette.open) {
            paletteClose();
        }
    });
}

// Legacy global search entry point now opens the palette.
function globalSearch() { openPalette(); }

// ── Initialization ──────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    syncAuthSession();

    // Dropzone: click, keyboard, and drag states (drag-and-drop is never the
    // only way — the Browse button always works).
    const dz = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    if (dz && fileInput) {
        dz.addEventListener('click', (e) => {
            if (e.target.closest('button')) return;   // the Browse button handles itself
            fileInput.click();
        });
        dz.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
        });
        dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag'); });
        dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
        dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('drag'); handleFiles(e.dataTransfer.files); });
    }

    // Theme (boot script already set attributes; applyTheme syncs UI + events)
    let savedMode = 'system';
    try { savedMode = localStorage.getItem('crm-theme-mode') || localStorage.getItem('crm-theme') || 'system'; } catch (e) { /* ignore */ }
    applyTheme(savedMode);
    if (window.matchMedia) {
        try {
            matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
                if ((document.documentElement.getAttribute('data-theme-mode') || 'system') === 'system') applyTheme('system');
            });
        } catch (e) { /* older browsers */ }
    }
    $$('input[name="theme-mode"]').forEach(r => r.addEventListener('change', () => setTheme(r.value)));

    // Sidebar collapsed state was restored pre-paint by the boot script
    const sbBtn = document.getElementById('sbToggleBtn');
    if (sbBtn) {
        sbBtn.setAttribute('aria-expanded', document.documentElement.classList.contains('sb-collapsed') ? 'false' : 'true');
    }

    // Row selection (bulk bar) — event delegation on the contacts table
    const contactsBody = document.getElementById('contactsBody');
    if (contactsBody) contactsBody.addEventListener('change', (e) => { if (e.target.classList.contains('row-check')) updateBulkBar(); });
    const checkAll = document.getElementById('contactsCheckAll');
    if (checkAll) checkAll.addEventListener('change', () => {
        const on = checkAll.checked;
        $$('#contactsBody .row-check').forEach(cb => { cb.checked = on; });
        updateBulkBar();
    });
    const stagedBody = document.getElementById('stagedContactsBody');
    if (stagedBody) stagedBody.addEventListener('change', (e) => { if (e.target.classList.contains('row-check')) syncStagedBulk(); });
    const stagedAll = document.getElementById('stagedCheckAll');
    if (stagedAll) stagedAll.addEventListener('change', () => {
        const on = stagedAll.checked;
        $$('#stagedContactsBody .row-check').forEach(cb => { cb.checked = on; });
        syncStagedBulk();
    });

    // Columns menu (popover where supported, hidden-toggle fallback otherwise)
    const colsBtn = document.getElementById('contactsColsBtn');
    const colsMenu = document.getElementById('contactsColsMenu');
    if (colsBtn && colsMenu) {
        const usePopover = 'popover' in colsMenu;
        if (!usePopover) colsMenu.hidden = true;
        colsBtn.addEventListener('click', () => {
            if (usePopover) { try { colsMenu.togglePopover(); } catch (e) { colsMenu.hidden = !colsMenu.hidden; } }
            else colsMenu.hidden = !colsMenu.hidden;
            colsBtn.setAttribute('aria-expanded', colsMenu.hidden ? 'false' : 'true');
        });
        if (!usePopover) {
            document.addEventListener('click', (e) => {
                if (!colsMenu.hidden && !e.target.closest('.menu-wrap')) { colsMenu.hidden = true; colsBtn.setAttribute('aria-expanded', 'false'); }
            });
        }
        colsMenu.addEventListener('change', (e) => {
            const col = e.target.dataset.col;
            if (!col) return;
            const table = document.getElementById('contactsTable');
            if (table) table.classList.toggle('hide-' + col, !e.target.checked);
        });
    }

    // Density init from stored preference
    try {
        if (localStorage.getItem('crm-density') === 'compact') {
            document.documentElement.setAttribute('data-density', 'compact');
            $$('.table-container').forEach(c => c.setAttribute('data-density', 'compact'));
            $$('[id$="Density"]').forEach(b => b.setAttribute('aria-pressed', 'true'));
        }
    } catch (e) { /* ignore */ }

    // Drawer + keyboard wiring
    document.addEventListener('keydown', stagedKeydown);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const drawer = document.getElementById('drawer');
            if (drawer && !drawer.hidden) closeDrawer();
        }
        if (e.key === 'Tab') {
            const drawer = document.getElementById('drawer');
            if (drawer && !drawer.hidden) {
                const focusables = $$('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])', drawer)
                    .filter(el => !el.disabled && el.offsetParent !== null);
                if (!focusables.length) return;
                const first = focusables[0], last = focusables[focusables.length - 1];
                if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
                else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
            }
        }
    });
    $$('[data-close-drawer]').forEach(el => el.addEventListener('click', closeDrawer));

    // Settings: unsaved-changes indicator
    ['crmDir', 'emlDir', 'watchInterval', 'watchEnabled'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', () => markSettingsDirty(true));
    });

    // Settings sub-nav click sets the active item
    $$('.settings-link').forEach(a => a.addEventListener('click', () => {
        $$('.settings-link').forEach(x => x.classList.remove('is-active'));
        a.classList.add('is-active');
    }));

    // Crossing the 900px breakpoint resets the off-canvas sidebar state
    if (window.matchMedia) {
        const mq = matchMedia('(max-width: 900px)');
        const onBreak = () => {
            if (!mq.matches && document.body.classList.contains('sb-open')) {
                document.body.classList.remove('sb-open');
                const bd = document.getElementById('sidebarBackdrop');
                if (bd) bd.hidden = true;
            }
        };
        try { mq.addEventListener('change', onBreak); } catch (e) { mq.addListener(onBreak); }
    }

    // Command palette (wrapped so a failure can never break the app)
    try { initPalette(); } catch (e) { console.warn('Palette init skipped:', e); }

    // Initial view from hash
    const hash = location.hash.replace('#/', '').replace('#', '');
    showView(VIEW_TITLES[hash] ? hash : 'overview');
});
