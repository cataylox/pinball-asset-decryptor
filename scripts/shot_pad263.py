"""PAD-263 capture: the Dutch Pinball Emulate tab, and its switch window,
against a LIVE rig - plus the "before" of the tab (main has none).

Start a game first (hidden, in the app's Linux, slot 0):
    wsl -d PAD-Runtime -u root -- env PAD_VISIBLE=0 bash tools/dp_emu/watch.sh <disk.img> [update.zip]
then
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad263.py --out <dir> [--prefix after_]
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad263.py --out <dir> --tab-only --prefix before_

The server runs against a scratch settings folder with the rig switched ON,
so the tab polls the real status.sh.  <prefix>emulate.png is Dutch Pinball's
page with the Emulate tab picked when the app has one (else the page the app
opens into).  Unless --tab-only: <prefix>switches.png is the switch window
(served headless exactly as dppf.py serves it), after pressing Start and
then a playfield switch on it, and <prefix>game.png is the game's own window
(tools/dp_emu/shot.sh) after those presses.
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


def wsl_root(*cmd):
    return subprocess.run(["wsl.exe", "-d", DISTRO, "-u", "root", "--"] + list(cmd),
                          capture_output=True, text=True, timeout=120)


def tab_shot(out, prefix, width, height):
    scratch = tempfile.mkdtemp(prefix="padshot263-")
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
                if "dp" in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                    break
                time.sleep(0.5)
            ws.api(url, "ui.pick_manufacturer", "dp")
            tabs = {t["ns"]: t for t in ws.state(url)["shell"]["tabs"]}
            has = "emulate_dp" in tabs and tabs["emulate_dp"]["visible"]
            print("REPO", REPO, "- Emulate DP tab:", has)
            if has:
                ws.api(url, "ui.select_tab", "emulate_dp")
                for _ in range(60):
                    if (ws.state(url).get("emulate_dp") or {}).get("up"):
                        break
                    time.sleep(1)
            time.sleep(3)
            page.screenshot(path=os.path.join(out, prefix + "emulate.png"))
            if has:
                st = ws.state(url)["emulate_dp"]
                print("state:", st.get("state_label"), st.get("state_hint"))
                print("cells:", {c["label"]: c["value"] for c in st.get("cells", [])})
            browser.close()
    finally:
        proc.terminate()
    return errors


def switch_shots(out, prefix, slot, playfield_switch):
    sys.path.insert(0, os.path.join(REPO, "tools", "dp_emu"))
    import dppf  # noqa: E402
    table_unc = "\\\\wsl.localhost\\%s\\var\\tmp\\pad_dp\\rig%s\\switches.json" % (DISTRO, slot)
    with open(table_unc, encoding="utf-8") as f:
        table = json.load(f)
    status = wsl_root("bash", "%s/tools/dp_emu/status.sh" % ws_path(REPO)).stdout
    info = dict(l.split("=", 1) for l in status.splitlines() if "=" in l)
    title = info.get("title", "Dutch Pinball").replace(" Pinball", "")
    model = dppf.page_model(table, title)
    rig = dppf.Rig(DISTRO, slot)
    app = dppf.App(model, rig, dppf.win_path(table.get("art") or "", DISTRO))
    host = dppf.pfweb.WebHost(os.path.join(dppf.HERE, "dppage"), app)
    app.host = host
    host.start()
    threading.Thread(target=app.poll, daemon=True).start()
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_page(viewport={"width": 980, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(host.url())
        page.wait_for_selector(".row")
        time.sleep(2)
        # Start, pressed on its row the way a user would
        page.locator(".row", has_text="Start Button").first.click()
        time.sleep(8)
        # a playfield switch, held while the window is captured
        row = page.locator(".row", has_text=playfield_switch).first
        row.hover()
        page.mouse.down()
        time.sleep(0.6)
        page.screenshot(path=os.path.join(out, prefix + "switches.png"))
        page.mouse.up()
        for _ in range(2):
            time.sleep(0.8)
            row.click()
        time.sleep(3)
        print("live:", app.live)
        b.close()
    app.stopping = True
    rig.close()
    host.stop()
    r = wsl_root("env", "PAD_SLOT=%s" % slot, "bash",
                 "%s/tools/dp_emu/shot.sh" % ws_path(REPO),
                 "%s/%sgame.png" % (ws_path(out), prefix))
    print("game shot:", r.stdout.strip(), r.stderr.strip())
    return errors


def ws_path(p):
    p = p.replace("\\", "/")
    return "/mnt/" + p[0].lower() + p[2:] if len(p) > 1 and p[1] == ":" else p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="after_")
    ap.add_argument("--tab-only", action="store_true")
    ap.add_argument("--slot", default="0")
    ap.add_argument("--switch", default="Left Slingshot",
                    help="the playfield switch's title to press")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    errors = tab_shot(args.out, args.prefix, args.width, args.height)
    if not args.tab_only:
        errors += switch_shots(args.out, args.prefix, args.slot, args.switch)
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
