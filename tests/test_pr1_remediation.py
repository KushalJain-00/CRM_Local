# tests/test_pr1_remediation.py — regression tests for the PR #1 remediation
# Changes pinned here (PR #1 review findings):
#   Fix 1  API_BASE no longer double-prefixes '/api'
#   Fix 2  extraction uploads real multipart bytes, not bare filenames
#   Fix 4  Analytics = data tables only (D-012: no charts or graphs)
#   Fix 5  settings api_key is HTML-escaped
#   Fix 6  csvCell neutralizes spreadsheet formula injection
#   Fix 7  table sort state reads data-sort attributes
#   Fix 8  command palette syncs with native dialog close events
# Static-content tests follow the documented test_ratchet.py pattern: those
# defects live only in frontend JS with no Python entry point, so the pinned
# defect pattern in static assets is the unit-level check available.
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def _js() -> str:
    return (ROOT / "static" / "app.js").read_text("utf-8")


def _html() -> str:
    return (ROOT / "static" / "index.html").read_text("utf-8")


def _css() -> str:
    return (ROOT / "static" / "style.css").read_text("utf-8")


def _multipart(files_dict):
    files = [(k, v) for k, v in files_dict.items()]
    return client.post("/api/intake", files=files)


# ── Fix 1: no double /api prefix ─────────────────────────────────────────────

def test_api_base_is_host_prefix_not_route_prefix():
    m = re.search(r"const API_BASE = (.*?)\.replace", _js())
    assert m, "API_BASE assignment missing"
    expr = m.group(1)
    assert "'/api'" not in expr, "API_BASE must not default to '/api' (api() paths already include the prefix)"
    assert "''" in expr, "same-origin default must be an empty host prefix"


# ── Fix 2: real multipart upload against the live API ───────────────────────

def test_multipart_upload_processes_real_csv(data_dir):
    csv = "Name,Email\nAsha Rao,asha@example.com\nBob Ray,bob@example.com\n"
    r = _multipart({"files": ("contacts.csv", csv.encode("utf-8"))})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"][0]["status"] == "OK", body["results"]
    assert body["results"][0]["contacts_found"] >= 2
    assert body["counts"]["new"] >= 2
    # Phase-1 backend reality (D-030: write-path redirection ships in Phase 2
    # with v7): intake resolves uploaded bytes into canonical `contacts`, and
    # there is no /api/contacts list router yet. Verify at the DB surface.
    import db
    con = db.connect("crm")
    rows = [tuple(r) for r in con.execute(
        "SELECT name, email_primary FROM contacts").fetchall()]
    assert ("Asha Rao", "asha@example.com") in rows
    # staged review surface stays queryable (empty until Phase 2 staging)
    assert client.get("/api/staged-contacts?page=1&size=50").status_code == 200


def test_multipart_upload_multiple_files_in_one_batch(data_dir):
    files = (
        ("files", ("one.csv", b"Name,Email\nCarol Chen,carol@example.com\n")),
        ("files", ("two.csv", b"Name,Email\nDan Diaz,dan@example.com\nDave Dee,dave@example.com\n")),
    )
    r = client.post("/api/intake", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["new"] >= 3
    assert len(body["results"]) == 2


def test_multipart_empty_file_yields_zero_contacts(data_dir):
    r = _multipart({"files": ("empty.csv", b"")})
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["new"] == 0


def test_front_end_uploads_file_objects_not_bare_names():
    js = _js()
    intake_calls = [seg.split(");")[0] for seg in js.split("/api/intake")[1:]]
    assert intake_calls
    for call in intake_calls:
        assert "JSON.stringify" not in call, "intake must send bytes, not a paths list"
    assert "fd.append('files'" in js


# ── Fix 4: analytics is tables-only (D-012) ──────────────────────────────────

def test_analytics_has_no_chart_rendering_code():
    js = _js()
    for name in ("renderBarChart", "renderDonutChart", "renderProgressChart",
                 "ChartCache", "chartGrowthObserver", "watchChartContainer",
                 "rerenderCharts"):
        assert name not in js, f"{name} is dead chart code and must be removed"
    html = _html()
    analytics = html.split('id="view-analytics"')[1].split('id="view-quality"')[0]
    for pattern in ("chart-host", "data-charttable", "chart-geo", "chart-completeness",
                    "chart-reachability", "chart-sources", "chart-card"):
        assert pattern not in analytics, pattern
    css = _css()
    for pattern in (".chart-row", ".chart-fill", ".chart-track", ".donut-", ".chart-donut"):
        assert pattern not in css, pattern


def test_analytics_renders_visible_data_tables():
    js = _js()
    html = _html()
    assert 'id="analytics-geo"' in html and 'id="analytics-sources"' in html
    assert "renderAnalyticsTable" in js and 'table class="analytics-table"' in js
    assert "loadAnalytics" in js
    for host in ("analytics-geo", "analytics-completeness", "analytics-reachability", "analytics-sources"):
        assert host in js


# ── Fix 5: settings escapes untrusted values ────────────────────────────────

def test_settings_renders_escaped_api_key():
    js = _js()
    for m in re.finditer(r"[\s\S]{40}entry\.api_key\b(?!_set)", js):
        ctx = js[m.start():m.start() + 80]
        assert "esc(" in ctx, f"api_key rendered into HTML without esc(): {ctx}"


# ── Fix 6: CSV formula injection ─────────────────────────────────────────────

def _csv_cell_via_node(values):
    fn = re.search(r"function csvCell\(v\) \{[\s\S]*?\n\}", _js()).group(0)
    script = f"{fn}\nconsole.log(JSON.stringify({values!r}.map(csvCell)));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_csv_cell_neutralizes_formula_injection():
    cells = _csv_cell_via_node(["=1+1", "+foo", "-5", "-abc", "@cmd", "\ttab", "\rCR", "Asha"])
    assert cells[0] == "'=1+1"
    assert cells[1] == "'+foo"
    assert cells[2] == "-5", "legitimate negative numbers must survive"
    assert cells[3] == "'-abc"
    assert cells[4] == "'@cmd"
    assert cells[5] == "'\ttab"
    assert cells[6] == "\"'\rCR\"", "CR cell: prefix then CSV-quote wraps the value with "" inside"
    assert cells[7] == "Asha"


def test_csv_cell_source_keeps_injection_guard():
    body = re.search(r"function csvCell\(v\) \{[\s\S]*?\n\}", _js())
    assert body, "csvCell must keep its injection guard"
    text = body.group(0)
    for tok in ("=", "+", "@"):
        assert tok in text, f"csvCell guard lost trigger {tok!r}"
    assert r"\t" in text and r"\r" in text, "csvCell guard lost tab/CR triggers"
    assert "Number(" in text, "csvCell must preserve legitimate negative numbers"


# ── Fix 7: sort state from data-sort attributes ─────────────────────────────

def test_sortable_headers_have_data_sort():
    html = _html()
    th_blocks = re.findall(r"<th\b[^>]*>.*?</th>", html, re.S)
    sort_ths = [b for b in th_blocks if re.search(r"onclick=\"sort(Contacts|Emails|History)\('", b)]
    assert sort_ths
    for blk in sort_ths:
        field = re.search(r"sort(?:Contacts|Emails|History)\('([a-z_]+)'\)", blk).group(1)
        assert f'data-sort="{field}"' in blk, f"sortable <th> for {field} lacks data-sort"


def test_update_sort_ui_reads_data_sort_not_onclick():
    m = re.search(r"function updateSortUI[^{]*\{[\s\S]*?\n\}", _js())
    assert m, "updateSortUI missing"
    assert "data-sort" in m.group(0), "updateSortUI must read data-sort"
    assert "onclick" not in m.group(0), "onclick regex parsing must be gone"


# ── Fix 8: palette / native dialog close sync ────────────────────────────────

def test_palette_never_opens_under_a_native_modal():
    fn = _js().split("function openPalette", 1)[1].split("function ", 1)[0]
    assert "dialog[open]" in fn, "openPalette must guard against an open native <dialog>"


def test_confirm_dialog_close_closes_palette():
    js = _js()
    assert "confirmDlg.addEventListener('close'" in js
    assert "palette.open) paletteClose" in js


# ── Upload workflow end-to-end against the real API ────────────────────────
# Phase-1 note (D-030): the full staged-approve loop is the Phase 2 write-path
# redirection; today intake resolves real uploaded bytes into canonical
# contacts, which is what the redesigned frontend surfaces.

def test_upload_and_resolve_full_workflow(data_dir):
    csv = "Name,Email,Company\nRavi Kumar,ravi@example.com,Acme\n"
    up = _multipart({"files": ("vendor.csv", csv.encode("utf-8"))})
    assert up.status_code == 200 and up.json()["counts"]["new"] >= 1

    import db
    con = db.connect("crm")
    rows = [tuple(r) for r in con.execute(
        "SELECT name, email_primary, company FROM contacts WHERE email_primary = ?",
        ("ravi@example.com",)).fetchall()]
    assert rows == [("Ravi Kumar", "ravi@example.com", "Acme")]
