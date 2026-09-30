"""PAD-271 capture: the Pinball Brothers Emulate tab and its switch window
against a LIVE rig - plus the "before" of the tab (main has none).

Start a game first (hidden and muted, in the app's Linux, slot 0 - the one
the tab polls):
    wsl -d PAD-Runtime -u root -- env PAD_VISIBLE=0 bash tools/pb_emu/watch.sh <pbpp_predator_game_1_0_1.upd>
then
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad271.py --out <dir> [--prefix after_]
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad271.py --out <dir> --tab-only --prefix before_

The server runs against a scratch settings folder with the rig switched ON,
so the tab polls the real status.sh.  <prefix>emulate.png is Pinball
Brothers' page with the Emulate tab picked when the app has one (else the
page the app opens into).  Unless --tab-only: <prefix>switches.png is the
switch window (served headless exactly as pbpf.py serves it) after a coin,
Start, the launch button and some playfield switches, and <prefix>game.png
the game's own screen (tools/pb_emu/shot.sh) after those presses.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import webui_shot as ws  # noqa: E402

DISTRO = "PAD-Runtime"


def wsl_root(*cmd):
    return subprocess.run(["wsl.exe", "-d", DISTRO, "-u", "root", "--"] + list(cmd),
                          capture_output=True, text=True, timeout=120)


def proc_state(slot):
    """The state letter of this slot's pinprog (T = stopped), read in WSL
    from a script file: a bash -c line through wsl.exe loses its quoting."""
    sh = os.path.join(tempfile.gettempdir(), "pad271_state.sh")
    with open(sh, "w", newline="\n") as f:
        f.write("p=$(cat /var/tmp/pad_pb/rig%s/game.pid)\n"
                "echo pinprog $p state $(cut -d' ' -f3 /proc/$p/stat)\n" % slot)
    return wsl_root("bash", ws_path(sh)).stdout.strip()


def ws_path(p):
    p = p.replace("\\", "/")
    return "/mnt/" + p[0].lower() + p[2:] if len(p) > 1 and p[1] == ":" else p


def tab_shot(out, prefix, width, height, upd):
    scratch = tempfile.mkdtemp(prefix="padshot271-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "pb_emulate_file": upd}, f)
    proc, url = ws.start_server(settings, scratch, extra_env={"PAD_UI_NO_RIG": "0"})
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
                if "pb" in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                    break
                time.sleep(0.5)
            ws.api(url, "ui.pick_manufacturer", "pb")
            time.sleep(2)
            tabs = {t["ns"]: t for t in ws.state(url)["shell"]["tabs"]}
            has = "emulate_pb" in tabs and tabs["emulate_pb"]["visible"]
            print("REPO", REPO, "- Emulate PB tab:", has)
            print("Play group:", [t["label"] for t in tabs.values()
                                  if t.get("visible") and t.get("group") == "Play"])
            if has:
                ws.api(url, "ui.select_tab", "emulate_pb")
                for _ in range(60):
                    if (ws.state(url).get("emulate_pb") or {}).get("up"):
                        break
                    time.sleep(1)
            time.sleep(3)
            page.screenshot(path=os.path.join(out, prefix + "emulate.png"))
            if has:
                st = ws.state(url)["emulate_pb"]
                print("state:", st.get("state_label"), st.get("state_hint"))
                print("cells:", {c["label"]: c["value"] for c in st.get("cells", [])})
                print("setup notice:", st.get("setup_msg") or "none")
            browser.close()
    finally:
        proc.terminate()
    return errors


def switch_shots(out, prefix, slot):
    sys.path.insert(0, os.path.join(REPO, "tools", "pb_emu"))
    import pbpf  # noqa: E402
    table_unc = "\\\\wsl.localhost\\%s\\var\\tmp\\pad_pb\\rig%s\\switches.json" % (DISTRO, slot)
    with open(table_unc, encoding="utf-8") as f:
        table = json.load(f)
    app, rig, host = pbpf.serve(table, DISTRO, slot)
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_page(viewport={"width": 1000, "height": 980})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(host.url())
        time.sleep(4)
        print("at rest:", app._balls()[3])
        for _ in range(4):                          # 4 x COIN 2 = a credit
            page.keyboard.press("Digit5")
            time.sleep(0.4)
        time.sleep(1)
        page.keyboard.press("Digit1")               # Start
        time.sleep(6)
        print("after Start:", app._balls()[3])
        page.keyboard.down("Space")                 # the launch button
        time.sleep(0.3)
        page.keyboard.up("Space")
        time.sleep(3)
        print("after Launch:", app._balls()[3])
        for key in "ASZXQWGE":                      # playfield switches by letter
            page.keyboard.down("Key" + key)
            time.sleep(0.15)
            page.keyboard.up("Key" + key)
            time.sleep(0.35)
        page.keyboard.down("KeyO")                  # one held while captured
        time.sleep(1.5)
        page.screenshot(path=os.path.join(out, prefix + "switches.png"))
        page.keyboard.up("KeyO")
        # Pause freezes the game's own processes (checked from outside)
        page.keyboard.press("F9")
        time.sleep(1)
        print("paused:", app.paused, proc_state(slot))
        page.keyboard.press("F9")
        time.sleep(1)
        print("resumed:", not app.paused, proc_state(slot))
        print("notes:", app.note)
        b.close()
    app.stopping = True
    rig.close()
    host.stop()
    r = wsl_root("env", "PAD_SLOT=%s" % slot, "bash",
                 "%s/tools/pb_emu/shot.sh" % ws_path(REPO),
                 "%s/%sgame.png" % (ws_path(out), prefix))
    print("game shot:", r.stdout.strip(), r.stderr.strip())
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="after_")
    ap.add_argument("--tab-only", action="store_true")
    ap.add_argument("--slot", default="0")
    ap.add_argument("--upd", default=r"D:\Pinball\images\Pinball Brothers\pbpp_predator_game_1_0_1.upd")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    errors = tab_shot(args.out, args.prefix, args.width, args.height, args.upd)
    if not args.tab_only:
        errors += switch_shots(args.out, args.prefix, args.slot)
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
