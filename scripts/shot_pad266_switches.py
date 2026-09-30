"""PAD-266 capture: the Beetlejuice switch window (tools/spooky_emu/spkpf.py)
against a LIVE rig, headless - its page is served exactly as the window
serves it, but shown to Playwright instead of in a window on the desktop.
Presses Start on its row, then Plunge, then a pop bumper, and prints what the
board saw.

    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad266_switches.py --slot 1 --out C:\\tmp\\PAD-266
"""
import argparse
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "spooky_emu"))
import spkpf  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--distro", default="PAD-Runtime")
    ap.add_argument("--slot", default="0")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    app, rig, host = spkpf.serve(args.distro, args.slot)
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_page(viewport={"width": 560, "height": 860})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(host.url())
        page.wait_for_selector(".row")
        time.sleep(2)
        page.screenshot(path=os.path.join(args.out, "switches.png"))
        print("at rest:", app.live)

        def press(text):
            row = page.locator(".row", has_text=text).first
            row.hover()
            page.mouse.down()
            time.sleep(0.25)
            page.mouse.up()

        press("Start Button")
        time.sleep(6)
        print("after Start:", app.live)
        page.screenshot(path=os.path.join(args.out, "switches_ball_served.png"))
        page.keyboard.press("p")                    # Plunge
        time.sleep(2)
        press("Top Pop Bumper")
        time.sleep(1)
        print("after Plunge + pop:", app.live)
        b.close()
    app.stopping = True
    rig.close()
    host.stop()
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
