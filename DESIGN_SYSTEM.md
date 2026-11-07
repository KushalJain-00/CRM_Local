# CRM_Local Design System — "Quiet chrome, dense data"

**Scope:** Localhost-only desktop UI (FastAPI + PyInstaller), vanilla HTML/CSS/JS, zero remote dependencies, WCAG 2.2 AA.
**Supersedes:** the 2026-11-07 Swiss-minimal spec (the 640–768px max-container and radius-0 rules are retired — they were wrong for a data dashboard).

---

## 1. CSS architecture

- Single stylesheet `static/style.css`, organized in **native cascade layers**:
  `@layer reset, tokens, base, components, utilities` — no specificity wars; utilities always win.
- **Native nesting** used sparingly inside layers.
- Class naming: BEM-light single-class selectors (`.btn-primary`, `.kpi-card`, `.queue-item`).
- JS hooks: element IDs (unchanged contract) + data attributes; no `js-` prefix needed since inline-handler names are part of the contract.
- Container queries: `.content-inner` is `container-name: page`; KPI grid, attention grid, chart grid, quality grid and settings layout respond to **available width** (so they adapt when the sidebar collapses), not to viewport width. `.kpi-card` is itself a container (sparkline hides below 200px).

## 2. Token tiers

### Tier 1 — primitives (`:root`, never used directly by components)
- Fonts: `--font-ui` (Inter variable), `--font-mono` (IBM Plex Mono). Self-hosted woff2 in `static/fonts/`.
- Spacing: `--s-1…--s-8` = 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 px. **Only 4/8 steps** — 12 and 24 are 3×4/… used for control rhythm; nothing arbitrary.
- Radii: `--r-control: 6px`, `--r-panel: 8px`, `--r-pill: 999px` (pills/avatars only).
- Type scale: `--fs-12/13/14/16/20/24`. Body = 14px (density); 13px tables; 24px KPI values.
- Motion: `--dur-instant 80ms`, `--dur-fast 120ms`, `--dur-base 200ms`, `--dur-slow 320ms`; `--ease-enter: cubic-bezier(.25,1,.5,1)`, `--ease-exit: cubic-bezier(.7,0,.84,0)`. Exits ≈ 75 % of enter duration. No `ease`, no bounce.
- Okabe–Ito chart primitives (`--ok-blue…--ok-pink`).

### Tier 2 — semantic (theme-agnostic names, resolved with `light-dark()`)
| Token | Light | Dark | Notes |
|---|---|---|---|
| `--surface-base` | warm paper ≈ `#f6f6f4` | `oklch(19% …)` ≈ `#121316` | never pure white/black |
| `--surface-raised` | white | ≈ `#1a1b1f` | cards, tables |
| `--surface-popover` | white | ≈ `#23242a` | palette, toasts, dialog |
| `--surface-inset` | subtle grey | darker step | search field, tracks |
| `--text-primary` | ≈ `#1a1c20` (15.2:1) | ≈ `#e6e6e6` (14.1:1) | never pure white in dark |
| `--text-secondary` | 7.2:1 on base | 7.2:1 | meta text |
| `--text-faint` | 5.6:1 | 5.5:1 | placeholders, timestamps |
| `--border-subtle` / `--border-strong` | hairlines | `rgb(255 255 255 / 9% / 16%)` | elevation = border + surface step |
| `--accent` | ≈ `#2563eb` (5.2:1 non-text on base) | ≈ `#8ab4f8` (9.3:1) | desaturated + lightened in dark |
| `--accent-hover` / `--accent-pressed` | derived with `color-mix(in oklch, …)` | same | no hardcoded hex |
| `--success/-text`, `--warning/-text`, `--danger/-text`, `--info/-text` | AA-verified (6.9–8.3:1) | luminance-boosted (6.5–9.1:1) | color = meaning only |
| `--success-bg/-warning-bg/-danger-bg/-info-bg` | tint mixed into the surface they sit on | same | badges, banners, bulk bar |
| `--chart-1…6` | Okabe–Ito | lightness-boosted Okabe–Ito | re-verified ≥3:1 vs `--surface-raised` |
| `--shadow-1` / `--shadow-2` | whisper / popover | stronger | no heavy shadows |
| `--backdrop` | `oklch(0 0 0 / 38%)` | 58% | overlays |
| `--row-hover` | 3 % ink | 4 % light | table hover |

**Theming:** `:root { color-scheme: light dark }` + `light-dark()` on every semantic token. `[data-theme="light"]` / `[data-theme="dark"]` force one side; without them (or `data-theme-mode="system"`) the UI follows `prefers-color-scheme`. A tiny pre-paint boot script in `<head>` applies the stored preference so there is no flash. For engines without `light-dark()`, an `@supports not` fallback block mirrors the same values driven by `[data-theme]` + `prefers-color-scheme`.
**Settings offers Light / Dark / System** (segmented control + topbar cycle button + legacy hidden `#themeSelect` kept in sync).

### Tier 3 — component tokens
`--control-h 36px`, `--control-h-sm 30px`, `--sidebar-w 236px`, `--sidebar-w-collapsed 64px`, `--topbar-h 52px`, `--focus-ring`.

## 3. Typography

- Inter for UI, IBM Plex Mono for emails, phones, IDs, counts, dates, pagination.
- Scale 12 / 13 / 14 / 16 / 20 / 24; body 14. Weights **400 / 500 / 600 only** (Inter variable file).
- Sentence case everywhere; no all-caps labels (nav group headings are sentence-case, 11px, secondary).
- `font-variant-numeric: tabular-nums` on all numbers (`.num`, KPI values, table numerics, badges counts).
- `text-wrap: balance` on headings.
- Mono usage: `input.mono`, `.cell.mono`, `.q-name`, `.chart-value`, `.activity-time`, `.completeness-label`, `.provider-order`, kbd.

## 4. Layout

- Shell: collapsible sidebar (icon rail 64px, tooltips via `[data-tip]`, active item = accent bar + tint), sticky-flavored topbar (title + Ctrl+K search trigger + theme + Refresh), scrolling content region.
- Content `max-width: 1440px`, fluid, centered; padding 24px (16px ≤1100px).
- Breakpoints (media): ≤1100px sidebar auto-rail; ≤900px sidebar off-canvas (hamburger toggles, backdrop, auto-closes on navigation, hamburger floats above while open). Container queries handle the rest.
- `scrollbar-gutter: stable` on `html` and `.content`; styled thin scrollbars both themes.

## 5. Components (states: default / hover / focus-visible / active / disabled / loading / empty / error)

- **Buttons** primary / secondary / ghost / danger; `btn-sm`; `btn-icon`; `btn-link`. 36px visual height with an invisible `::after` hit-area extension to **44px effective target** (primary actions); 30px sm buttons extend ±7px. Press = `scale(.98)` 80ms. Disabled = 45 % opacity, no hit area, `not-allowed`.
- **Inputs / select / checkbox / switch / segmented**: 36px controls, focus ring = accent border + 3px `color-mix` halo; switch is a real checkbox + track; segmented uses `:has(input:checked)`.
- **Badges / severity pills**: icon + text (never color alone), tinted bg + 25 % border, pill radius.
- **Tooltips**: CSS-only `[data-tip]` on hover and `:focus-visible`; `data-tipdir="right"` variant for the collapsed rail.
- **Toasts**: stacked bottom-right in `#toasts` (`role="status"` `aria-live="polite"`), 4 s default, pause on hover, optional actions (Undo), dismiss button, enter via `@starting-style`, exit via `.is-leaving` (keyframe fallback for engines without `transition-behavior`).
- **Confirm dialog**: native `<dialog>`, centered, focus trapped by the UA, Esc handled, focus returned to opener, promise-based `confirmDialog()`. `window.confirm` fallback on very old engines.
- **Drawer**: right-side panel 440px for contact / staged detail; slide + fade; backdrop click / Esc / ✕ close; focus trap; focus returned.
- **Command palette**: Ctrl+K, grouped results (Go to view / Actions / Contacts), fuzzy subsequence scoring, listbox + `aria-activedescendant`, ↑/↓/Enter/Esc, opens ≤150 ms, fails silently if init errors.
- **Tables**: toolbar (search, filter select, density toggle, column visibility menu (`popover` attribute with hidden-toggle fallback), Export); sticky header; sortable headers = `<button class="th-btn">` + `aria-sort` + arrow; row hover; checkbox column + select-all (indeterminate state); **bulk bar appears via `:has(.row-check:checked)`** (JS `hidden` fallback for engines without `:has`); row actions revealed on hover / `:focus-within` (always visible on `hover: none` devices); ellipsis cells with `title`; numbers right-aligned mono; footer "Showing X–Y of Z" + page size + pagination.
- **Skeletons**: shimmer bars matching final row shape — no layout shift; skeletons are injected into tables/lists before fetches.
- **Empty states**: icon + one-line instruction + primary CTA (`emptyStateHTML()`), used in every table, list, chart and the activity feed.
- **Banners**: inline error/info/success with plain-language fixes.
- **Dropzone**: idle / drag-over (accent tint + border) / disabled states; click and Enter/Space open the file dialog; Browse button always present; accepted types as visible text.
- **File queue rows**: type icon, mono name, size, own status badge, own progress bar, retry/remove, per-row error text.
- **Provider chain**: ordered list, index chip, provider/model/key inputs, enable switch, status dot, up/down/remove.
- **KPI cards**: label, 24px tabular value, optional delta chip (tone = meaning, not direction) and optional sparkline (only when the API returns them; omitted otherwise).

## 6. Motion

| Trigger | Spec |
|---|---|
| View switch | same-document View Transition: fade + 4–8px rise, 200ms; instant fallback |
| Drawer | 320ms enter `--ease-enter`, 240ms exit `--ease-exit` |
| Dialog / toast | `@starting-style` + `transition-behavior: allow-discrete`; keyframe fallback |
| Button press | scale(.98), 80ms |
| Skeleton | shimmer 1.4s linear |
| KPI count-up | first load only, ≤600ms, skipped when unchanged or reduced motion |
| Chart bars | grow once on first reveal (IntersectionObserver, unobserve after); stagger 30ms |
| Hover | no transitions on cards; only color/background fast changes |

Only `transform` and `opacity` animate (sidebar rail width is the single deliberate exception). `prefers-reduced-motion: reduce` removes movement, count-up and bar growth; focus styles and progress bars stay functional; skeleton shimmer stops.

## 7. Charts (hand-built SVG/CSS, zero dependencies)

- Geographic distribution → horizontal bars, top 8 + "Other" (muted), direct value labels.
- Field completeness → horizontal progress bars sorted desc, direct % labels (<50 % flagged warning).
- Reachability → donut ≤5 slices, center total, legend rows with values + %; slices focusable with `<title>`.
- Extraction sources → horizontal bars by file type.
- Rules: bars start at zero; no gridlines, no 3D; direct labels instead of legends (donut legend doubles as labels); title states the **takeaway** ("84 % of contacts have an email"), chart name is the subtitle; same category = same color everywhere (email = chart-1, phone = chart-2, both = chart-3, unreachable = muted); Okabe–Ito palette, dark-boosted; tooltips via native `<title>` + focusable rows with `aria-label`; "View as table" toggle + always-present visually-hidden table; re-render on theme change (`crm:themechange`) and container resize (ResizeObserver, debounced); friendly empty states; **nothing fabricated** — charts render only from fields the API actually returns (geo chart shows an honest empty state until a location field exists).

## 8. Accessibility (WCAG 2.2 AA)

- Contrast: verified programmatically in both themes (see `tools/contrast_check.py` output): all text ≥ 5.5:1 (worst pair), non-text accent ≥ 3:1.
- `:focus-visible` ring everywhere (`outline: 2px solid var(--focus-ring); offset 2px`); inputs get an additional halo.
- 44px effective targets for primary actions and topbar/nav controls via invisible hit-area pseudos; table row buttons ≥ 24px (AA 2.5.8).
- Real `<button>` / `<a href>` elements only; keyboard triage (J/K/↑/↓/A/R/D/Enter) guarded against text inputs and overlays; Ctrl+K palette with full listbox semantics; toasts `role="status"`; dialog/drawer with focus trap + return; `[hidden] { display: none !important }` guarantees state integrity.
- Skip link, landmark regions, `aria-label`s on icon-only controls, `aria-sort` on sortable headers, `aria-expanded` on disclosure buttons, visually-hidden data tables for charts.

## 9. Icons

One inline SVG sprite in `index.html` (~50 Lucide-style 24×24 stroke symbols, `currentColor`). Usage: `<svg class="icon"><use href="#i-users"/></svg>`. No icon font, no remote requests.

## 10. Fonts & PyInstaller

- `static/fonts/InterVariable.woff2` (352 KB), `IBMPlexMono-Regular/Medium/SemiBold.woff2` (~46 KB each), declared with `font-display: swap`; relative URLs in CSS so bundling paths just work.
- Ship with `--add-data "static:static"` (or equivalent); no build step, no CDN, no npm at runtime.
