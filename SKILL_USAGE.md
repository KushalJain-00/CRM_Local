# SKILL_USAGE.md — Evidence of Mandatory Skill Usage (Phase 0)

Both mandatory skills for this phase were loaded with the skill tool **before** any research or writing began, and their guidance was applied — and in places explicitly overruled — while producing `docs/DESIGN_RESEARCH.md`.

---

## Skill 1: `ui-ux-pro-max`

- **Skill ID:** `ui-ux-pro-max`
- **Skill file:** `/home/kushal_jain/.agents/skills/ui-ux-pro-max/SKILL.md`
- **Loaded:** via the skill tool at session start (full skill content in context).

### How it was actually used

The skill ships a Python 3 stdlib search CLI. Python 3.14.7 was confirmed present (nothing installed). Real queries executed against the skill's own data files:

| Command (from skill base dir) | Result used? |
|---|---|
| `python3 scripts/search.py "crm contact table dense data grid row actions" --domain ux` | **Yes.** Top result: *"Allow multi-select and bulk edit / Don't: single row actions only / Good: checkbox column + action bar"* → directly shaped findings rows for contextual row actions and the anti-pattern "per-row action buttons everywhere" in §3 of DESIGN_RESEARCH.md. Second result: table horizontal-overflow handling → the responsive note in interaction standards. |
| `python3 scripts/search.py "command palette keyboard navigation modal focus trap" --domain ux` | **Yes.** High-severity results: visible focus ring on every control including modal contents; complete keyboard navigation with visible focus; no keyboard traps → §5.2 (focus trap / focus restore / `inert`) and §6 accessibility commitments. |
| `python3 scripts/search.py "tabular numerals data dense interface type scale" --domain typography` | **Partially.** "Dashboard Data" pairing (mono + sans, "precise, data-dense") → kept the *tabular numerals / mono-for-IDs* idea; rejected its font choices (see rejected list). |
| `python3 scripts/search.py "neutral gray accent professional SaaS" --domain color` | **Partially.** Confirmed the "trust blue + neutral background" SaaS convention already used by the repo (`#2563EB` on `#F8FAFC`) is a legitimate starting point; the emitted `#6366F1` indigo palette was rejected (indigo/purple is banned by the brief). |
| `python3 scripts/search.py "crm data-dense professional" --design-system --project-name CRM_Local --density 8 --variance 3 --motion 3` | **Yes, with rejections.** Dials (density 8, variance 3, motion 3) and the returned style **"Minimalism & Swiss Style"** (light+dark, "functional, grid-based, professional tools", low accessibility risk requiring `contrast-text-4.5, keyboard, visible-focus, reduced-motion`) were adopted as the §4 archetype. Its pre-delivery checklist (no emoji icons → SVG; visible focus; reduced motion; 4.5:1 contrast; breakpoints 375/768/1024/1440) was adopted verbatim in §4/§6. |
| `python3 scripts/search.py "icons" / "iconography" / "lucide" --domain icons` | **No — empty result.** The skill's `icons.csv` returned 0 matches for all three queries. The skill's own instruction says to say so explicitly: **no database match was found**, so icon guidance in DESIGN_RESEARCH.md §4.4 rests on the skill's design-system checklist (SVG, no emoji) plus license analysis (Lucide ISC / Phosphor MIT), not on its icon database. |

### Guidance adopted

- Density dial 8/10 + variance 3/10 + motion 3/10 → dense, minimal, low-motion direction (§4).
- "Minimalism & Swiss Style" as the style archetype, with light **and** dark mode support (§4).
- Pre-delivery checklist: no emoji icons (use SVG), visible focus states, `prefers-reduced-motion`, ≥4.5:1 text contrast, responsive breakpoints (§4, §6).
- UX guidelines: multi-select + bulk action bar instead of repeated per-row actions (findings row + §3 anti-pattern).
- UX guidelines: visible focus on every control including inside modals; complete keyboard navigation; no keyboard traps (§5.2, §6).
- Typography insight: tabular numerals for data-dense UI (§4.1).
- Color insight: neutral background + single trust-blue accent is a valid professional SaaS baseline (§4.2).
- Sustainability guideline: no autoplaying motion; reduced-motion honored (§4.5).

### Guidance rejected (and why)

- **Google Fonts `@import` / CDN URLs** emitted by the design-system and typography output — PRODUCT.md bans CDNs; fonts must be bundled locally. Replaced with self-hosted Inter/IBM Plex woff2 (§4.1).
- **Fira Code as heading font** — mono headings hurt word-shape legibility in a dense application; kept only the tabular/mono-for-IDs idea.
- **`#6366F1` indigo primary** from the color results — indigo/violet sits in the banned purple family.
- **"Enterprise Gateway" pattern** (hero video, mega menu, logo carousel, Contact Sales CTA) — a marketing-landing pattern with no application in a local CRM shell; its reduced-motion caveats were noted but the pattern discarded.
- **GSAP scroll-reveal motion recipe** — scroll reveals are a landing-page device; the brief bans decorative motion, and DESIGN_RESEARCH.md §4.5 permits feedback-only motion.
- **"Accent/CTA `#D97706` amber" second accent** from the design-system output — the brief allows **one** accent; semantic status colors are functional, not decorative accents.

---

## Skill 2: `frontend-design`

- **Skill ID:** `frontend-design`
- **Skill file:** `/home/kushal_jain/.agents/skills/frontend-design/SKILL.md`
- **Loaded:** via the skill tool at session start (full skill content in context).

### Guidance adopted

- **Anti-AI-tell discipline:** the research explicitly lists the banned visual tropes (purple gradients, glassmorphism, glowing borders, emoji icons, generic feature-card grids, oversized numbers) as rejected *with reasons*, rather than silently omitting them — §3 ties each to a concrete failure mode.
- **Restraint / content-first:** direction §4 is border-first elevation, ≤20px type inside the app, 4px spacing scale, one accent — no decorative layers anywhere in the proposal.
- **Type critique:** rejected the mono-heading pairing from the other skill on legibility grounds; set an explicit small type scale (11–20px) instead of a display scale (§4.1).
- **Copy voice:** concrete, sentence-case verbs; example empty-state/error phrasing in §5.8; banned hype language.
- **Layout critique:** findings rows repeatedly reward "controls adjacent to the data" (filters above the table, totals in the footer, actions on the row) — this adjacency principle is stated as an interaction standard (§5.3).

### Guidance rejected (and why)

- Any **marketing-page / hero-first** direction the skill covers (landing heroes, brand statements) — CRM_Local is an application shell; the skill's landing guidance was not applied.
- No other conflicts: the brief's banned list and the skill's anti-slop list agree, so nothing else needed overriding.

---

## Where the skills changed the output

| Output location | Skill influence |
|---|---|
| DESIGN_RESEARCH.md §2 findings rows (row actions, keyboard, focus) | `ui-ux-pro-max` ux-domain search results |
| DESIGN_RESEARCH.md §3 anti-patterns table | `frontend-design` anti-tell list + `ui-ux-pro-max` "Don't" entries |
| DESIGN_RESEARCH.md §4 archetype, dials, checklist | `ui-ux-pro-max --design-system` run (with documented rejections) |
| DESIGN_RESEARCH.md §4.1 typography | Both skills' type critique (kept tabular numerals, dropped mono headings + CDNs) |
| DESIGN_RESEARCH.md §4.4 icons | `ui-ux-pro-max` checklist (icons database empty — stated honestly) |
| DESIGN_RESEARCH.md §5–§6 interaction + a11y standards | `ui-ux-pro-max` High-severity accessibility guidelines + `frontend-design` restraint/copy rules |

---
*Written in Phase 0. Files changed this phase: `docs/DESIGN_RESEARCH.md` (new) and this file (new). No code, config, or other docs were modified; nothing was committed.*
