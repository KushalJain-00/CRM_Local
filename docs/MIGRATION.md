# Migration notes — CRM Local 1.0.0

Read this if you have used a preview build of CRM Local before.

## What changed in the data write path

Extraction results no longer write straight into the CRM. They are staged in
a review queue (`staged_contacts`); you approve, reject or dismiss each one
from **Staged review**. Approvals are replay-safe and enrich existing
contacts with local-wins rules (your existing values are never overwritten).

## What changed for AI extraction

Two independent master prompts (Contact documents, Email/EML) are editable in
**Settings → Prompts**. Large documents are processed in bounded chunks with
row-level provenance; conflicting AI output across chunks is kept as warnings
for review, never silently merged.

## Database migration (v1 → v10)

See **docs/BACKUP_AND_RECOVERY.md**. The migration train is additive and
logged; on a fresh install it runs automatically. On an existing database
with data it runs only with explicit approval (`CRM_APPLY_MIGRATIONS=1`),
after a backup.

## Rollback

Your pre-migration backup is the rollback path: stop the app, copy it back
over `crm.db`, done.
