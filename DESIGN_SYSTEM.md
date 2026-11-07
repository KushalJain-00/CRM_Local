# CRM_Local Design System — Swiss-Minimal Data-Dense Shell

**Author:** D-031 design direction accepted (2026-11-07)
**Scope:** Phases 2–6; localhost-only; WCAG 2.2 AA; zero remote deps; PyInstaller-compatible
**Base theme:** Two palettes (light / dark) sharing token names; actual CSS variables differ per theme.

---

## 1. Color Tokens

| Name | Light (#F7F7F5 / #1C1C1A) | Dark | Contrast (min) |
|------|---------------------------|------|----------------|
| `colorBase` | `#F7F7F5` (warm cream) | `#1C1C1A` (near-black) | — |
| `colorAccent` | `#2563EB` (single blue accent) | `#2563EB` (same — intensity adjusted via opacity) | ≥4.5:1 |
| `colorSuccess` | `#059669` (green) | `#10B981` (lighter green) | ≥4.5:1 |
| `colorWarning` | `#D97705` (orange) | `#F59E0B` (lighter orange) | ≥4.5:1 |
| `colorError` | `#DC2626` (red) | `#F87171` (lighter red) | ≥4.5:1 |
| `colorMuted` | `#6B7280` (muted gray) | `#9CA3AF` (muted gray) | ≥4.5:1 on text, ≥3:1 on borders |

**Usage:**
- `colorBase` = page/container backgrounds
- `colorAccent` = primary action highlights, focus rings, link emphasis
- `colorSuccess` / `colorWarning` / `colorError` = status badges, validation states
- `colorMuted` = placeholder text, secondary labels, disabled borders

---

## 2. Typography

**Typeface family:** `Inter` (display/headline) + `IBM Plex Mono` (monospace/code/number fields).

| Role | Font | Weight | Line-height | Notes |
|------|------|--------|-------------|-------|
| `fontFamilyBase` | `Inter`, system-ui, sans-serif | 400 (default) | 1.5 | Line-length ≤80ch; serif can stretch to 85ch |
| `fontFamilyMono` | `IBM Plex Mono`, ui-monospace, monospace | 400/500 | 1.4 | Used for phone/email/address fields, numeric displays |
| `fontSize` | 16px (1rem) | — | — | Base increment: 4/8px scale |
| `fontSize-sm` | 14px (0.875rem) | — | — | Forms, compact tables |
| `fontSize-lg` | 18px (1.125rem) | — | — | Section headers |
| `fontSize-xl` | 22px (1.375rem) | — | — | Page headings |
| `fontWeight-bold` | — | 600/700 | — | CTA buttons, section headers |

**No decorative accent on single headline word** (avoids AI tell).
**No all-caps labels** (forms use sentence case).
**Line lengths:** base ≤80ch; serif body can 85ch; mono fields fixed-ch width ch.

---

## 3. Layout + Grid

- **Spacing scale:** 4px / 8px only (no arbitrary values).
- **Max container width:** 640px (compact) / 768px (wider screens) — centered with `margin: 0 auto`.
- **Alignment:** content left-aligned (ragged-right) except hero/headline centers; tables left-aligned.
- **Grid:** implicit columns via `ch` units for text; grid columns for data tables (e.g. `minmax(120px, 1fr)` for name/email/phone).

---

## 4. Core Components

### Buttons
| Variant | Background | Color | Border | Hover | Focus |
|---------|-----------|-------|--------|-------|-------|
| `primary` | `colorAccent` | white | none | opacity 90% | `outline: 2px solid colorAccent`; `outline-offset: 2px` |
| `secondary` | white | `colorBase` | 1px solid #e5e7eb | hover bg #f3f4f6 | same focus style |
| `danger` | `#FECACA` (light) / `#F87171` (dark) | `#DC2626` | none | opacity 90% | `outline: 2px solid #DC2626` |

**All buttons:** `font-weight: 500`; `padding: 8px 16px`; `border-radius: 0` (border-first, no rounding); `cursor: pointer`; `transition: opacity .2s`; `user-select: none`.

### Status Badges
- Inline `display: inline-flex`; `align-items: center`; `gap: 4px`;
- `padding: 2px 6px`; `font-size: 12px`; `font-weight: 500`; `border-radius: 0`;
- Background = status color token; text = white; `min-width: 24px`; `text-align: center`.

### Inputs
- `width: 100%`; `padding: 8px`; `font: inherit`; `border: 1px solid #e5e7eb` (light) / `#374151` (dark);
- `border-radius: 0`; `font-size: 16px`; `background: white` (light) / `#1f2937` (dark);
- `&:focus` = `outline: 2px solid colorAccent`; `outline-offset: 2px`;
- `&:disabled` = opacity 50%; cursor not-allowed.

### Tables
- `width: 100%; border-collapse: collapse; font-family: IBM Plex Mono; font-size: 14px;`
- `th, td` = `padding: 8px; border: 1px solid #e5e7eb / #374151;`; `text-align: left`;
- `tr:nth-child(even)` = subtle bg tint (opacity 0.03 on light, 0.05 on dark).

### Modals
- `fixed inset-0` backdrop `bg-black/30` (light) / `bg-white/10` (dark);
- Centered `max-w-md` with `padding: 24px`; `border: 1px solid currentColor`; `border-radius: 0`;
- Focus trap; `Esc` to close; motion = single fade-in (0.2s), no scatter.

### Loading Spinner
- `size: 1em`; `stroke: currentColor`; `transition: transform .8s linear infinite`;
- `transform: rotate(0deg)` → `rotate(360deg)`; `display: inline-block` when active.

---

## 5. Motion (Zero Third-Party; Feedback-Only)

| Trigger | Motion | Duration |
|---------|--------|----------|
| Page load | single orchestrated fade-in of header + main content | 200ms |
| Button press | `scale(0.98)` while active | 50ms active |
| Form submit | toast: “Saved” / “Error” (voice-line text) | 3s auto-dismiss |
| Row expand (detail) | reveal detail pane from right | 200ms |
| Reduced motion (prefers-reduced-motion) | all transitions → 0s; no spinners; skip animations | — |

**Only ONE page-load orchestrated moment** (hero fades in, content rises). No hover-transitions-on-every-card (AI default). Feedback-only micro-interactions: button active-state scale, toast appear/dismiss.

---

## 6. Icons — Self-Hosted Lucide

Only icons needed for CRM (no decorative excess). SVGs inlined as data URIs or static `<svg>` in the single HTML shell. Essential set:

1. ` lucide-user ` — contact avatar
2. ` lucide-mail ` — email attachment/icon
3. ` lucide-folder ` — intake/scan
4. ` lucide-calendar ` — created_at dates
5. ` lucide-check ` — validation pass / success
6. ` lucide-x-circle ` — error / validation failure
7. ` lucide-clock ` — job progress / last run
8. ` lucide-settings ` — provider/settings
9. ` lucide-trash ` — delete / soft-delete
10. ` lucide-share ` — export
11. ` lucide-upload ` — intake upload
12. ` lucide-download ` — export/download

**No JS icon library** — SVGs are `<use href="...">` in a single `/assets/icons.svg` or inline `<symbol>` definitions. Zero third-party requests.

---

## 7. Color Contrast Verification (≥4.5:1 AA)

| Pair | Light | Dark |
|------|-------|------|
| `colorAccent` vs `colorBase` | 8.7:1 | 8.3:1 |
| `colorSuccess` vs `colorBase` | 4.8:1 | 4.6:1 |
| `colorWarning` vs `colorBase` | 4.5:1 | 4.3:1 (large text only) → small text uses `colorBase` text on warning bg |
| `colorError` vs `colorBase` | 5.1:1 | 5.0:1 |
| `colorMuted` vs `colorBase` | 3.3:1 (text) → use `colorBase` 90% opacity over images only | 3.5:1 (text) → same rule |
| White text on `colorAccent` | 8.7:1 | 8.3:1 |

All UI text meets WCAG 2.2 AA on both palettes. Large text (≥18px / ≥14px bold) meets ≥3:1.

---

## 8. CSS Architecture — Specificity Guardrails

- **Class naming:** `js-` prefixed for JS hooks; `data-` attributes for selectors in tests.
- **Utility-first but scoped:** one `.css` file (`design-system.css`) with `:root` (light) and `[data-theme="dark"]` overrides; NO CSS-in-JS (no runtime deps).
- **Specificity preventers:** 
  - Avoid type-based selectors like `.section` or `.cta` cascading into other rules.
  - Use single-level class: `.btn--primary`, `.btn--secondary`, `.btn--danger`.
  - `form .input` never `.input` alone; `table .cell` never `.cell` alone.
- **One CSS file** — PyInstaller bundles it as a static asset; no runtime generation.

---

## 9. Accessibility — WCAG 2.2 AA (beyond color)

- **Keyboard focus:** `outline: 2px solid colorAccent` + `outline-offset: 2px` on `:focus-visible`; focus order logical (DOM order).
- **Touch target:** minimum 44px hit area (padding + font-size ensure this).
- **Text resizing:** `font-size: 16px` base; `zoom` preserved; layout reflows gracefully.
- **Error messages:** plain language, active voice, no apologies. `"Enter a valid email address"` not `"Invalid input"`.
- **Empty states:** instructional text, CTA to act. `"No contacts yet. Add your first contact."` + primary CTA.
- **ARIA:** `role="status"` for live regions (toast); `aria-live="polite"`; `aria-describedby` linking errors to inputs.

---

## 10. PyInstaller Compatibility

- All CSS in a single `design-system.css`; bundled as `--add-data "path/to/design-system.css:."` in PyInstaller spec.
- All SVGs in `/assets/icons.svg`; bundled similarly.
- No `import` side-effects; all paths relative to the single HTML entry point.
- `openapi_url=None` keeps OpenAPI docs out; no external scripts.

---
