# CRM Local — User Guide

## Getting Started

1. Install CRM Local using the Windows installer (`CRM_Local-Setup.exe`) or run the portable executable (`CRM_Local.exe`).
2. The application opens in your browser at `http://127.0.0.1:<port>`.
3. On first launch, you'll see the Overview page with empty statistics.

## Navigation

The application has 9 views accessible from the sidebar:

1. **Overview** — Dashboard with KPIs, recent activity, and data completeness
2. **Extract** — Universal file intake (drag & drop or browse)
3. **Contacts** — Contact management (search, filter, sort, paginate, edit, delete)
4. **Emails** — Email browser with search and filtering
5. **Customer Profiles** — Company and person details with source information
6. **Analytics** — Geographic, segmentation, reachability, completeness charts
7. **Data Quality** — Invalid emails/phones, missing fields, duplicates
8. **History** — Processing runs, files, successes/failures, error details
9. **Settings** — Provider configuration, folders, theme, backup/restore

## Universal Extract

1. Go to the **Extract** view
2. Drag & drop files or click "Browse Files"
3. Supported formats: XLSX, XLS, CSV, PDF, TXT, EML
4. Click "Extract" to process
5. View per-file results (contacts found, errors)
6. Files are automatically deduplicated on rescan

## Contacts

- **Search:** Type in the search box to filter by name, email, phone, or company
- **Edit:** Click "Edit" on a contact row to modify fields
- **Delete:** Click "Delete" to remove a contact
- **Export:** Click "Export" to download as Excel

## Settings

### AI Providers
- Add providers in order of preference
- Test each provider with the "Test" button
- Leave empty for local-only extraction
- Supports: OpenRouter, Groq, Gemini, OpenAI, DeepSeek, Anthropic, Ollama

### Folders
- CRM Directory: folder containing spreadsheet/PDF files
- EML Directory: folder containing .eml files
- Enable "Watch" for automatic scanning

### Appearance
- Theme: Light or Dark

### Processing
- Watch interval: minimum 10 seconds
- Enable/disable folder watching

## Data Location

```
%APPDATA%\CRM_Local\
  config.json
  crm.db (unified database)
```

Backup: copy the entire folder. Delete to reset.

## Troubleshooting

- **App won't start:** Check if port 8000-8010 is available
- **No contacts extracted:** Verify file format is supported; check file size (< 10MB)
- **LLM not working:** Verify API key and model name; test with "Test" button
- **Database locked:** Close other instances of the app

## Build from Source

Requires Python 3.12+.

```bash
python -m venv venv
venv/bin/pip install -r requirements-dev.txt
venv/bin/python app.py
venv/bin/python -m pytest -q
```