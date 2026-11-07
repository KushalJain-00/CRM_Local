#!/usr/bin/env python3
"""UI verification for the CRM Local redesign (screenshots + checks)."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8787"
OUT = Path("/tmp/shots"); OUT.mkdir(exist_ok=True)
errors, failed_requests, external = [], [], []

def shoot(page, name, full=False):
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print(f"  shot: {name}.png")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page = ctx.new_page()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("request", lambda r: external.append(r.url) if r.url.startswith("http") and "localhost" not in r.url else None)
        page.on("requestfailed", lambda r: failed_requests.append(r.url))

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(900)

        # fonts loaded?
        fonts = page.evaluate("() => ({inter: document.fonts.check('14px Inter'), mono: document.fonts.check('13px \"IBM Plex Mono\"')})")
        print("fonts:", fonts)
        theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
        print("resolved theme:", theme)

        shoot(page, "01-overview-light")
        page.click('button[aria-label="Refresh data"]')
        page.wait_for_timeout(600)

        # Contacts
        page.click('.nav-item[data-view="contacts"]')
        page.wait_for_timeout(800)
        shoot(page, "02-contacts-light")
        # select two rows -> bulk bar
        boxes = page.locator('#contactsBody .row-check')
        if boxes.count() >= 2:
            boxes.nth(0).check(); boxes.nth(1).check()
            page.wait_for_timeout(200)
            shoot(page, "03-contacts-bulkbar")
        # open drawer
        page.locator('#contactsBody .row-btn').first.click()
        page.wait_for_timeout(500)
        shoot(page, "04-drawer-profile")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        # confirm dialog
        page.locator('#contactsBody .row-btn.danger').first.click()
        page.wait_for_timeout(400)
        shoot(page, "05-confirm-dialog")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # Staged + keyboard triage
        page.click('.nav-item[data-view="staged"]')
        page.wait_for_timeout(800)
        shoot(page, "06-staged-light")
        page.evaluate("document.activeElement && document.activeElement.blur()")
        page.keyboard.press("j"); page.keyboard.press("j"); page.wait_for_timeout(250)
        shoot(page, "07-staged-kbd-row")
        page.keyboard.press("Enter"); page.wait_for_timeout(500)
        shoot(page, "08-staged-drawer")
        page.keyboard.press("Escape"); page.wait_for_timeout(300)
        page.keyboard.press("a"); page.wait_for_timeout(700)   # approve -> optimistic + toast
        shoot(page, "09-staged-after-approve")

        # Extract
        page.click('.nav-item[data-view="extract"]')
        page.wait_for_timeout(400)
        shoot(page, "10-extract-light")

        # Analytics (charts)
        page.click('.nav-item[data-view="analytics"]')
        page.wait_for_timeout(1200)
        shoot(page, "11-analytics-light")

        # Quality
        page.click('.nav-item[data-view="quality"]')
        page.wait_for_timeout(800)
        shoot(page, "12-quality-light")

        # History + emails + profiles
        page.click('.nav-item[data-view="emails"]'); page.wait_for_timeout(700)
        shoot(page, "13-emails-light")
        page.click('.nav-item[data-view="profiles"]'); page.wait_for_timeout(700)
        shoot(page, "14-profiles-light")
        page.click('.nav-item[data-view="history"]'); page.wait_for_timeout(700)
        shoot(page, "15-history-light")

        # Settings + dark
        page.click('.nav-item[data-view="settings"]'); page.wait_for_timeout(800)
        shoot(page, "16-settings-light")

        # Dark theme via topbar cycle (system->light->dark)
        page.click('button[aria-label^="Theme"]')  # light
        page.wait_for_timeout(300)
        page.click('button[aria-label^="Theme"]')  # dark
        page.wait_for_timeout(600)
        page.click('.nav-item[data-view="overview"]'); page.wait_for_timeout(900)
        shoot(page, "17-overview-dark")
        page.click('.nav-item[data-view="analytics"]'); page.wait_for_timeout(1200)
        shoot(page, "18-analytics-dark")
        page.click('.nav-item[data-view="staged"]'); page.wait_for_timeout(800)
        shoot(page, "19-staged-dark")
        page.click('.nav-item[data-view="contacts"]'); page.wait_for_timeout(800)
        shoot(page, "20-contacts-dark")

        # Command palette
        page.keyboard.press("Control+k"); page.wait_for_timeout(300)
        shoot(page, "21-palette")
        page.keyboard.type("cont", delay=40); page.wait_for_timeout(600)
        shoot(page, "22-palette-contacts")
        page.keyboard.press("ArrowDown"); page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter"); page.wait_for_timeout(700)
        shoot(page, "23-palette-run")

        # 900px viewport (sidebar becomes off-canvas; use hamburger)
        page.set_viewport_size({"width": 900, "height": 800})
        page.wait_for_timeout(500)
        page.click('.hamburger')
        page.wait_for_timeout(500)
        page.click('.nav-item[data-view="overview"]')
        page.wait_for_timeout(700)
        # navigating auto-closes the off-canvas sidebar; verify it really closed
        print("STATE after nav @900:", page.evaluate("({body: document.body.className, backdrop: document.getElementById('sidebarBackdrop').hidden})"))
        shoot(page, "24-overview-900")
        page.set_viewport_size({"width": 1280, "height": 720})
        page.wait_for_timeout(500)
        shoot(page, "25-overview-1280")

        # reduced motion emulation
        page2 = ctx.new_page()
        page2.emulate_media(reduced_motion="reduce")
        page2.goto(BASE, wait_until="networkidle")
        page2.wait_for_timeout(600)
        page2.screenshot(path=str(OUT / "26-reduced-motion.png"))
        print("  shot: 26-reduced-motion.png")

        browser.close()

    print("\nCONSOLE ERRORS:", len(errors))
    for e in errors[:20]: print("  -", e)
    print("FAILED REQUESTS:", len(failed_requests))
    for u in failed_requests[:20]: print("  -", u)
    ext = [u for u in external if not u.startswith(BASE)]
    print("EXTERNAL REQUESTS:", len(ext))
    for u in ext[:10]: print("  -", u)
    return 0 if not errors and not failed_requests else 1

if __name__ == "__main__":
    sys.exit(main())
