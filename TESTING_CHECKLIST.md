# Manual test checklist — CRM Local redesign

Run the app the way users do (FastAPI serving `/` and `/static/*`), or stand-in with
`python tools/mock_api.py` → http://localhost:8787. Tick every box in **both themes**
unless noted. Keyboard section must be done with mouse/trackpad disconnected or ignored.

## 1. Every view, light + dark
- [ ] Overview: 5 KPI cards render, tabular numerals align; "Needs attention" items appear only for counts the API returns; each item navigates (staged → Staged review, others → Data Quality); Recent activity lists jobs with relative times
- [ ] Overview dark: surface steps visible (base → card), text never pure white, accent readable
- [ ] Extract: dropzone idle state; Browse files opens dialog; dragging a file over shows strong highlight; unsupported extension shows a per-row error + toast; supported file shows Queued → Processing → Done with size in mono; Start extraction disabled with empty queue; progress bar + `N/N` counter; summary lines + "Review staged contacts →"
- [ ] Staged review: badges render with icon + text (never color alone); confidence right-aligned mono; J/K move the accent indicator, A approves (row updates without page reload, toast confirms), R rejects, D dismisses, Enter opens drawer; shortcut hints visible; bulk "Approve selected" after ticking rows
- [ ] Contacts: search hits the API (debounced typing), filter select narrows the loaded page, column headers toggle sort arrows + `aria-sort`, row hover reveals actions, ellipsis cells show `title` tooltips, pagination footer "Showing X–Y of Z", page-size select reloads, Export downloads CSV
- [ ] Contacts: tick 2 rows → bulk bar slides in with "2 selected", Export selected + Delete (confirm dialog) work; select-all shows indeterminate state
- [ ] Emails: search filters the page, Date/Contacts sort client-side, Contacts column right-aligned
- [ ] Customer Profiles: initials avatars, completeness meters, "View profile" opens drawer
- [ ] Analytics: four charts render with takeaway titles; "View as table" swaps chart ↔ table; hovering/focusing a bar row announces its value; if backend has no country field, geo card shows the honest empty state
- [ ] Data Quality: counts match `/api/status`; severity pills icon+label; "Review" buttons navigate; Detection rules list renders `/api/dedup-rules` rows or a friendly fallback
- [ ] History: status badges OK/error, mono file names with tooltip, contacts right-aligned, filter + sort work
- [ ] Settings: provider chain ordered with up/down/remove/enable switch/status dot; folder paths mono + editable; theme segmented control (Light/Dark/System); watch interval + switch; "Unsaved changes" pill appears after any edit; Save shows toast or the plain-language error banner if the backend has no save endpoint

## 2. States
- [ ] Loading: every table shows skeleton rows matching final layout (no layout shift); Refresh button spins
- [ ] Empty: stop the backend (or empty DB) → contacts/emails/history/staged/profiles/charts/activity each show icon + instruction + CTA, never a blank panel
- [ ] Error: kill the backend mid-session → inline banner with plain-language fix ("Could not reach the local API… press Refresh"), no unhandled red screens
- [ ] Disabled: Extract button disabled until a valid file is queued; pagination arrows disabled at bounds; provider move buttons disabled at ends

## 3. Keyboard-only run-through
- [ ] Tab from address bar: Skip link appears first and works
- [ ] Sidebar: all nav items reachable, active state visible, Enter navigates
- [ ] Topbar: Ctrl+K trigger, theme cycle, Refresh reachable; focus ring visible on each
- [ ] Ctrl+K → palette opens ≤150ms; type "cont"; ↑/↓ move with `aria-activedescendant`; Enter runs; Esc closes; grouped results visible
- [ ] Contacts: Tab reaches search, filter, density, columns menu (Space toggles), Export, row checkboxes, sortable headers, row actions (focus-within reveals them), pagination
- [ ] Staged: J/K/A/R/D/Enter as above, without the mouse
- [ ] Drawer: Esc closes; Tab cycles inside the panel only; focus returns to the opener
- [ ] Confirm dialog: Esc cancels, focus returns, Tab is trapped
- [ ] Toasts: reachable/announced (role=status); Undo action runs for queue removal
- [ ] Dropzone: Tab reaches it, Enter opens the file dialog

## 4. Ctrl+K specifics
- [ ] Opens/closes with Ctrl+K (Cmd+K on Mac), never scrolls the page
- [ ] Views / Actions / Contacts groups ordered; shortcut column present
- [ ] "Refresh data", "Theme: Dark", "Export contacts (CSV)", "Toggle sidebar" all execute
- [ ] Contact results appear after 2+ characters and open the drawer
- [ ] Palette still works after visiting every view (no stale handlers); app unaffected if palette init throws (check console)

## 5. Viewport sizes
- [ ] 1920×1080: content max-width 1440 centered, KPI row = 5
- [ ] 1280×720: KPI row = 5, tables fit, no horizontal scroll (except inside table container)
- [ ] ~1000px: sidebar auto-collapses to icon rail with tooltips; KPI row = 3
- [ ] 900px: sidebar off-canvas; hamburger opens it; navigating auto-closes; hamburger floats above the open sidebar and closes it; KPI row = 3→2; page-head stacks
- [ ] No layout shift while loading at any size (skeletons match final heights)

## 6. Reduced motion (OS setting on, or DevTools emulation)
- [ ] No view fade/rise, no drawer slide (instant), no count-up, no bar growth
- [ ] Skeleton shimmer static; progress bars still fill; focus rings unchanged
- [ ] Toasts appear/disappear without motion

## 7. Offline
- [ ] DevTools → Network: zero requests to non-localhost origins, zero failed font/icon loads
- [ ] Disconnect network entirely (or serve with no internet): everything still renders, fonts load from `static/fonts/`
- [ ] Console: no errors on boot, on navigation, on empty/error states (verified 0/0/0 by `tools/test_ui.py`)

## 8. Theme persistence
- [ ] Choose Dark → reload → still Dark (no flash of light)
- [ ] Choose System → switch OS theme → UI follows live
- [ ] Sidebar collapsed state, density compact, staged badge count survive reload
