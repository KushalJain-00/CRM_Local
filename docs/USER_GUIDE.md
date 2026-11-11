# CRM Local — User Guide

The normal workflow, start to finish.

## 1. Install

Run `CRM_Local-Setup.exe`. If you downloaded the portable `CRM_Local.exe`,
put it anywhere and double-click it. No administrator rights are required
for the per-user install. Accept the desktop shortcut if you want one.

## 2. Launch

The app starts a small local server and opens your default browser at
`http://127.0.0.1:<port>`. Everything it does stays on this machine.

Your local database and configuration live in:

- **Windows:** `%APPDATA%\CRM_Local\`
- **Linux/macOS:** `~/.crm_local/`

Files there: `crm.db` (your data), `config.json` (your settings — contains API
keys; keep it private), `uploads/` (temporary spool, cleaned automatically).

## 3. Optional: configure AI providers

Everything works without AI. Local pattern matching runs always; an AI
provider only fills gaps.

In **Settings → AI providers**:

1. Pick a provider (OpenAI, OpenRouter, Groq, Gemini, Anthropic, DeepSeek,
   Ollama for local models, or a custom OpenAI-compatible endpoint).
2. Paste your API key. Keys are stored on this machine only and are masked
   in every screen and diagnostic.
3. Use **Test** to check it, **Discover models** to list models, or type a
   model name manually.
4. Reorder providers with the arrows — requests try them top to bottom.
   Disabled providers are never called.

Leave the chain empty to run fully offline with local extraction only.

Extraction prompts: **Settings → Prompts** lets you view/edit the two master
prompts (Contact documents and Email/EML). Saving validates the required
output contract; **Reset** restores the built-in default. Edits survive
restarts.

## 4. Import documents and emails

Go to **Extract** and drop files (or use the file picker):

| Format | Notes |
|---|---|
| CSV | Delimiter and encoding auto-detected |
| XLSX / XLS | All sheets, merged cells, multi-row headers |
| PDF | Text and tables; scanned images without OCR text are not supported |
| TXT | Structured lists and contact-shaped blocks |
| EML | Whole email: sender, recipients, signature, body |

Large spreadsheets are processed in bounded chunks; spreadsheet rows keep
their `row N` provenance.

Each file appears in **History** with its status and the number of contacts
found.

## 5. Review extracted contacts

Everything the extractors find lands in **Staged review** — nothing enters
your CRM without your decision. Each row shows:

- **Review:** Ready, Needs review, Approved, Rejected, Dismissed
- **Dedup:** Unique, Exact duplicate, Probable duplicate, Conflict
- **Import:** New contact created / existing contact enriched / not imported

Actions per row: open, approve, reject, dismiss. Bulk actions via checkbox +
keyboard: `J`/`K` move, `A` approve, `R` reject, `D` dismiss, `Enter` open.

**Approve a new contact** — creates the CRM record.
**Approve a duplicate of an existing contact** — enriches the existing
record (local values win; only empty fields are filled). Approving the same
row twice is safe — it is never duplicated.

## 6. Search and manage contacts

**Contacts** lists, searches, sorts and filters your CRM. Open a contact to
edit any field inline; soft-delete hides it (it is recoverable by restoring
from the database backup; the app never hard-deletes). Companies are matched
by normalized website/domain keys where possible.

**Customer Profiles** shows people grouped by company.

## 7. Emails, History, Data Quality, Analytics

- **Emails** — every imported EML with subject, date, sender, and how many
  contacts came from it.
- **History** — per-file ledger: status, contacts found, when. Re-importing
  the same file is safe; duplicates surface in review.
- **Data Quality** — counts of invalid emails/phones, duplicates, and
  incomplete records, plus the rule catalogue the server enforces.
- **Analytics** — summaries and tables only (no charts, by design).

## 8. Back up and restore

See **docs/BACKUP_AND_RECOVERY.md**. Short version: stop the app, copy
`%APPDATA%\CRM_Local\crm.db` somewhere safe (optionally `config.json` too),
or use the backup instructions in that document for a live-copy backup.
Restore by replacing the file while the app is closed, or with
`db.restore_database(backup, dest)` in a Python session.

## 9. Uninstall

Windows: Settings → Apps → CRM Local → Uninstall. Your data in
`%APPDATA%\CRM_Local\` is **not** deleted by the uninstaller — remove that
folder manually if you want a full wipe.
