# Acceptance Scenarios (verbatim from master brief §16)

Authoritative end-to-end acceptance tests. Source: master brief, 2026-11-07 session (this text exists nowhere else in either repo — see DECISIONS.md D-024).

The product is not complete merely because each individual page exists. Test real end-to-end scenarios.

## Scenario A — Spreadsheet

1. Import a spreadsheet with multiple sheets.
2. Detect fields.
3. Map columns.
4. Extract company information.
5. Extract contacts.
6. Preserve unmapped values.
7. Stage contacts.
8. Detect duplicates.
9. Approve selected records.
10. Verify final CRM data.

## Scenario B — PDF

1. Import multiple PDFs.
2. Extract text and tables.
3. Identify company information.
4. Identify multiple people.
5. Preserve page references.
6. Validate results.
7. Stage contacts.
8. Approve or correct candidates.

## Scenario C — EML

1. Import multiple email messages.
2. Preserve original email content.
3. Extract deterministic headers.
4. Extract sender signatures.
5. Identify genuine contact candidates.
6. Preserve To/CC/BCC.
7. Stage contacts.
8. Resolve duplicate candidates.
9. Approve and enrich.
10. Verify email relationships.

## Scenario D — Enrichment

1. Import a contact already in CRM.
2. Provide additional phone or company information.
3. Detect the existing contact.
4. Fill missing fields.
5. Preserve existing populated values.
6. Record provenance.
7. Verify the source relationship.

## Scenario E — Duplicate review

1. Create exact duplicate candidates.
2. Create probable duplicates.
3. Identify conflicts.
4. Compare field values.
5. Merge selected fields.
6. Preserve email and activity relationships.
7. Verify recovery behaviour.

## Scenario F — Offline usage

1. Disable internet.
2. Launch CRM_Local.
3. Import supported local files.
4. Perform local extraction.
5. Manage contacts.
6. Review staged records.
7. Export results.

The application must remain useful without external services.

## Scenario G — Restart and recovery

1. Process a batch.
2. Close the application.
3. Restart.
4. Verify database integrity.
5. Verify contact records.
6. Verify staged records.
7. Verify email relationships.
8. Verify settings and history.
