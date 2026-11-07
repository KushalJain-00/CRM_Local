#!/usr/bin/env python3
"""WCAG 2.2 contrast verification for the CRM Local token set (both themes)."""

def oklch_to_srgb(L, C, H):
    import math
    hr = math.radians(H)
    a = C * math.cos(hr)
    b = C * math.sin(hr)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l = l_ ** 3; m = m_ ** 3; s = s_ ** 3
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    def lin2srgb(u):
        u = max(0.0, min(1.0, u))
        return u * 12.92 if u <= 0.0031308 else 1.055 * (u ** (1 / 2.4)) - 0.055
    return lin2srgb(r), lin2srgb(g), lin2srgb(bb)

def rel_lum(rgb):
    def f(u):
        return u / 12.92 if u <= 0.03928 else ((u + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def contrast(fg, bg):
    l1, l2 = rel_lum(fg), rel_lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)

# (name, fg oklch, bg oklch)
LIGHT_BASE = (0.973, 0.004, 90)
LIGHT_RAISED = (1.0, 0.0, 0)
DARK_BASE = (0.19, 0.006, 260)
DARK_RAISED = (0.22, 0.006, 260)
DARK_POPOVER = (0.26, 0.007, 260)

LIGHT = [
    ("text-primary/base",      (0.24, 0.012, 260), LIGHT_BASE),
    ("text-secondary/base",    (0.44, 0.014, 260), LIGHT_BASE),
    ("text-faint/base",        (0.50, 0.012, 260), LIGHT_BASE),
    ("text-primary/raised",    (0.24, 0.012, 260), LIGHT_RAISED),
    ("text-secondary/raised",  (0.44, 0.014, 260), LIGHT_RAISED),
    ("accent-text/raised",     (0.46, 0.19, 257), LIGHT_RAISED),
    ("danger-text/raised",     (0.47, 0.18, 25),  LIGHT_RAISED),
    ("warning-text/raised",    (0.43, 0.11, 65),  LIGHT_RAISED),
    ("success-text/raised",    (0.45, 0.11, 160), LIGHT_RAISED),
    ("on-accent/accent",       (1.0, 0.0, 0),     (0.52, 0.20, 257)),
    ("accent(3:1 non-text)/base", (0.52, 0.20, 257), LIGHT_BASE),
]
DARK = [
    ("text-primary/base",      (0.91, 0.004, 260), DARK_BASE),
    ("text-secondary/base",    (0.71, 0.005, 260), DARK_BASE),
    ("text-faint/base",        (0.64, 0.005, 260), DARK_BASE),
    ("text-primary/raised",    (0.91, 0.004, 260), DARK_RAISED),
    ("text-secondary/raised",  (0.71, 0.005, 260), DARK_RAISED),
    ("text-secondary/popover", (0.71, 0.005, 260), DARK_POPOVER),
    ("accent-text/raised",     (0.80, 0.09, 253),  DARK_RAISED),
    ("danger-text/raised",     (0.72, 0.16, 25),   DARK_RAISED),
    ("warning-text/raised",    (0.80, 0.13, 78),   DARK_RAISED),
    ("success-text/raised",    (0.76, 0.13, 162),  DARK_RAISED),
    ("on-accent/accent",       (0.18, 0.02, 253),  (0.78, 0.09, 253)),
    ("accent(3:1 non-text)/base", (0.78, 0.09, 253), DARK_BASE),
]

def run(name, pairs):
    print(f"── {name} ──")
    ok = True
    for label, fg, bg in pairs:
        ratio = contrast(oklch_to_srgb(*fg), oklch_to_srgb(*bg))
        need = 3.0 if "non-text" in label else 4.5
        mark = "PASS" if ratio >= need else "FAIL"
        if ratio < need: ok = False
        print(f"  {mark}  {ratio:5.2f}:1  (need {need}:1)  {label}")
    return ok

if __name__ == "__main__":
    a = run("LIGHT", LIGHT)
    b = run("DARK", DARK)
    print("\nALL PASS" if a and b else "\nSOME FAILURES")
