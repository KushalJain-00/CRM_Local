# CRM Local redesign — release notes

## Files delivered (exact paths)

```
crm-local-redesign/
├── static/
│   ├── index.html                  ← full replacement
│   ├── style.css                   ← full replacement
│   ├── app.js                      ← full replacement
│   └── fonts/
│       ├── InterVariable.woff2     ← already included (downloaded, verified WOFF2)
│       ├── IBMPlexMono-Regular.woff2
│       ├── IBMPlexMono-Medium.woff2
│       └── IBMPlexMono-SemiBold.woff2
├── DESIGN_SYSTEM.md                ← updated design system
├── TESTING_CHECKLIST.md            ← manual test checklist
├── NOTES.md                        ← this file
└── tools/                          ← dev-only, NOT shipped to users
    ├── mock_api.py                 ← mock FastAPI responses to run the UI standalone
    ├── test_ui.py                  ← Playwright verification (26 screenshots)
    └── contrast_check.py           ← WCAG contrast verification of the token set
```

### Fonts — what you must do
Nothing. All four woff2 files are already in `static/fonts/` and were verified as real
WOFF2 binaries. If you ever need to refresh them:
- Inter variable: `https://rsms.me/inter/font-files/InterVariable.woff2` → `static/fonts/InterVariable.woff2`
- IBM Plex Mono 400/500/600: npm package `@ibm/plex-mono` (`fonts/complete/woff2/IBMPlexMono-*.woff2`) → `static/fonts/`
No CDN references exist in the code; the app is 100 % offline.

## What changed (15 bullets)

1. **Token system rebuilt**: 3-tier CSS custom properties (primitive → semantic → component) in `@layer reset/tokens/base/components/utilities`, all colors in `oklch()`, hover/pressed/tint states derived with `color-mix(in oklch, …)` — no hardcoded hex for states.
2. **Theming**: `color-scheme` + `light-dark()` with `[data-theme]` overrides and a Light / Dark / **System** segmented control; default follows `prefers-color-scheme`; pre-paint boot script kills theme flash; dark theme designed from scratch (`#121316` base, `#1a1b1f` cards, `#23242a` popovers, `#8ab4f8` accent, luminance-boosted status colors) — not an inversion.
3. **Shell**: grouped sidebar with icons and badge count for staged review (shown only when the API provides a count), icon-rail collapse with tooltips + accent bar on the active item, topbar with page title, Ctrl+K search trigger, theme cycle and Refresh spinner.
4. **New Staged review screen** (keyboard-first triage: J/K/↑/↓, A approve, R reject, D dismiss, Enter opens the drawer, visible shortcut hints) — the old JS referenced `stagedContactsBody`/`stagedPagination` but no such view existed.
5. **Ctrl+K command palette** (~180 lines): grouped commands (views / actions / contact search with debounced API query), fuzzy matching, full listbox ARIA, shortcut hints; wrapped in try/catch so it can never break the app.
6. **Right-side drawer** for contact and staged detail: fields, completeness bar, provenance (source file / sheet / row / timestamps when the API provides them), and in-place editing (replaces `prompt()`).
7. **Toasts + native `<dialog>` confirm** replace every `alert()`/`confirm()`: stacked toasts with pause-on-hover and Undo for client-side destructive actions (file queue remove/clear); delete still confirms, approve/reject/dismiss no longer block.
8. **Overview redesigned**: 5 KPI cards (Duplicates moved into a clickable "Needs attention" strip alongside staged / invalid emails / missing fields), compact activity timeline from real `/api/jobs/0` rows, count-up on first load, delta/sparkline support that only renders when the API returns them.
9. **Extract**: real dropzone states (idle/drag-over/disabled) with click + keyboard access, per-file status badges and error lines, retry per file, Undo on queue removal, visible accepted-types text, summary with a link to staged review.
10. **Tables upgraded**: sticky headers, `aria-sort` sortable headers, row selection with `:has()`-driven bulk bar (export/delete selected), column visibility menu (popover attribute + fallback), density toggle (comfortable/compact, persisted), "Showing X–Y of Z" footer with page-size select, row actions revealed on hover/focus-within.
11. **Analytics charts hand-built in SVG/CSS** (zero dependencies): takeaway titles, direct labels, Okabe–Ito palette, focusable data rows, "View as table" toggle + visually-hidden tables, one-shot bar growth, re-render on theme change and container resize — and honest empty states where the API has no data (e.g. geography).
12. **Data Quality / History / Profiles / Settings** redesigned: severity pills (icon + label), detection-rules list, status badges, profile cards with initials avatars and completeness meters, settings sub-nav with ordered provider chain (up/down/enable/status dot), unsaved-changes pill, editable folder paths in mono.
13. **Self-hosted fonts + inline icon sprite**: Inter variable + IBM Plex Mono woff2 in `static/fonts/`, ~50 inline Lucide-style symbols; zero external requests (verified: 0 across the whole test run).
14. **Motion system**: duration/easing tokens, View Transitions on view switch (instant fallback), `@starting-style` for dialogs/toasts, one-shot chart growth, KPI count-up, full `prefers-reduced-motion` handling.
15. **A11y verified**: programmatic contrast check passes AA in both themes (worst pair 5.49:1), focus-visible everywhere, 44px effective targets on primary actions, keyboard-only triage, `role="status"` toasts, skip link, `aria-sort`/`aria-expanded`/`aria-activedescendant` wired.

## Issues noticed (found in the uploaded build — not silently changed)

1. **The uploaded `app.js` cannot execute at all.** The shipped file contains `esc()` with HTML-entity replacements whose entities were lost (e.g. `.replace(/&/g, '&')`), producing a `SyntaxError` at parse time, plus invalid escaped-backtick template literals in `loadDataQuality()`. Every screen was dead on arrival. The replacement obviously had to fix parsing; the escape helper now emits real entities (`&amp;` etc. — the old intent was also a no-op replacement, an XSS/rendering hazard with `innerHTML`).
2. **`API_BASE = '/api'` + paths starting with `/api/…` yields `/api/api/…`.** Kept exactly as shipped per your instruction (all calls still read `api('/api/status')` against the unchanged `API_BASE` line). If the backend serves routes at `/api/…`, either inject `window.CRM_API_BASE = ''` from FastAPI or mount routes accordingly. The mock server aliases both shapes so you can test either way.
3. **Undefined inline handlers in the old build**: `refreshData()`, `filterContacts()`, `exportContacts()`, `searchEmails()`, `addProvider()`, `pickFolder()`, `saveSettings()`, `viewContactProfile()` were referenced by the HTML but never defined (clicking them threw). All are now implemented — `filterContacts`/`searchEmails` filter the loaded page client-side because the backend exposes no filter parameter; `pickFolder` explains that a native picker needs a backend endpoint and focuses the (now editable) path input; `saveSettings` POSTs to `/api/settings` and shows a plain-language inline error if the backend rejects it (no save endpoint existed — GET-only in the old build).
4. **Email pagination reloaded contacts.** The shared `renderPagination` generated `onclick="S.page=N; loadContacts()"` even inside `emailsPagination`. Now pagination callbacks are per-view; the function name/signature is unchanged.
5. **`sortContacts()` never sent sort/dir.** Old `loadContacts()` built its URL without them, so header clicks re-fetched unsorted data. The new URL includes `&sort=&dir=` — harmless if the backend ignores the params.
6. **Data Completeness always showed 100 %** (`withEmail = total` in the old code). It now derives from `counts.incomplete_records` when present, with a caption; no fabricated data.
7. **`stagedContactsCache` was never populated** (declared at the bottom, never filled), so `editStagedContact()` silently did nothing. Now filled by `loadStagedContacts()`.
8. **Undo on approve/dismiss is not offered**: the backend exposes only approve/reject/dismiss POSTs — there is no revert endpoint — so a true Undo is impossible without fabricating one. Toasts inform; optimistic row state reverts on API error. If you add e.g. `POST /api/staged-contacts/{id}/restore`, wire it into `stagedDecide()`'s toast actions.
9. **Settings persistence is GET-only upstream.** `saveSettings()` attempts `POST /api/settings` (payload `{chain, crm_dir, eml_dir, watch_interval, watch_enabled}`); on 404/405 the UI shows a plain-language banner and keeps a localStorage copy (`crm-settings-local`) so nothing is lost in-session.
10. **Analytics has no dedicated endpoint.** Charts compute from real data the app already fetches (`/api/contacts` fill-rates, `/api/jobs/0` file types, email/phone presence); geographic distribution renders an explicit "no location field" empty state until the backend provides one. Delta/sparkline hooks read `status.trends` and stay hidden unless present.
11. **Minor old bugs fixed in passing**: duplicate `esc()` definition; `renderFileQueue()` printed the literal string `$(f.size / 1024).toFixed(1)KB` (`$( )` instead of `${ }`); `S.emaills` typo (kept for compatibility, `S.emails` is the real one); `style="align-items: margin-top: 4px"` invalid inline CSS in old `renderSettings`; CSS `transition-duration: 0.01ms !;` invalid syntax; double load of `loadOverview()` on boot (bottom-of-file IIFE + DOMContentLoaded).
12. **Sidebar collapse semantics unified** (old code mixed `.sidebar.collapsed` and `body.sb-collapsed` with inconsistent restore). Both class hooks are still set for compatibility, driven by one code path; on ≤900px the sidebar becomes off-canvas and navigation auto-closes it.

## Order of work (how this was built — and how to re-do/extend it)

1. Tokens/base (`style.css` layers + fonts) → 2. Shell (sidebar/topbar/views) → 3. Shared components (buttons, inputs, tables, badges, banners, empty states, skeletons, toasts, dialog, drawer) → 4. Screens (Overview → Extract → Staged → Contacts → Emails → Profiles → History → Quality → Settings) → 5. Charts → 6. Motion → 7. Palette → 8. Theme/a11y verification (`tools/contrast_check.py`, `tools/test_ui.py`).
