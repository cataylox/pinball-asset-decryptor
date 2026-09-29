"""PAD-257 capture: the BoF switch window (tools/bof_emu/bofpf.py) against a
LIVE rig, headless - its page is served exactly as the window serves it, but
shown to Playwright instead of in a window on the desktop.

    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad257_switches.py --title dune --art <UNC path to pfart.webp> --out C:\\tmp\\PAD-257\\sw
"""
import argparse
import os
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "bof_emu"))
import bofpf  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--art", default="")
    ap.add_argument("--distro", default="PAD-Runtime")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    prof = bofpf.load_profile(args.title)
    rig = bofpf.Rig(args.distro, "0")
    app = bofpf.App(prof, rig, args.art)
    host = bofpf.pfweb.WebHost(os.path.join(bofpf.HERE, "bofpage"), app)
    app.host = host
    host.start()
    threading.Thread(target=app.poll, daemon=True).start()
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_page(viewport={"width": 980, "height": 860})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(host.url())
        page.wait_for_selector(".row")
        time.sleep(2)
        page.screenshot(path=os.path.join(args.out, "window.png"))
        # Start, pressed on its row the way a user would
        start = page.locator(".row", has_text="START").first
        start.hover()
        page.mouse.down()
        time.sleep(0.2)
        page.mouse.up()
        time.sleep(6)
        # hold the left flipper with the keyboard while capturing
        page.keyboard.down("z")
        time.sleep(0.8)
        page.screenshot(path=os.path.join(args.out, "window_flipper_held.png"))
        page.keyboard.up("z")
        time.sleep(1)
        print("live:", app.live)
        b.close()
    app.stopping = True
    rig.close()
    host.stop()
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
