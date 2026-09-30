"""PAD-266 capture: the Beetlejuice virtual playfield (tools/spooky_emu/spkpf.py
-> tools/ap_emu/appf.py) against a LIVE rig, headless - its page is served
exactly as the window serves it, but shown to Playwright instead of in a
window on the desktop.  Presses Start with its key (1), plunges (F), hits
playfield switches with their letters, drains (D), and prints what the
window saw.

    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad266_switches.py --slot 1 --out C:\\tmp\\PAD-266
"""
import argparse
import json
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
    ap.add_argument("--audio-ctl", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    table_path = r"\\wsl.localhost\%s\var\tmp\pad_spooky\rig%s\switches.json" % (
        args.distro, args.slot)
    with open(table_path, encoding="utf-8") as f:
        table = json.load(f)
    app, rig, host = spkpf.serve(table, args.distro, args.slot, args.audio_ctl)
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_page(viewport={"width": 1000, "height": 980})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(host.url())
        time.sleep(4)
        page.screenshot(path=os.path.join(args.out, "playfield.png"))
        print("at rest:", app._balls()[3])
        page.keyboard.press("Digit5")               # a coin
        time.sleep(1)
        page.keyboard.press("Digit1")               # Start
        time.sleep(6)
        print("after Start:", app._balls()[3])
        page.screenshot(path=os.path.join(args.out, "playfield_ball_served.png"))
        page.keyboard.press("KeyF")                 # Plunge
        time.sleep(3)
        print("after Plunge:", app._balls()[3])
        for key in "ASZXQWGEOPMR":                  # playfield switches by letter
            page.keyboard.down("Key" + key)
            time.sleep(0.15)
            page.keyboard.up("Key" + key)
            time.sleep(0.35)
        time.sleep(2)
        page.screenshot(path=os.path.join(args.out, "playfield_playing.png"))
        page.keyboard.press("KeyD")                 # Drain
        time.sleep(2)
        print("after Drain:", app._balls()[3])
        print("notes:", app.note)
        b.close()
    app.stopping = True
    rig.close()
    host.stop()
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
