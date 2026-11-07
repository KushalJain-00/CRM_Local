# CRM_Local — Phase-0 Design Research

Status: research input for Phases 1–6. Read-only analysis; no code or design decisions are made here beyond a *proposed* direction for later approval.

## 1. Method and evidence honesty

- **Web search was unavailable** during this session (HTTP 402, no quota). All findings come from **direct URL fetches** of vendor documentation and design galleries. Nothing below is inferred from memory and presented as "researched".
- Evidence tiers used in the table:
  - **(docs)** — read directly from the vendor's own help/docs pages this session: `attio.com/help`, `linear.app/docs`, `help.close.com`, `help.folk.app`.
  - **(gallery)** — screenshot-caption inventory from `saasui.design/crm-dashboard-ui-design` (115 screenshots, 6 products) and the short pattern write-up at `fudge.design/share/crm-ui-design-examples`. Captions prove a screen type exists; they do **not** prove interaction details. Rows marked (gallery) are deliberately conservative.
- Unreachable sources (attempted, failed): `attio.com/help/articles/using-tables` (404), `linear.app/docs/keyboard-shortcuts` (404), `www.folk.app/help` (404), `help.clay.com` (transport error), `saasui.design/.../clay` (404).
- **No proprietary assets were copied.** No branding, source code, illustrations, or screenshots are reproduced. Observations are described in words only.
- **Charts/analytics are out of scope.** The brief bans all charts; `DECISIONS.md` D-012 deletes the Analytics `chart-*` view. Close's "Analytics view" and Attio's dashboard screens exist in the galleries but are intentionally *not* mined for patterns.

## 2. Findings

Columns are fixed: `Reference product | Observed pattern | Why it works | Proposed CRM_Local adaptation | Trade-offs`.

| Reference product | Observed pattern | Why it works | Proposed CRM_Local adaptation | Trade-offs |
|---|---|---|---|---|
| Attio (docs) | Hovering a record name in a table reveals two small icon buttons: comment and "Open preview" — a record opens in a preview pane without leaving the table. | Preserves list context; peeking is cheaper than navigating, so scanning stays fast. | Row hover reveals an "Open preview" icon button that opens the contact/company **detail drawer**; Esc or the table returns focus to the same row. | Hover-only affordances are invisible on touch; must be mirrored by Enter-key behavior and a always-visible row overflow menu. |
| Attio (docs) | View settings: `+ Add column`, drag-reorder, hide, resize, per-column formatting, and a *view-scoped* column label edit that does not rename the underlying attribute. | Separates presentation from schema — users customize a view without corrupting data. | Contacts table gets a "Columns" popover: show/hide/reorder, with labels stored per saved view, not per field. | More state to persist and explain; label divergence between views can confuse ("why is `company` called `Account` here?"). |
| Attio (docs) | Full cell keyboard navigation: arrow keys move, Enter commits, ↑/↓ walk dropdown options, ⌘/Ctrl+C/V copies/pastes cells, shift-click selects a range. | Data entry without the mouse is dramatically faster for power users and is the only usable path for screen-reader/table-grid users. | Standard grid keyboard model for the contacts table (roving tabindex, Enter to edit, Esc to cancel, arrows to move). | Significant implementation cost in vanilla JS; paste semantics (dates, selects) need careful validation. |
| Attio (docs) | Right-click on a cell opens a context action — "View edit history". | Surfaces auditability exactly where the user is looking, instead of burying it in settings. | Right-click (contextmenu) on a row opens a row action menu; every item in it is also reachable from a visible `⋯` overflow button for keyboard/AT users. | Two entry points to maintain; context menus must not shadow critical UI on small screens. |
| Attio (docs) | Filter (`+ Add condition`, condition groups) and Sort (asc/desc) live in the view toolbar directly above the table. | Controls sit next to the data they affect — cause and effect are visible in one glance. | Persistent toolbar above every list view: search field, filter popover, sort menu, columns menu; active filters shown as dismissible chips. | Toolbar eats vertical space in a dense layout; needs a compact single-row design. |
| Attio (docs) | CSV import is a 7-step wizard: define object → prep file → upload (shows detected column/row counts) → map columns (auto-map, skip with ×, 100-row data preview on hover, duplicate policy "Add again / Update existing") → review values → preview import ("Up to [X] will be created") → run with progress and per-row results. | A long, risky operation is broken into small confirmable steps; the user always knows scale ("up to X") before committing. | Rebuild the existing CSV import as a stepper: Upload → Map → Review → Confirm → Results, with a live "N contacts will be created / M updated" estimate on the Confirm step. | Longer flow than a single upload button; each step needs validation or users get stuck mid-wizard. |
| Attio (docs) | Review-values step shows Raw data vs Mapped value side by side, unique values with row counts, per-value fix/skip/revert icons, an "Invalid format" error state, and a "Create missing select options" toggle. | Errors are shown *before* commit, grouped and deduplicated — one bad date format is fixed once, not 400 times. | Import review table lists each mapped field's distinct values with counts; invalid values flagged inline with a fix/skip action. | Building a value-level review UI is the most expensive part of the wizard; a simpler version (row-level errors only) is acceptable for v1. |
| Attio (docs) | Run step: progress bar, per-row green check / red error with hover description, filter by Failed/Planned/Completed, import continues in background and is resumable from Settings → Import history. | Trust: partial failure is visible, recoverable, and doesn't block the rest of the app. | Import results screen with status counts (created/updated/failed) as **text**, an `aria-live` progress region, and a per-row error list; store the last import summary. | Background/resumable imports need persistence beyond the page; simpler alternative is a synchronous run with a hard row cap. |
| Attio (docs) | Table footer offers `+ Add calculation` — column-level aggregates (count, filled/empty) shown as a summary row. | Answers "how many?" without a dashboard or chart — totals live with the data. | Contacts table footer shows static counts ("248 contacts · 31 missing email") computed from the current filter. | Aggregations over large tables must be computed server-side eventually; no charts — text only. |
| Linear (docs) | `/` opens workspace search; `Cmd/Ctrl+F` inside a view acts as a *temporary* filter cleared with Esc; result lists show recent searches first and order by relevance (in-progress before done). | Search is one keystroke away and never destroys saved state; recents reduce repeated typing. | Global `/` or `Cmd+K` search over contacts/companies; in-table filter input clears with Esc and shows "N of M matches". | Two search surfaces (global vs in-table) must be clearly differentiated or users lose track of which one they're in. |
| Linear (docs) | Command menu supports typed prefixes (`i ` issue, `p ` project, `u ` user, `t ` team, `l ` label) with a 500-result cap and English stop-word removal. | Prefixes make a small vocabulary of commands fast *and* discoverable; caps keep the list responsive. | `Cmd/Ctrl+K` palette with groups: Navigate, Create, Recent records, plus `c ` to jump to a contact by name. | Prefix syntax has a learning cost; needs a visible hint line in the palette footer. |
| Linear (docs) | Saved views: a "Save view" icon appears once ≥1 filter is applied; views can be favorited into the sidebar; the URL carries temporary filters so a pasted link reproduces the exact list. | Filter state becomes shareable and durable — the URL is the source of truth. | Implement saved views (name + filter/sort/column set persisted) and reflect active filters in the hash route. | URL-encoded filter state gets ugly fast; need a compact encoding and a "clear all" affordance. |
| Linear (docs) | "Peek" preview opens on the Space bar and toggles off with Space — a temporary overlay, not a navigation. | Preview is cheap and reversible; keyboard users get the same affordance as mouse users. | `Space` peeks the selected contact row in the detail drawer; `Enter` opens it "for real" (full record route). | Two levels of "open" can confuse; must be documented in the shortcut help (`?`). |
| Close (docs) | `?` on any page opens a keyboard-shortcut overlay. | Discoverability: power-user features exist without cluttering the UI, and are findable. | Ship a `?` shortcut sheet covering palette, table nav, drawer, and import steps. | Sheet must be kept in sync as shortcuts evolve; an out-of-date help page is worse than none. |
| Close (docs) | `Cmd/Ctrl+K` palette with **contextual** command sets — different commands on a Lead page vs a Smart View — expressed as phrases ("Create lead", "Go to Smart View: X"). | Commands match what the user is looking at; plain-language verbs are guessable via typing. | Palette commands change by route (table vs drawer vs import), grouped under "This view" / "Go to" / "Create". | Context-sensitivity is harder to test; risk of commands silently missing in some routes. |
| Close (docs) | List navigation shortcuts: `j`/`k` and arrows move, `Enter` opens, `Cmd+Enter` opens in a new window, `x` checks a row, `y`/`e` mark done, `r`/`a`/`f` reply/forward — active only when not typing in a field. | High-volume triage (review queues!) becomes possible without the pointer; the "not while typing" guard prevents accidental actions. | Adopt `j`/`k` + `x` selection for the future Review Queue, guarded by an `isTypingTarget()` check on every handler. | Shortcut collisions with browser defaults (e.g. `/`) need `preventDefault` only when the app owns focus. |
| Close (docs) | `Cmd/Ctrl+Shift+F` focuses search; `Cmd/Ctrl+S` collapses the sidebar to icons-only mode. | Fixed chords stay in muscle memory; a compact nav mode reclaims width for dense tables. | Adopt: `Cmd/Ctrl+K` palette, `Cmd/Ctrl+/` focus search, sidebar collapse toggle persisted per user (localStorage is enough locally). | `Cmd+S` must be intercepted to prevent the browser's Save dialog — a common source of user surprise. |
| Close (docs + gallery) | A dedicated Email screen with a rich-text **Editor UI** (`/` quick-insert, `Cmd+Enter` submits); gallery shows a separate "Email" screen distinct from the dashboard. | Email is a two-pane workspace of its own — list left, thread/composer right — rather than a modal over a contact. | Phase-6 Emails view: two-pane layout (list \| reading/composer), keyboard: `j/k` through mail, `Cmd+Enter` sends, `/` inserts a snippet. | Largest net-new surface in Phase 6; composer needs draft autosave or users lose work. |
| folk (docs) | A **Duplicates review view appears only when duplicates are detected**; groups can be filtered by match reason ("full name is a match"), reviewed one by one, or "merge all"; exact matches auto-merge silently during import. | Empty-when-not-needed UI: the queue carries zero cognitive cost until it has real work, and each item states *why* it's there. | Review Queue shows only actionable items; each row states its reason and offers Merge / Skip; hidden entirely when empty (with a Settings entry point). | Auto-merge is risky without user trust; CRM_Local should default to *suggest*, never auto-merge. |
| folk (docs) | Merge screen: side-by-side comparison, choose which emails/phones/companies to keep, star marks the primary value, "Don't merge" dismisses the group. | Merging is destructive; showing both records and letting the user pick primaries prevents silent data loss. | Merge dialog in CRM_Local: two columns, per-field radio/star selection, explicit "Merge (keeps selected values)" primary action and "Keep separate" cancel. | Needs a real undo path — merging without undo is a data-loss risk; store the pre-merge snapshot. |
| folk (docs) | Import path includes "migrate from another CRM" and bulk cleaning during CSV import (data hygiene at ingest, not after). | Cleaning at ingest is 10× cheaper than cleaning later; users arrive at a usable database. | Import wizard gets an optional "Review problems" step: duplicate emails, missing names, malformed phones — fix or skip before commit. | Over-promising cleaning (AI or otherwise) sets expectations; keep v1 to deterministic checks only. |
| HubSpot (gallery — existence evidence only) | Screenshot set shows the standard surface family: data table ×2, modal ×3, profile page ×2, onboarding ×2, dashboard, signup/login. | Confirms the minimum viable surface list a serious CRM ships — nothing more can be claimed from captions. | Use as a **coverage checklist** for Phase 6: table, drawer/profile, modals, onboarding/empty, settings — not as a source of interaction detail. | Weak evidence; do not cite for specific behaviors. |
| Zoho CRM (gallery — existence evidence only) | Screenshot set is settings/form/modal-heavy: settings panel, form ×4, editor, modal ×4, empty state. | Confirms settings-as-panel and forms-in-modals are common; also that empty states are first-class screens. | Settings view in CRM_Local: left sub-nav + right form panel; destructive actions behind a confirm modal with explicit verbs. | Zoho's density is notoriously heavy; copy the *structure*, not the visual weight. |
| Clay (gallery — existence evidence only) | Screenshot set includes a dedicated **Search interface**, a **Loading** screen, two **Empty states**, **Navigation UI**, settings panel, modals, integrations screen, profile pages. | Search as its own surface, deliberate loading states, and designed empty states are treated as real screens, not afterthoughts. | (a) search results get a full view; (b) skeleton loading states for tables/drawers; (c) every empty list gets a written empty state with one primary action. | Full-page search may be overkill for a local CRM — an overlay palette can cover it; decide in Phase 1. |
| fudge.design (gallery — pattern write-up) | Navigation active-state clarity called out as a core CRM pattern. | Users orient by "where am I"; a weak active state makes a dense app feel unreliable. | Sidebar active item: filled background + `aria-current="page"` + accent left-bar; never color alone (icon shape + text weight also change). | Three simultaneous signals can look heavy; tune contrast so it stays calm. |
| fudge.design (gallery — pattern write-up) | Quiet secondary metadata inside rows (dates, counts, domains set back visually). | Primary column stays scannable; metadata is available but never competes. | Two-tier row text: primary `#1C1C1A`, secondary `#5F5E59` at 12–13px with `tabular-nums`. | Too-quiet metadata fails low-vision users — keep secondary ≥ 4.5:1 (it is: 6.5:1) and never below 12px. |
| fudge.design (gallery — pattern write-up) | A few meaningful totals instead of a chart per number. | Totals answer real questions ("how many leads left?") without visual noise. | Home view KPI strip: 3–4 text metrics (contacts, open tasks, unread, last import) — plain numbers, no charts, per the ban list. | Bigger numbers tempt "oversized number" styling — cap at 24px per the banned list. |
| fudge.design (gallery — pattern write-up) | Filters adjacent to the list; bulk actions appear only when rows are selected. | Controls are where the data is; actions that don't apply are hidden, reducing decision load. | Selection checkboxes in the contacts table reveal a bulk bar (tag, export, delete) that disappears at zero selection. | Hidden-until-selected actions are undiscoverable — show a disabled hint or teach via the empty selection state. |

Row count: 28 rows · products covered: Attio, Linear, Close, folk, HubSpot, Zoho CRM, Clay (7) · interaction areas covered: contact tables, company/record profiles, detail drawers, navigation grouping, search + command palette, import wizards, review queues, modals/dialogs, settings, email two-pane, contextual row actions, keyboard navigation, empty states.

## 3. Anti-patterns (banned direction, with reasons)

| Anti-pattern | Why rejected here |
|---|---|
| Purple gradients / glassmorphism / glowing borders | Distracts from data, wrecks text contrast in dark mode, reads as "AI-generated landing page" (frontend-design anti-tell). |
| Decorative backgrounds, illustrations | A working CRM should feel like a tool, not a brochure; every pixel not spent on data is waste. |
| Oversized numbers / hero KPIs | Explicitly banned; also pushes real rows below the fold. |
| Excessive rounded cards, unnecessary shadows | Cards-in-cards ("card soup") destroys row scanning; elevation must be border-first. |
| Emoji icons | Banned; emoji render inconsistently, lack AT labels, and break the calm tone. Use a self-hosted SVG set. |
| Generic feature-card grids | Marketing pattern; no place in an app shell. |
| All charts / analytics views | Banned by the brief and deleted by D-012. Totals as text only. |
| Per-row action buttons everywhere | ui-ux-pro-max UX guideline (bulk actions): "Don't: repeated actions per row" — one overflow menu per row + bulk bar instead. |
| Focus outlines removed, modal without focus trap | ui-ux-pro-max UX guidelines: visible focus is High severity; keyboard traps and unreachable elements are explicit "Don'ts". |
| Auto-playing motion | ui-ux-pro-max sustainability guideline + `prefers-reduced-motion`: no scroll reveals in an app shell; motion is feedback only. |

## 4. Proposed visual direction

**Archetype:** *Minimalism & Swiss Style, data-dense* (this is the style the ui-ux-pro-max design-system pass returned at density 8/10, variance 3/10, motion 3/10 — a match for the brief's "professional, calm, dense, precise, content-first, premium"). Applied to an application shell, not a marketing page.

### 4.1 Typography (open-licensable, self-hosted)

- **UI/body:** **Inter** (SIL Open Font License) — variable woff2 bundled under `static/fonts/`, **no CDN** (Google Fonts URLs emitted by the tooling were rejected for this reason). Fallback stack: `Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`.
- **Numeric/ID contexts:** Inter with `font-variant-numeric: tabular-nums` for all table cells, counts, dates and money; optional **IBM Plex Mono** (SIL OFL) at 12px for record IDs and import row numbers only.
- **Scale:** 11px label / 12px meta / 13px table / 14px body / 16px section / 20px view title. Nothing above 20px inside the app (bans oversized display type).
- Rejected from tooling output: Fira Code as a heading font (mono headings reduce word-shape legibility in dense UI — the *tabular numerals* part of that pairing was kept instead).

### 4.2 Palette (warm-neutral grays + exactly one accent) with WCAG 2.2 AA checks

Light theme:

| Role | Hex | Contrast (measured) |
|---|---|---|
| Background | `#F7F7F5` (warm neutral) | — |
| Surface | `#FFFFFF` | — |
| Border | `#E5E4E0` | structural only (non-text) |
| Text primary | `#1C1C1A` | 15.91:1 on bg · 17.07:1 on surface ✅ |
| Text secondary | `#5F5E59` | 6.06:1 on bg · 6.50:1 on surface ✅ |
| **Accent (single)** | `#2563EB` | 4.82:1 on bg · 5.17:1 on surface · white-on-accent 5.17:1 ✅ |
| Success | `#15803D` | 4.68:1 on bg · 5.02:1 on surface ✅ |
| Warning | `#B45309` | 4.68:1 on bg · 5.02:1 on surface ✅ |
| Danger | `#B91C1C` | 6.03:1 on bg · 6.47:1 on surface ✅ |

Dark theme (system-themable via `prefers-color-scheme` + explicit override):

| Role | Hex | Contrast (measured) |
|---|---|---|
| Background | `#171715` (warm near-black) | — |
| Surface | `#1F1F1D` | — |
| Border | `#34332F` | structural only |
| Text primary | `#ECEBE7` | 13.84:1 on surface ✅ |
| Text secondary | `#A5A49D` | 6.60:1 on surface ✅ |
| Accent | `#8AB0FF` | 7.65:1 on surface ✅ · 8.32:1 as fill with `#171715` text ✅ |
| Success | `#5ECB8B` | 8.17:1 ✅ |
| Warning | `#E8A34A` | 7.68:1 ✅ |
| Danger | `#F08080` | 6.37:1 ✅ |

All ratios computed with the WCAG relative-luminance formula; every text pair meets 4.5:1 (AA normal text) and 3:1 (AA large/UI). Status is **never** color-alone: each status color ships with a text label or shape.

### 4.3 Spacing, shape, elevation

- 4px base scale: `4 / 8 / 12 / 16 / 24 / 32`.
- Dense table row: **36px**; control height 28px (compact) / 36px (default); touch targets ≥ **24×24 CSS px** (WCAG 2.2 AA 2.5.8), primary buttons 36px.
- Radius: 4px inputs/badges, 6px buttons/popovers, 8px max on panels. No pill-shaped cards.
- **Border-first elevation:** 1px `--border` for separation; shadows only on overlays (popover/drawer/modal): `0 8px 24px rgba(0,0,0,.12)` (dark: `0 8px 24px rgba(0,0,0,.4)`). No shadows on cards or rows.

### 4.4 Icons

- **Lucide** (ISC license) as a self-hosted SVG sprite/symbol sheet under `static/icons/` — 16px default, stroke 1.75, `currentColor`. Alternatives: Phosphor (MIT) or Feather (MIT).
- Rule: every icon-only control gets `aria-label` + visible tooltip; **no emoji, ever** (also enforced by the ui-ux-pro-max pre-delivery checklist).
- Note: the ui-ux-pro-max `icons` search domain returned **0 results** for every query tried this session; icon guidance above comes from its design-system checklist ("No emojis as icons — use SVG: Heroicons/Lucide") plus license analysis, not from its icon database.

### 4.5 Motion

- Feedback only: 120–160ms `ease-out` on opacity/transform for drawer, popover, row highlight, toast.
- `@media (prefers-reduced-motion: reduce)` → durations 0ms, no transforms, no shimmer on skeletons (static placeholder instead).
- No scroll reveals, no parallax, no carousels — this is an application, not a landing page.

### 4.6 Theming

- `light` / `dark` / `system` (default `system`), implemented as a `data-theme` attribute overriding the custom properties above; persisted in `localStorage`.
- All fonts, icons, and any imagery bundled locally. Zero third-party requests at runtime.

## 5. Interaction standards (to carry into Phases 1–6)

1. **Command palette:** `Cmd/Ctrl+K` everywhere; `/` focuses search; `?` opens the shortcut sheet; `Esc` closes the topmost layer.
2. **Layers:** drawer → modal → palette, each with `role="dialog"`, `aria-modal="true"`, focus trap, focus restore to the trigger on close, and background `inert`.
3. **Tables:** roving-tabindex grid; arrows move, Enter edits, Esc cancels; sortable headers with `aria-sort`; filter chips adjacent to the list; selection reveals the bulk bar; footer shows text totals (no charts).
4. **Destructive actions:** confirm dialog with a verb-named button ("Delete 3 contacts", not "OK"); toast with **Undo** for deletes/merges where feasible.
5. **Async feedback:** skeletons for table/drawer loading (no spinners on first paint); `aria-live="polite"` for import progress and result counts; `assertive` only for errors.
6. **Empty states:** every list has a written empty state — one sentence of cause + one primary action + optional secondary link. Empty Review Queue hides itself.
7. **Keyboard guard:** all single-letter shortcuts (`j`, `k`, `x`) check `event.target` for input/textarea/contenteditable before firing.
8. **Copy voice:** concrete verbs, sentence case, no hype ("Import 248 contacts", "No contacts match these filters").

## 6. Accessibility commitments (WCAG 2.2 AA)

- Contrast: all text pairs verified above (≥4.5:1); focus indicators ≥3:1 against adjacent colors.
- **Target size:** all controls ≥ 24×24 CSS px (2.5.8); icon-only buttons get padding to comply.
- **Focus visible:** keep and extend the existing `:focus-visible` ring (currently in `style.css`) to every interactive element, including inside modals (ui-ux-pro-max High-severity guideline).
- Skip link exists in CSS but is **missing from markup** — add `<a class="skip-link">` as the first body element in Phase 1.
- Full keyboard operability of: sidebar nav, table grid, drawers, palette, import wizard (step-by-step), merge dialog.
- `prefers-reduced-motion` and `prefers-contrast` respected; status never conveyed by color alone.
- Screen-reader pass (NVDA/VoiceOver) on the three highest-traffic flows: contact table → drawer → edit; import wizard; command palette.

## 7. Inform, don't decide (flagged for Phase 6 planning)

- **ES-module migration blast radius:** `static/index.html` wires behavior through inline `onclick` globals (documented in `docs/CRM_FEATURE_PARITY.md`). Converting to native ES modules (required by PRODUCT.md) will touch every handler reference at once. This is a planning risk for Phase 6, not a design decision — surfaced here so it isn't discovered mid-implementation.
- Other Phase-6 gaps confirmed by the parity doc and relevant to this research: Review Queue and Emails two-pane have **no backend yet**; command palette would be the app's **first `keydown` listener**; `sortContacts` is a no-op and `filterContacts`/`exportContacts` are referenced but undefined — the table interaction standards above depend on these being real.

---
*Produced in Phase 0 by the frontend-engineer subagent. Skill usage evidence: see `/SKILL_USAGE.md`.*
