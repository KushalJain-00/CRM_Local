// app.js — three views, no framework, no CDN.
"use strict";

const state = {
  view: "run",
  silo: "crm",
  page: 1,
  size: 50,
  q: "",
  total: 0,
  config: null,
  chain: [],
  editing: null,
  lastLog: 0,
  wasRunning: false,
};

const CONTACT_FIELDS = [
  ["name", "Name"], ["email_primary", "Email"], ["email_secondary", "Alt email"],
  ["phone_primary", "Phone"], ["phone_secondary", "Alt phone"], ["company", "Company"],
  ["designation", "Designation"], ["address", "Address"], ["city", "City"],
  ["pincode", "Pincode"], ["website", "Website"],
];

const MODEL_HINTS = {
  openrouter: "anthropic/claude-3.5-sonnet",
  groq: "llama-3.3-70b-versatile",
  gemini: "gemini-2.0-flash",
  openai: "gpt-4o-mini",
  deepseek: "deepseek-chat",
  anthropic: "claude-3-5-sonnet-latest",
  ollama: "llama3.1",
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* keep statusText */ }
    throw new Error(detail);
  }
  return res.json();
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child != null) node.append(child);
  }
  return node;
}

function toast(message, isError = false) {
  const node = $("toast");
  node.textContent = message;
  node.className = isError ? "toast err" : "toast";
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.hidden = true; }, 3200);
}

// ── Navigation ────────────────────────────────────────────
function showView(name) {
  state.view = name;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${name}`));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === name));
  if (name === "contacts") loadContacts();
  if (name === "settings") renderChain();
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

// ── Status polling ────────────────────────────────────────
async function refreshStatus() {
  const data = await api("/api/status");
  $("stat-crm").textContent = data.counts.crm;
  $("stat-eml").textContent = data.counts.eml;
  $("stat-emails").textContent = data.counts.eml_emails;
  $("stat-pending").textContent = data.pending.crm + data.pending.eml;
  $("pending-crm").textContent = `${data.pending.crm} new`;
  $("pending-eml").textContent = `${data.pending.eml} new`;
  $("tab-crm").textContent = data.counts.crm;
  $("tab-eml").textContent = data.counts.eml;
  $("version").textContent = `v${data.version}`;

  const run = data.run;
  $("run-status").textContent = run.running ? "Running" : "Idle";
  $("run-status").classList.toggle("live", run.running);
  renderRunStats(run.stats);
  renderLog(run.log);

  if (state.wasRunning && !run.running) {
    loadContacts();
    toast("Scan finished");
  }
  state.wasRunning = run.running;
}

function renderRunStats(stats) {
  const box = $("run-stats");
  box.replaceChildren();
  const pairs = [
    ["Files", stats.files], ["New", stats.new], ["Merged", stats.merged],
    ["Duplicates", stats.duplicates], ["Errors", stats.errors],
  ];
  for (const [label, value] of pairs) {
    box.append(el("span", {}, [el("b", { text: String(value) }), ` ${label}`]));
  }
}

function renderLog(lines) {
  const box = $("log");
  if (lines.length === state.lastLog) return;
  state.lastLog = lines.length;
  box.replaceChildren();
  for (const line of lines) {
    box.append(el("div", { class: `log-line ${line.level}` }, [
      el("time", { text: line.time }),
      el("span", { text: line.msg }),
    ]));
  }
  box.scrollTop = box.scrollHeight;
}

// ── Run actions ───────────────────────────────────────────
async function startScan(which) {
  try {
    await api("/api/scan", { method: "POST", body: JSON.stringify({ which }) });
    toast(`Scanning ${which === "all" ? "both folders" : which.toUpperCase()}`);
  } catch (err) {
    toast(err.message, true);
  }
}

$("scan-all").addEventListener("click", () => startScan("all"));
$("scan-crm").addEventListener("click", () => startScan("crm"));
$("scan-eml").addEventListener("click", () => startScan("eml"));

document.querySelectorAll("[data-pick]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const which = btn.dataset.pick;
    btn.disabled = true;
    try {
      const current = state.config[`${which}_dir`] || "";
      const data = await api("/api/pick-folder", {
        method: "POST", body: JSON.stringify({ initial: current }),
      });
      if (!data.path) return;
      state.config[`${which}_dir`] = data.path;
      await api("/api/config", {
        method: "POST", body: JSON.stringify({ [`${which}_dir`]: data.path }),
      });
      renderFolders();
      await refreshStatus();
    } catch (err) {
      toast(err.message, true);
    } finally {
      btn.disabled = false;
    }
  });
});

document.querySelectorAll("[data-open]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const which = btn.dataset.open;
    const path = state.config[`${which}_dir`];
    if (!path) return toast("Choose a folder first", true);
    try {
      await api("/api/open-folder", { method: "POST", body: JSON.stringify({ initial: path }) });
    } catch (err) {
      toast(err.message, true);
    }
  });
});

function renderFolders() {
  $("path-crm").textContent = state.config.crm_dir || "Not set";
  $("path-eml").textContent = state.config.eml_dir || "Not set";
  $("watch-toggle").checked = !!state.config.watch;
  $("watch-interval").value = state.config.watch_interval || 30;
  $("autostart-toggle").checked = !!state.config.autostart;
}

$("watch-toggle").addEventListener("change", async (event) => {
  try {
    await api("/api/config", {
      method: "POST", body: JSON.stringify({ watch: event.target.checked }),
    });
    toast(event.target.checked ? "Watch mode on" : "Watch mode off");
  } catch (err) {
    toast(err.message, true);
  }
});

$("watch-interval").addEventListener("change", async (event) => {
  const seconds = Math.max(10, Number(event.target.value) || 30);
  event.target.value = seconds;
  try {
    await api("/api/config", {
      method: "POST", body: JSON.stringify({ watch_interval: seconds }),
    });
  } catch (err) {
    toast(err.message, true);
  }
});

$("autostart-toggle").addEventListener("change", async (event) => {
  try {
    const data = await api("/api/autostart", {
      method: "POST", body: JSON.stringify({ enabled: event.target.checked }),
    });
    if (!data.ok) {
      event.target.checked = false;
      toast(data.error || "Could not change autostart", true);
    }
  } catch (err) {
    event.target.checked = false;
    toast(err.message, true);
  }
});

// ── Contacts ──────────────────────────────────────────────
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    state.silo = tab.dataset.silo;
    state.page = 1;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t === tab));
    loadContacts();
  });
});

let searchTimer = null;
$("search").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = event.target.value.trim();
    state.page = 1;
    loadContacts();
  }, 250);
});

$("prev-page").addEventListener("click", () => {
  if (state.page > 1) { state.page -= 1; loadContacts(); }
});
$("next-page").addEventListener("click", () => {
  if (state.page * state.size < state.total) { state.page += 1; loadContacts(); }
});

$("export-btn").addEventListener("click", () => {
  window.location.href = `/api/export?which=${state.silo}`;
});

async function loadContacts() {
  try {
    const data = await api(`/api/contacts?which=${state.silo}&q=${encodeURIComponent(state.q)}&page=${state.page}&size=${state.size}`);
    state.total = data.total;
    renderTable(data.rows);
    const pages = Math.max(1, Math.ceil(data.total / state.size));
    $("page-label").textContent = `Page ${state.page} of ${pages}`;
    $("table-total").textContent = `${data.total} contact${data.total === 1 ? "" : "s"}`;
    $("prev-page").disabled = state.page <= 1;
    $("next-page").disabled = state.page >= pages;
  } catch (err) {
    toast(err.message, true);
  }
}

function renderTable(rows) {
  const body = $("contacts-body");
  body.replaceChildren();
  $("contacts-empty").hidden = rows.length > 0;

  for (const row of rows) {
    const tr = el("tr", { tabindex: "0" }, [
      el("td", { text: row.name || "—" }),
      el("td", { class: "clip", text: row.email_primary || "—" }),
      el("td", { text: row.phone_primary || "—" }),
      el("td", { class: "clip", text: row.company || "—" }),
      el("td", { class: "clip", text: row.designation || "—" }),
      el("td", { text: row.city || "—" }),
      el("td", { class: "actions" }, [
        el("button", {
          class: "icon-btn", "aria-label": "Edit contact",
          onclick: (event) => { event.stopPropagation(); openDrawer(row); },
        }, [iconPencil()]),
      ]),
    ]);
    tr.addEventListener("click", () => openDrawer(row));
    tr.addEventListener("keydown", (event) => {
      if (event.key === "Enter") openDrawer(row);
    });
    body.append(tr);
  }
}

function iconPencil() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M4 20h4l10-10-4-4L4 16v4zM14 6l4 4");
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.7");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.append(path);
  return svg;
}

// ── Edit drawer ───────────────────────────────────────────
function openDrawer(row) {
  state.editing = row;
  const form = $("contact-form");
  form.replaceChildren();
  for (const [field, label] of CONTACT_FIELDS) {
    const input = el("input", { name: field, value: row[field] || "", autocomplete: "off" });
    form.append(el("div", { class: "field" }, [el("label", { text: label }), input]));
  }
  $("drawer").hidden = false;
  $("drawer-scrim").hidden = false;
  form.querySelector("input")?.focus();
}

function closeDrawer() {
  state.editing = null;
  $("drawer").hidden = true;
  $("drawer-scrim").hidden = true;
}

$("drawer-close").addEventListener("click", closeDrawer);
$("drawer-scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDrawer();
});

$("contact-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.editing) return;
  const fields = {};
  for (const [field] of CONTACT_FIELDS) {
    fields[field] = event.target.elements[field].value.trim() || null;
  }
  try {
    await api(`/api/contacts/${state.silo}/${state.editing.id}`, {
      method: "PATCH", body: JSON.stringify({ fields }),
    });
    closeDrawer();
    loadContacts();
    refreshStatus();
    toast("Contact saved");
  } catch (err) {
    toast(err.message, true);
  }
});

$("delete-contact").addEventListener("click", async () => {
  if (!state.editing) return;
  if (!confirm("Delete this contact? This cannot be undone.")) return;
  try {
    await api(`/api/contacts/${state.silo}/${state.editing.id}`, { method: "DELETE" });
    closeDrawer();
    loadContacts();
    refreshStatus();
    toast("Contact deleted");
  } catch (err) {
    toast(err.message, true);
  }
});

// ── Settings: provider chain ──────────────────────────────
function newEntry(provider = "openrouter") {
  return {
    provider,
    model: MODEL_HINTS[provider] || "",
    api_key: "",
    base_url: provider === "ollama" ? "http://localhost:11434" : "",
    enabled: true,
  };
}

function renderChain() {
  const box = $("chain");
  box.replaceChildren();
  if (!state.chain.length) {
    box.append(el("div", { class: "chain-empty", text: "No provider. Extraction uses local pattern matching only." }));
    return;
  }

  state.chain.forEach((entry, index) => {
    const card = el("div", { class: "entry" });

    const ord = el("div", { class: "ord" }, [
      el("button", {
        class: "icon-btn", "aria-label": "Move up", title: "Move up",
        onclick: () => moveEntry(index, -1),
      }, ["↑"]),
      el("span", { class: "muted small", text: String(index + 1) }),
      el("button", {
        class: "icon-btn", "aria-label": "Move down", title: "Move down",
        onclick: () => moveEntry(index, 1),
      }, ["↓"]),
    ]);

    const providerSelect = el("select", {
      onchange: (event) => {
        entry.provider = event.target.value;
        entry.model = MODEL_HINTS[entry.provider] || "";
        entry.base_url = entry.provider === "ollama" ? (entry.base_url || "http://localhost:11434") : "";
        renderChain();
      },
    }, Object.keys(MODEL_HINTS).map((name) =>
      el("option", { value: name, text: name, ...(name === entry.provider ? { selected: "" } : {}) })
    ));

    const modelInput = el("input", {
      value: entry.model || "", placeholder: MODEL_HINTS[entry.provider],
      oninput: (event) => { entry.model = event.target.value; },
    });

    const keyInput = el("input", {
      type: "password", value: entry.api_key || "",
      placeholder: entry.provider === "ollama" ? "not needed" : "API key",
      autocomplete: "off",
      oninput: (event) => { entry.api_key = event.target.value; },
    });

    const actions = el("div", { class: "entry-actions" }, [
      el("label", { class: "small muted", style: "flex-direction:row;align-items:center;gap:6px" }, [
        el("input", {
          type: "checkbox", ...(entry.enabled ? { checked: "" } : {}),
          onchange: (event) => { entry.enabled = event.target.checked; },
        }),
        "on",
      ]),
      el("button", {
        class: "icon-btn", "aria-label": "Remove provider", title: "Remove",
        onclick: () => { state.chain.splice(index, 1); renderChain(); },
      }, ["✕"]),
    ]);

    const testBtn = el("button", {
      class: "btn ghost", type: "button",
      onclick: async () => {
        testBtn.disabled = true;
        testBtn.textContent = "Testing…";
        try {
          const data = await api("/api/test-llm", { method: "POST", body: JSON.stringify(entry) });
          out.className = data.ok ? "test-out ok" : "test-out err";
          out.textContent = data.ok ? "Works" : data.result;
        } catch (err) {
          out.className = "test-out err";
          out.textContent = err.message;
        } finally {
          testBtn.disabled = false;
          testBtn.textContent = "Test";
        }
      },
    }, ["Test"]);

    const out = el("div", { class: "test-out" });

    card.append(
      ord,
      el("label", {}, ["Provider", providerSelect]),
      el("label", {}, ["Model", modelInput]),
      el("label", {}, [entry.provider === "ollama" ? "Host URL" : "API key",
        entry.provider === "ollama"
          ? el("input", {
              value: entry.base_url || "http://localhost:11434",
              oninput: (event) => { entry.base_url = event.target.value; },
            })
          : keyInput]),
      actions,
      el("div", { class: "entry-actions", style: "grid-column: 2 / -1" }, [testBtn]),
      out,
    );
    box.append(card);
  });
}

function moveEntry(index, delta) {
  const target = index + delta;
  if (target < 0 || target >= state.chain.length) return;
  const [entry] = state.chain.splice(index, 1);
  state.chain.splice(target, 0, entry);
  renderChain();
}

$("add-provider").addEventListener("click", () => {
  state.chain.push(newEntry());
  renderChain();
});

$("save-settings").addEventListener("click", async () => {
  try {
    const cfg = await api("/api/config", {
      method: "POST", body: JSON.stringify({ chain: state.chain }),
    });
    state.config = cfg;
    toast("Settings saved");
  } catch (err) {
    toast(err.message, true);
  }
});

// ── Theme ─────────────────────────────────────────────────
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("theme-label").textContent = theme === "dark" ? "Light" : "Dark";
  localStorage.setItem("crm-theme", theme);
}

$("theme-toggle").addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

// ── Boot ──────────────────────────────────────────────────
async function boot() {
  applyTheme(localStorage.getItem("crm-theme") || "light");
  try {
    state.config = await api("/api/config");
    state.chain = Array.isArray(state.config.chain) ? state.config.chain : [];
    renderFolders();
    $("data-config").textContent = state.config.config_path || "—";
    $("data-crm").textContent = state.config.crm_db_path || "—";
    $("data-eml").textContent = state.config.eml_db_path || "—";
    await refreshStatus();
    await loadContacts();
    setInterval(refreshStatus, 1500);
  } catch (err) {
    toast(err.message, true);
  }
}

boot();
