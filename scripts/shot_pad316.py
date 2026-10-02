"""PAD-316 capture: the Emulate Spooky tab, idle (what it says it runs) and
optionally running a game from an update file.

    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad316.py --out <dir>
        --prefix before_ [--file <update>] [--name <screen>]

Run it from the checkout whose app code you want (main's export for the
before shots).  The server runs against a scratch settings folder with the
rig switched ON, on rig slot --slot, hidden and muted (PAD_HIDDEN=1), with
PAD_SPOOKY_EMU_DIR pointing at this checkout's tools/spooky_emu (or --rig).
--runtime0 sets PAD_RUNTIME=0 (the rig runs in the default distro).

Shoots <prefix>emulate_spooky.png with the tab idle; with --file, sets it,
presses Start, waits for the start to end and shoots <prefix><name>.png,
then Stops.
"""
import argparse
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import webui_shot as ws  # noqa: E402

NS = "emulate_spooky"


def wait_idle(url):
    for _ in range(60):
        st = ws.state(url).get(NS) or {}
        if st.get("state_label") not in (None, "Checking…"):
            return st
        time.sleep(1)
    return st


def shoot(args):
    scratch = tempfile.mkdtemp(prefix="padshot316-")
    env = {"PAD_UI_NO_RIG": "0", "PAD_SLOT": str(args.slot),
           "PAD_LABEL": "PAD-316", "PAD_HIDDEN": "1",
           "PAD_SPOOKY_EMU_DIR": args.rig or os.path.join(REPO, "tools",
                                                          "spooky_emu")}
    if args.runtime0:
        env["PAD_RUNTIME"] = "0"
    if os.environ.get("APPDATA"):
        env["PYTHONUSERBASE"] = os.path.join(os.environ["APPDATA"], "Python")
    proc, url = ws.start_server("", scratch, extra_env=env)
    from playwright.sync_api import sync_playwright
    errors = []
    result = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": args.width,
                                              "height": args.height})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            for _ in range(480):
                if "spooky" in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                    break
                time.sleep(0.5)
            ws.api(url, "ui.pick_manufacturer", "spooky")
            ws.api(url, "ui.select_tab", NS)
            st = wait_idle(url)
            print("rig_ok:", st.get("rig_ok"), "supported:", st.get("supported"))
            time.sleep(2)
            page.screenshot(path=os.path.join(args.out,
                                              args.prefix + "emulate_spooky.png"))
            if args.file:
                ws.api(url, "ui.set", NS, "file", args.file)
                time.sleep(1)
                ws.api(url, NS + ".toggle")
                t0 = time.time()
                time.sleep(3)
                while time.time() - t0 < 1500:
                    st = ws.state(url).get(NS) or {}
                    if not st.get("busy") and not st.get("starting"):
                        break
                    time.sleep(2)
                time.sleep(4)
                st = ws.state(url).get(NS) or {}
                result = (st.get("state_label"), st.get("state_hint"),
                          [c["value"] for c in st.get("cells", [])],
                          round(time.time() - t0))
                print("->", result)
                page.screenshot(path=os.path.join(
                    args.out, "%s%s.png" % (args.prefix, args.name)))
                if st.get("up"):
                    ws.api(url, NS + ".toggle")          # Stop
                    for _ in range(60):
                        st = ws.state(url).get(NS) or {}
                        if not st.get("busy") and not st.get("up"):
                            break
                        time.sleep(2)
                    print("stopped:", not st.get("up"))
            browser.close()
    finally:
        proc.terminate()
    return errors, result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="after_")
    ap.add_argument("--rig", default="")
    ap.add_argument("--file", default="")
    ap.add_argument("--name", default="emulate_spooky_running")
    ap.add_argument("--slot", default="7")
    ap.add_argument("--runtime0", action="store_true")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    errors, result = shoot(args)
    print("result:", result)
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
