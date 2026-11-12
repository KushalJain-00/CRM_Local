#!/usr/bin/env python3
"""Mock CRM Local backend for offline testing of the redesigned frontend.

Serves the static/ directory and aliases every /api route under BOTH /api/*
and /api/api/* (the app keeps the original '/api' + '/api/...' path shape,
which yields '/api/api/...' when CRM_API_BASE is unset — see Issues noticed).
Run:  python tools/mock_api.py  →  http://localhost:8787
"""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PORT = 8787

FIRST = ["Anna", "Ben", "Carla", "Daniel", "Elena", "Felix", "Greta", "Henrik",
         "Iris", "Jonas", "Klara", "Liam", "Mara", "Nils", "Oda", "Pia",
         "Quinn", "Rosa", "Sam", "Tessa"]
LAST = ["Meyer", "Schulz", "Weber", "Fischer", "Wagner", "Becker", "Hoffmann",
        "Schaefer", "Koch", "Richter", "Klein", "Wolf", "Neumann", "Schwarz"]
COMPANIES = ["Nordwind GmbH", "Baltic Logistics", "Alpen Trading", "Rhein Tech",
             "Elbe Media", "Hansa Consulting", "Spree Digital", "Falkensee AG"]
COUNTRIES = ["Germany", "United States", "Austria", "Netherlands", "Poland"]
STATUSES = ["OK", "OK", "OK", "ERROR"]

def contacts_rows(n=60):
    rows = []
    for i in range(1, n + 1):
        name = f"{FIRST[i % len(FIRST)]} {LAST[i % len(LAST)]}"
        rows.append({
            "id": i,
            "name": name,
            "email_primary": "" if i % 13 == 0 else f"{name.split()[0].lower()}.{name.split()[1].lower()}@example.com",
            "phone_primary": "" if i % 7 == 0 else f"+49 30 {(1000000 + i * 7919) % 9999999}",
            "company": "" if i % 9 == 0 else COMPANIES[i % len(COMPANIES)],
            "country": "" if i % 5 == 0 else COUNTRIES[i % len(COUNTRIES)],
            "source_file": f"leads_q{i % 4 + 1}.xlsx" if i % 3 else f"mail_dump_{i % 5}.eml",
            "sheet": "Contacts",
            "row_number": i + 2,
            "created_at": f"2026-1{(i % 3) + 1}-0{(i % 8) + 1}T10:{i % 60:02d}:00",
        })
    return rows

ROWS = contacts_rows()
EMAILS = [{"subject": f"Quotation request #{1000 + i}", "sender_name": f"{FIRST[i % len(FIRST)]} {LAST[i % len(LAST)]}",
           "date": f"2026-10-{(i % 28) + 1:02d}T14:0{i % 9}:00", "contact_count": (i * 3) % 12} for i in range(1, 41)]
JOBS = {"results": [
    {"file": "leads_q1.xlsx", "status": "OK", "contacts_found": 84, "processed_at": "2026-11-01T09:12:00"},
    {"file": "mail_dump_3.eml", "status": "OK", "contacts_found": 26, "processed_at": "2026-11-02T16:40:00"},
    {"file": "expo_contacts.csv", "status": "OK", "contacts_found": 312, "processed_at": "2026-11-04T11:05:00"},
    {"file": "broken_scan.pdf", "status": "ERROR", "contacts_found": 0, "processed_at": "2026-11-05T08:31:00"},
    {"file": "partners.xls", "status": "OK", "contacts_found": 57, "processed_at": "2026-11-06T13:22:00"},
]}
STAGED = [{"id": i, "name": f"{FIRST[(i * 3) % len(FIRST)]} {LAST[(i * 5) % len(LAST)]}",
           "email": f"stage{i}@example.com" if i % 4 else "",
           "phone_primary": f"+49 170 {100000 + i * 977}" if i % 3 else "",
           "company": COMPANIES[i % len(COMPANIES)],
           "review_status": ["NEW", "NEEDS_REVIEW", "READY", "APPROVED", "REJECTED", "DISMISSED"][i % 6],
           "dedup_status": ["NOT_CHECKED", "UNIQUE", "PROBABLE_DUPLICATE", "EXACT_DUPLICATE"][i % 4],
           "import_status": ["NOT_IMPORTED", "NEW_CONTACT_CREATED", "EXISTING_CONTACT_ENRICHED"][i % 3],
           "confidence": 0.62 + (i % 5) * 0.08,
           "source_file": f"leads_q{(i % 4) + 1}.xlsx", "sheet": "Leads", "row_number": 10 + i,
           "extracted_at": f"2026-11-0{(i % 6) + 1}T12:30:00"}
          for i in range(1, 27)]
SETTINGS = {"chain": [
    {"provider": "openai", "model": "gpt-4o-mini", "api_key_set": True, "enabled": True},
    {"provider": "anthropic", "model": "claude-haiku", "api_key_set": False, "enabled": False},
], "crm_dir": r"C:\CRM\data", "eml_dir": r"C:\MailDump", "watch_interval": 30, "watch_enabled": True}
DEDUP = {"rows": [
    {"field": "email_primary", "status": "12 invalid", "severity": "error"},
    {"field": "phone_primary", "status": "7 suspect", "severity": "warning"},
    {"field": "company", "status": "63 missing", "severity": "warning"},
    {"field": "name+email", "status": "18 duplicate pairs", "severity": "warning"},
]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload, ctype="application/json"):
        body = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _api(self, method):
        path = self.path.split("?")[0]
        # strip the double prefix so /api/api/x and /api/x hit the same handler
        route = re.sub(r"^/api(/api)?", "", path) or "/"
        q = self.path
        if route == "/status":
            return self._send(200, {"counts": {
                "crm": 1284, "emails": 3562, "processed_files": 47, "new": 23,
                "duplicates": 18, "eml_contacts": 512, "invalid_emails": 12,
                "invalid_phones": 7, "incomplete_records": 63, "staged": 9,
            }, "run": {"extraction_run_id": "run_8f3k2", "status": "completed",
                       "finished_at": "2026-11-07T08:15:00"}})
        if route == "/contacts":
            m = re.search(r"[?&]q=([^&]*)", q)
            rows = ROWS
            if m and m.group(1):
                needle = m.group(1).lower()
                rows = [r for r in rows if needle in r["name"].lower() or needle in r["email_primary"].lower()
                        or needle in r["company"].lower()]
            page = int(re.search(r"[?&]page=(\d+)", q).group(1)) if re.search(r"[?&]page=(\d+)", q) else 1
            size = int(re.search(r"[?&]size=(\d+)", q).group(1)) if re.search(r"[?&]size=(\d+)", q) else 50
            start = (page - 1) * size
            return self._send(200, {"rows": rows[start:start + size], "total": len(rows), "page": page, "pageSize": size})
        if route == "/emails":
            page = int(re.search(r"[?&]page=(\d+)", q).group(1)) if re.search(r"[?&]page=(\d+)", q) else 1
            size = int(re.search(r"[?&]size=(\d+)", q).group(1)) if re.search(r"[?&]size=(\d+)", q) else 50
            start = (page - 1) * size
            return self._send(200, {"rows": EMAILS[start:start + size], "total": len(EMAILS), "page": page, "pageSize": size})
        if route == "/jobs/0":
            return self._send(200, JOBS)
        if route == "/settings":
            if method == "POST":
                return self._send(200, {"ok": True})
            return self._send(200, SETTINGS)
        if route == "/staged-contacts" and method == "GET":
            page = int(re.search(r"[?&]page=(\d+)", q).group(1)) if re.search(r"[?&]page=(\d+)", q) else 1
            size = int(re.search(r"[?&]size=(\d+)", q).group(1)) if re.search(r"[?&]size=(\d+)", q) else 20
            start = (page - 1) * size
            return self._send(200, {"rows": STAGED[start:start + size], "total": len(STAGED), "page": page, "pageSize": size})
        m = re.match(r"^/staged-contacts/(\d+)/(approve|reject|dismiss)$", route)
        if m and method == "POST":
            return self._send(200, {"ok": True, "id": int(m.group(1))})
        m = re.match(r"^/staged-contacts/(\d+)$", route)
        if m and method == "PATCH":
            return self._send(200, {"ok": True, "id": int(m.group(1))})
        m = re.match(r"^/contacts/crm/(\d+)$", route)
        if m:
            return self._send(200, {"ok": True, "id": int(m.group(1))})
        if route == "/dedup-rules":
            return self._send(200, DEDUP)
        if route == "/intake" and method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            results = [{"file": p, "status": STATUSES[i % len(STATUSES)],
                        "contacts_found": (i + 1) * 7 if STATUSES[i % len(STATUSES)] == "OK" else 0,
                        **({"error": "No contact rows found"} if STATUSES[i % len(STATUSES)] != "OK" else {})}
                       for i, p in enumerate(data.get("paths", []))]
            return self._send(200, {"results": results,
                                    "counts": {"new": 12, "merged": 4, "skipped": 2, "error": 1}})
        return self._send(404, {"error": f"no route {route}"})

    def do_GET(self):
        if self.path.startswith("/api"):
            return self._api("GET")
        name = self.path.split("?")[0]
        if name in ("/", "/index.html"):
            return self._serve(STATIC / "index.html", "text/html")
        rel = name.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[len("static/"):]
        safe = (STATIC / rel).resolve()
        try:
            safe.resolve().relative_to(STATIC.resolve())
        except ValueError:
            return self._send(403, {"error": "forbidden"})
        if not safe.exists():
            return self._send(404, {"error": "not found"})
        ctype = {"css": "text/css", "js": "text/javascript", "html": "text/html",
                 "woff2": "font/woff2", "svg": "image/svg+xml"}.get(safe.suffix[1:], "application/octet-stream")
        return self._serve(safe, ctype)

    def do_POST(self):
        if self.path.startswith("/api"):
            return self._api("POST")
        self._send(404, {"error": "not found"})

    def do_PATCH(self):
        if self.path.startswith("/api"):
            return self._api("PATCH")
        self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if self.path.startswith("/api"):
            return self._api("DELETE")
        self._send(404, {"error": "not found"})

    def _serve(self, file, ctype):
        try:
            data = file.read_bytes()
            self._send(200, data, ctype)
        except OSError:
            self._send(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"Serving {STATIC} on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
