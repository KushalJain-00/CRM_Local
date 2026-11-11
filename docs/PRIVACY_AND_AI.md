# Privacy and AI disclosure

## What stays on this machine

- The entire CRM database (`crm.db`) and all extracted contacts.
- Your configuration (`config.json`), including provider settings and API keys.
- File parsing, deterministic extraction, dedup, validation, history,
  exports — all run locally.

API keys are written only to `config.json` in the data directory. The file is
owner-only on POSIX (`0600`). Keys are masked in every settings screen,
status endpoint, diagnostic and log. The app never phones home.

## What leaves this machine — and only if you turn it on

If you configure an AI provider (OpenAI, OpenRouter, Groq, Google Gemini,
Anthropic, DeepSeek, Ollama, or a custom OpenAI-compatible endpoint), then
during extraction the **content of the files you import is sent to that
provider** for processing. That includes email bodies, signatures,
addresses, phone numbers and any other personal data in those files.

- With an empty provider chain, nothing is sent anywhere. Full stop.
- Ollama and "custom OpenAI-compatible" endpoints on `localhost`/your own
  network process data on infrastructure you control.
- Cloud providers process your extraction content under their own terms.
  Review their data-use policies before importing sensitive mailboxes.

The app does not hide this. There is no telemetry. The only outbound network
traffic is: (a) requests you trigger to providers you configured, and
(b) your browser fetching the app itself from `127.0.0.1`.

## How to disable AI

Settings → AI providers → disable or remove every provider (or leave the
chain empty). Extraction keeps working with local pattern matching, which
handles most structured documents (CSV/XLSX with clean headers, EML
signatures). AI is an enhancement layer, not a dependency.

## Prompts and data retention

The two master extraction prompts are stored in `config.json` under
`prompts.*`. They are visible in Settings → Prompts and can be reset to the
built-in defaults at any time.

## What the app does not do

- No analytics beacons, crash reporters or update checks.
- No accounts, no cloud sync, no background network use.
- No deletion of your source files (imports copy; sources stay where they are).
- No hard deletion of contacts (soft delete only).
