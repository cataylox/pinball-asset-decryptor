"""PAD-257 capture: the Emulate BoF tab against a LIVE rig.

Start the game first (hidden, in the app's Linux):
    wsl -d PAD-Runtime -u root -- bash tools/bof_emu/run_game.sh <binary> tools/bof_emu/profiles/dune.json --detach
then
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad257.py --out C:\\tmp\\PAD-257\\ui
The server runs against a scratch settings folder with the rig switched ON
(the usual captures switch it off), so the tab polls the real status.sh; the
script then presses Start on the page and captures before and after.
"""
import argparse
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import webui_shot as ws  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1000)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="padshot257-")
    proc, url = ws.start_server("", scratch, extra_env={"PAD_UI_NO_RIG": "0"})
    from playwright.sync_api import sync_playwright
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": args.width,
                                              "height": args.height})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.on("console", lambda m: errors.append(m.text)
                    if m.type == "error" else None)
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            ws.api(url, "ui.pick_manufacturer", "bof")
            ws.api(url, "ui.select_tab", "emulate_bof")
            # wait for the poll to see the running game and build the panel
            for _ in range(60):
                if (ws.state(url).get("emulate_bof") or {}).get("panel"):
                    break
                time.sleep(1)
            time.sleep(2)
            page.screenshot(path=os.path.join(args.out, "running.png"))
            # press Start on the page, as a user would
            page.locator(".bof-quick button.bof-sw",
                         has_text="Start").first.click()
            time.sleep(8)
            page.screenshot(path=os.path.join(args.out, "after_start.png"))
            page.keyboard.down("z")
            time.sleep(0.4)
            page.keyboard.up("z")
            time.sleep(3)
            page.screenshot(path=os.path.join(args.out, "after_flip.png"))
            st = ws.state(url)["emulate_bof"]
            print("state:", st.get("state_label"), st.get("cells"))
            browser.close()
    finally:
        proc.terminate()
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
