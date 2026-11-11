# Backup and recovery

CRM Local keeps everything in one SQLite database (`crm.db`) plus one
configuration file (`config.json`). Both live in the data directory:

| Platform | Location |
|---|---|
| Windows | `%APPDATA%\CRM_Local\` |
| Linux/macOS | `~/.crm_local/` |

## Cold backup (recommended, always safe)

1. Close CRM Local completely.
2. Copy `crm.db` to a safe location (USB stick, another drive).
3. Optionally copy `config.json` (it contains your API keys — protect it).

The file is self-contained once the app is closed; the copy is a full backup.

## Live backup (app running)

SQLite's online backup API produces a consistent copy even while the app
uses the database. From a Python session in the app directory:

```python
import db  # app directory on sys.path, or use the bundled module
db.backup_database(r"C:\backups\crm-2026-11-11.db")  # verified by integrity_check
```

`backup_database()` verifies the copy with `PRAGMA integrity_check` and
raises if the copy is unreadable.

## Restore

1. Stop CRM Local.
2. Copy your backup over `crm.db` in the data directory (overwriting is
   intentional — the backup becomes the live database), or:

   ```python
   db.restore_database(r"C:\backups\crm-2026-11-11.db")  # atomic replace
   ```

3. Start CRM Local. Verify a few contacts.

`restore_database()` checks the backup's integrity first and refuses to
install a corrupt file. WAL sidecar files (`crm.db-wal`, `crm.db-shm`) from
an older state are removed by the restore procedure.

## Migrating from an older CRM Local

- **v1 → current:** on first launch the app detects the old schema and
  applies the additive migration train automatically on a *fresh* database.
  On a database that already contains data, migrations are gated: they only
  run with `CRM_APPLY_MIGRATIONS=1` in the environment (or by an explicit
  support step), after a backup. Nothing is merged or dropped silently;
  every migration is transactional and logged in `_migration_log`.
- **Live upgrade procedure (Windows):**
  1. Close CRM Local.
  2. Back up `%APPDATA%\CRM_Local\crm.db` (cold backup above).
  3. Install the new version over the old one.
  4. Set `CRM_APPLY_MIGRATIONS=1` and launch once; check the log output and
     the History/Data Quality screens; then remove the variable.
- **Rollback:** close the app, restore the backup file, reinstall the old
  version if needed.

## Data safety notes

- The app never hard-deletes contacts; deletes are soft (`deleted_at`).
- The app never deletes your WAL files at startup (they may hold the last
  commits after a crash; SQLite replays them automatically).
- Staging review means nothing enters the canonical CRM without your approval;
  `staged_contacts` preserves the raw extracted data for every decision.
