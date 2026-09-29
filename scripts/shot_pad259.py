"""PAD-259 before/after: the key panel's BALLS section on the playfield demo.

    python scripts/shot_pad259.py <checkout> <out.png>

Serves <checkout>'s scripts/playfield_demo.py (field view, page only) and
captures the BALLS section, where this ticket adds "Spin disc (hold)" for a
title with an Angle Sensor Threshold switch. The demo title has one from this
ticket on; main's does not, which is the before. Playwright from PAD_PWLIB.
"""
import os
import subprocess
import sys
import tempfile
import time

if os.environ.get("PAD_PWLIB"):
    sys.path.insert(0, os.environ["PAD_PWLIB"])


def main():
    checkout, out = sys.argv[1], sys.argv[2]
    log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False).name
    proc = subprocess.Popen(
        [sys.executable, os.path.join(checkout, "scripts", "playfield_demo.py"),
         "field", "--window", "none", "--seconds", "60"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT, cwd=checkout)
    try:
        url = None
        for _ in range(120):
            txt = open(log, encoding="utf8", errors="replace").read()
            urls = [ln.split()[1] for ln in txt.splitlines()
                    if ln.startswith("URL ")]
            if urls:
                url = urls[0]
                break
            time.sleep(0.5)
        if not url:
            sys.exit("the demo never printed its URL:\n" + txt)
        from playwright.sync_api import sync_playwright
        errors = []
        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge")
            pg = b.new_page(viewport={"width": 1180, "height": 900})
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(url)
            pg.wait_for_timeout(3000)
            sec = pg.locator(".kp-sec", has=pg.locator(".kp-ball"))
            sec.screenshot(path=out)
            print("buttons:", pg.locator(".kp-sec .kp-btns button")
                  .all_inner_texts())
            b.close()
        if errors:
            sys.exit("page errors: %r" % errors)
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
