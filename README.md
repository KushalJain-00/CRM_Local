# CRM Local

A Windows desktop app that reads two folders on your machine, extracts contacts, and keeps them in two local databases. No accounts, no cloud database, no hosting. The only network traffic is the LLM provider you configure.

## What it does

- **CRM folder** — `.xlsx`, `.xls`, `.csv`, `.pdf` files are parsed, columns are mapped to contact fields automatically, and rows land in `crm.db`.
- **EML folder** — `.eml` files are read oldest-first by their `Date` header, contacts are extracted, stored in `eml.db`, and pushed into `crm.db`.
- Every processed file is recorded in a ledger, so a rescan never processes the same file twice.
- Contacts are shown as a sheet inside the app and can be downloaded as a styled Excel file at any time.

## Install

1. Run `CRM_Local-Setup.exe` (or `CRM_Local.exe` for a portable copy).
2. The app opens in your browser at `http://127.0.0.1:<port>`.
3. On the **Run** page, choose your CRM folder and your EML folder.
4. Press **Scan now**.

Windows SmartScreen may warn about an unsigned installer. Choose **More info → Run anyway**.

## Settings

### Providers

Extraction runs in two layers:

1. Local pattern matching (always on, no setup).
2. Your provider chain, tried top to bottom. If one fails, the next takes over.

Add providers in **Settings → Add provider**. Cloud APIs are the default:

| Provider | Model example |
|---|---|
| OpenRouter | `anthropic/claude-3.5-sonnet` |
| Groq | `llama-3.3-70b-versatile` |
| Gemini | `gemini-2.0-flash` |
| OpenAI | `gpt-4o-mini` |
| DeepSeek | `deepseek-chat` |
| Anthropic | `claude-3-5-sonnet-latest` |
| Ollama | any local model, host default `http://localhost:11434` |

Use the arrows to reorder. Leave the chain empty to use local matching only.

### Watch mode

While the app is open, it scans both folders on an interval (default 30 s). **Start CRM Local when Windows starts** adds a shortcut to your Startup folder — available in the installed app.

## Where your data lives

```
%APPDATA%\CRM_Local\
  config.json
  crm.db
  eml.db
```

Back up that folder by copying it. Deleting it resets the app.

## Build from source

Requires Python 3.12+ on Windows.

```bat
build_windows.bat
```

Produces `dist\CRM_Local.exe` and, if Inno Setup 6 is installed, `dist\CRM_Local-Setup.exe`.

On Linux/macOS for development:

```bash
python -m venv venv
venv/bin/pip install -r requirements-dev.txt
venv/bin/python app.py
venv/bin/python -m pytest -q
```

The Windows `.exe` cannot be cross-compiled from Linux; use the GitHub Actions workflow (`.github/workflows/windows-build.yml`) or a Windows machine.
