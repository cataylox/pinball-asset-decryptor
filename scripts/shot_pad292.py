"""PAD-292 capture: the American Pinball Emulate tab, and its switch window,
against a LIVE rig - plus the "before" of the tab (main has none).  A copy of
scripts/shot_pad263.py (Dutch Pinball's).

Start a game first (hidden, in the app's Linux, slot 0 - the app's slot):
    wsl -d PAD-Runtime -u root -- env PAD_VISIBLE=0 PAD_TITLE="Legends of Valhalla" bash tools/ap_emu/watch.sh <game.pkg>
then
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad292.py --out <dir> [--prefix after_]
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad292.py --out <dir> --tab-only --prefix before_

The server runs against a scratch settings folder with the rig switched ON,
so the tab polls the real status.sh.  <prefix>emulate.png is American
Pinball's page with the Emulate tab picked when the app has one (else the
page the app opens into).  Unless --tab-only: <prefix>switches.png is the
switch window (served headless exactly as appf.py serves it) after coins,
Start and a plunge on it, with a playfield switch held, and <prefix>game.png
is the game's own window (tools/ap_emu/shot.sh) after those presses.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import webui_shot as ws  # noqa: E402

DISTRO = "PAD-Runtime"
NS = "emulate_ap"


def wsl_root(*cmd):
    return subprocess.run(["wsl.exe", "-d", DISTRO, "-u", "root", "--"] + list(cmd),
                          capture_output=True, text=True, timeout=120)


def ws_path(p):
    p = p.replace("\\", "/")
    return "/mnt/" + p[0].lower() + p[2:] if len(p) > 1 and p[1] == ":" else p


def tab_shot(out, prefix, width, height, cache=False):
    scratch = tempfile.mkdtemp(prefix="padshot292-")
    proc, url = ws.start_server("", scratch, extra_env={"PAD_UI_NO_RIG": "0"})
    from playwright.sync_api import sync_playwright
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            # the manufacturers arrive as their plugins load, after the page
            for _ in range(120):
                if "ap" in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                    break
                time.sleep(0.5)
            ws.api(url, "ui.pick_manufacturer", "ap")
            tabs = {t["ns"]: t for t in ws.state(url)["shell"]["tabs"]}
            has = NS in tabs and tabs[NS]["visible"]
            print("REPO", REPO, "- Emulate AP tab:", has)
            if has:
                ws.api(url, "ui.select_tab", NS)
                for _ in range(60):
                    if (ws.state(url).get(NS) or {}).get("up"):
                        break
                    time.sleep(1)
            time.sleep(3)
            page.screenshot(path=os.path.join(out, prefix + "emulate.png"))
            if has and cache:
                # the Cache window, against the real rig's cache.sh --list
                ws.api(url, NS + ".open_cache")
                for _ in range(120):
                    c = (ws.state(url).get(NS) or {}).get("cache") or {}
                    if c and not c.get("busy"):
                        break
                    time.sleep(0.5)
                ws.api(url, NS + ".cache_select", ["lov_26.08.22"])
                time.sleep(1.5)
                page.screenshot(path=os.path.join(out, prefix + "cache.png"))
                print("cache:", ws.state(url)[NS]["cache"].get("head"))
            if has:
                st = ws.state(url)[NS]
                print("state:", st.get("state_label"), st.get("state_hint"))
                print("cells:", {c["label"]: c["value"] for c in st.get("cells", [])})
            browser.close()
    finally:
        proc.terminate()
    return errors


def switch_shots(out, prefix, slot, playfield_key):
    """The virtual playfield (the Stern page, served by appf.py) against the
    live game: coins and Start on their key-panel rows, Plunge, then a
    playfield switch held on its key while the window is captured."""
    sys.path.insert(0, os.path.join(REPO, "tools", "ap_emu"))
    import appf  # noqa: E402
    table_unc = r"\\wsl.localhost\%s\var\tmp\pad_ap\rig%s\switches.json" % (DISTRO, slot)
    with open(table_unc, encoding="utf-8") as f:
        table = json.load(f)
    rig = appf.Rig(DISTRO, slot)
    # a scratch Volume / Mute file: the status bar shows VOL as in the app
    ctl = os.path.join(tempfile.mkdtemp(prefix="padshot292-"), "audio_ctl.json")
    with open(ctl, "w") as f:
        json.dump({"gain": 0.47, "muted": False}, f)
    app = appf.App(table, rig, appf.win_path(table.get("art") or "", DISTRO),
                   table.get("title") or "American Pinball", slot=slot, audio_ctl=ctl)
    host = appf.pfweb.WebHost(appf.PAGE_DIR, app)
    app.host = host
    host.start()
    threading.Thread(target=app.poll, daemon=True).start()
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_page(viewport={"width": 1000, "height": 980})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(host.url())
        page.wait_for_selector(".kp-row")
        time.sleep(2)
        for _ in range(4):
            page.keyboard.press("5")
            time.sleep(0.5)
        time.sleep(4)
        page.keyboard.press("1")
        time.sleep(6)
        page.locator(".btn", has_text="Plunge").first.click()
        time.sleep(3)
        page.keyboard.down(playfield_key)
        time.sleep(0.8)
        page.screenshot(path=os.path.join(out, prefix + "switches.png"))
        page.keyboard.up(playfield_key)
        time.sleep(2)
        print("status:", app._status())
        b.close()
    app.stopping = True
    rig.close()
    host.stop()
    r = wsl_root("env", "PAD_SLOT=%s" % slot, "bash",
                 "%s/tools/ap_emu/shot.sh" % ws_path(REPO),
                 "%s/%sgame.png" % (ws_path(out), prefix))
    print("game shot:", r.stdout.strip(), r.stderr.strip())
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="after_")
    ap.add_argument("--tab-only", action="store_true")
    ap.add_argument("--cache", action="store_true",
                    help="also shoot the Cache window (<prefix>cache.png)")
    ap.add_argument("--slot", default="0")
    ap.add_argument("--switch", default="a",
                    help="the key of a playfield switch to hold for the shot")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    errors = tab_shot(args.out, args.prefix, args.width, args.height, args.cache)
    if not args.tab_only:
        errors += switch_shots(args.out, args.prefix, args.slot, args.switch)
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
