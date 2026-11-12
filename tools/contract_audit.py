#!/usr/bin/env python3
"""Contract audit: inline-handler functions defined, required IDs present."""
import re
from pathlib import Path

S = Path(__file__).resolve().parent.parent / "static"
html = (S / "index.html").read_text()
js = (S / "app.js").read_text()

# 1. functions used by inline handlers in HTML
handlers = set()
for m in re.finditer(r'on(?:click|change|input|drop|dragover)=["\']([^"\']+)["\']', html):
    for fn in re.findall(r'([A-Za-z_$][\w$]*)\s*\(', m.group(1)):
        handlers.add(fn)
# functions called from generated HTML strings inside app.js
gen = set(re.findall(r'onclick="(?:closeDrawer\(\); )?([A-Za-z_$][\w$]*)\(', js))
# spec-required names
required = {
    "toggleSidebar", "showView", "refreshData", "handleDrop", "handleFiles", "startExtraction",
    "clearQueue", "searchContacts", "filterContacts", "exportContacts", "sortContacts",
    "searchEmails", "addProvider", "pickFolder", "setTheme", "saveSettings",
    "approveContact", "rejectContact", "dismissContact", "deleteContact", "editContact",
    "editStagedContact", "viewContactProfile", "removeFromQueue", "renderFileQueue",
    "loadOverview", "loadContacts", "loadEmails", "loadCustomerProfiles", "loadDataQuality",
    "loadHistory", "loadSettings", "renderSettings", "addProviderSetting",
    "updateProviderSetting", "removeProviderSetting", "globalSearch", "syncAuthSession",
    "api", "apiFormData", "esc", "renderPagination", "renderContactsTable", "renderEmailsTable",
    "renderCustomerProfiles", "renderStagedContactsTable", "renderStagedPagination",
    "loadStagedContacts", "cycleTheme", "openPalette", "closeDrawer",
}
BUILTINS = {"getElementById", "click", "togglePopover", "showPopover", "hidePopover"}
missing = []
for fn in sorted((handlers - BUILTINS) | gen | required):
    if fn in BUILTINS:
        continue
    if not re.search(rf'(?:^|\n)\s*(?:async\s+)?function\s+{re.escape(fn)}\s*\(', js):
        missing.append(fn)
print("HANDLERS USED:", len((handlers - BUILTINS) | gen | required))
print("MISSING DEFINITIONS:", missing or "none")

# 2. required element IDs
required_ids = [
    "topTitle", "main-content", "kpi-contacts", "kpi-emails", "kpi-files", "kpi-new",
    "kpi-dupes", "kpi-completeness", "recent-activity", "dropZone", "fileInput", "fileQueue",
    "extractBtn", "progress", "progressFill", "progressText", "extractResults",
    "contactSearch", "contactFilter", "contactsTable", "contactsBody", "contactsPagination",
    "emailSearch", "emailsTable", "emailsBody", "emailsPagination", "profilesList",
    "chart-geo", "chart-completeness", "chart-reachability", "chart-sources",
    "quality-invalid-emails", "quality-invalid-phones", "quality-missing", "quality-dupes",
    "historyTable", "historyBody", "providerChain", "crmDir", "emlDir", "themeSelect",
    "watchInterval", "watchEnabled", "stagedContactsBody", "stagedPagination",
]
ids_in_html = set(re.findall(r'id="([^"]+)"', html))
ids_in_js = set(re.findall(r"getElementById\('([^']+)'\)", js)) | set(re.findall(r'id="([^"]+)"', js))
miss_ids = [i for i in required_ids if i not in ids_in_html and i not in ids_in_js]
print("MISSING IDS:", miss_ids or "none")

# 3. no external resources
ext = re.findall(r'(?:src|href)="(https?://[^"]+)"', html) + re.findall(r'url\((?:["\']?)https?://[^)]+\)', js) + re.findall(r'url\((?:["\']?)https?://[^)]+\)', (S / "style.css").read_text())
print("EXTERNAL URLS:", ext or "none")

# 4. suspicious truncations like 'TITLESash'
sus = [w for w in re.findall(r'\b(\w{6,})ash\]', js) ]
print("SUSPICIOUS PATTERNS:", sus or "none")

# 5. API endpoints preserved
endpoints = sorted(set(re.findall(r"api\('([^']+)'", js) + re.findall(r'api\(`/([^`]+)`', js)))
print("API CALLS:", endpoints)
