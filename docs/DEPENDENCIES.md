# Dependencies — CRM_Local (release 1.0.0, 2026-11-13)

Inventory of what the app actually imports vs what is declared, packaged and tested. Replaces the 2026-11-07 audit.

| Dependency | Kind | Version | Used by |
|---|---|---|---|
| fastapi | runtime | 0.111.0 | app.py, api/*, TestClient in tests |
| uvicorn | runtime | 0.29.0 | app.py main() (lazy `uvicorn.run`) |
| httpx | runtime | 0.27.0 | llm.py provider calls; TestClient backend |
| openpyxl | runtime | 3.1.2 | parse.py, export.py |
| xlrd | runtime | 2.0.1 | services/parser.py (legacy .xls) |
| pdfplumber | runtime | 0.11.10 | services/parser.py parse_pdf (MIT) |
| pydantic | runtime (direct import) | 2.14.3 | app.py, api/*, services/contract.py |
| python-multipart | runtime (multipart intake) | 0.0.33 | api/intake.py — FastAPI raises at route registration without it |
| pytest | test | 9.1.1 | tests/ |
| reportlab | test-only (dev) | 4.4.4 | tests/test_pdf_parser.py fixture generation |
| PyInstaller | packaging | 6.11.1 | windows-build.yml / build_windows.bat |

Transitives of pdfplumber (all permissive): pdfminer.six (MIT), pypdfium2 (BSD-3/Apache-2.0), Pillow (MIT-CMU), pypdf (BSD).

## Notes

- All six runtime imports are also statically analyzable — no hiddenimports needed beyond the uvicorn recipe in CRM_Local.spec.
- Zero CDN/remote URLs in static/. Fonts are self-hosted under static/fonts.
- Fresh-install verification: clean venv (python 3.14.7 via /home/kushal_jain/.local/bin), `pip install -r requirements.txt -r requirements-dev.txt`, then `pytest tests/ -q` → 332 passed.
- Frozen binary verified to contain pdfplumber and no PyMuPDF/fitz strings.
