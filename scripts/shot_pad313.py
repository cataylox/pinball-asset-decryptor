"""PAD-313 capture: the Emulate PB and Emulate Spooky tabs pressing Start
with their rig in a folder whose path has a space, as every installed copy's
is (C:\\Program Files\\Pinball Asset Decryptor\\tools\\...).

    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad313.py --out <dir>
        --rigs "C:\\tmp\\PAD-313 after\\tools" --prefix after_
        --pb <pbpp_predator_game_1_0_1.upd> --spooky <vX.beetlejuice>

Run it from the checkout whose app code you want (main's export for the
before shots).  The server runs against a scratch settings folder with the
rig switched ON, on rig slot --slot, hidden and muted (PAD_HIDDEN=1), with
PAD_PB_EMU_DIR / PAD_SPOOKY_EMU_DIR pointing at --rigs.  For each maker:
pick it, open its Emulate tab, set the file, press Start, wait for the start
to end (Running, or the failure in the log), shoot <prefix>emulate_<mfr>.png,
then Stop.
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

TABS = (("pb", "emulate_pb", "pb_emu"), ("spooky", "emulate_spooky", "spooky_emu"))


def shoot(out, prefix, rigs, files, slot, width, height):
    scratch = tempfile.mkdtemp(prefix="padshot313-")
    env = {"PAD_UI_NO_RIG": "0", "PAD_SLOT": str(slot), "PAD_LABEL": "PAD-313",
           "PAD_HIDDEN": "1",
           "PAD_PB_EMU_DIR": os.path.join(rigs, "pb_emu"),
           "PAD_SPOOKY_EMU_DIR": os.path.join(rigs, "spooky_emu")}
    if os.environ.get("APPDATA"):
        env["PYTHONUSERBASE"] = os.path.join(os.environ["APPDATA"], "Python")
    proc, url = ws.start_server("", scratch, extra_env=env)
    from playwright.sync_api import sync_playwright
    errors = []
    results = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            for mfr, ns, _rig in TABS:
                if not files.get(mfr):
                    continue
                for _ in range(480):
                    if mfr in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                        break
                    time.sleep(0.5)
                ws.api(url, "ui.pick_manufacturer", mfr)
                ws.api(url, "ui.select_tab", ns)
                for _ in range(60):
                    st = ws.state(url).get(ns) or {}
                    if st.get("state_label") not in (None, "Checking…"):
                        break
                    time.sleep(1)
                print(ns, "rig_ok:", st.get("rig_ok"), "note:", st.get("note"))
                ws.api(url, "ui.set", ns, "file", files[mfr])
                time.sleep(1)
                ws.api(url, ns + ".toggle")
                # the start: busy until watch.sh returns (a few minutes at most)
                t0 = time.time()
                time.sleep(3)
                while time.time() - t0 < 900:
                    st = ws.state(url).get(ns) or {}
                    if not st.get("busy") and not st.get("starting"):
                        break
                    time.sleep(2)
                time.sleep(4)
                st = ws.state(url).get(ns) or {}
                results[mfr] = (st.get("state_label"), st.get("state_hint"),
                                round(time.time() - t0))
                print(ns, "->", results[mfr])
                page.screenshot(path=os.path.join(out, "%semulate_%s.png" % (prefix, mfr)))
                if st.get("up"):
                    ws.api(url, ns + ".toggle")          # Stop
                    for _ in range(60):
                        st = ws.state(url).get(ns) or {}
                        if not st.get("busy") and not st.get("up"):
                            break
                        time.sleep(2)
                    print(ns, "stopped:", not st.get("up"))
            browser.close()
    finally:
        proc.terminate()
    return errors, results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="after_")
    ap.add_argument("--rigs", required=True,
                    help="the folder holding pb_emu, spooky_emu, ap_emu, rigboard.sh")
    ap.add_argument("--pb", default="")
    ap.add_argument("--spooky", default="")
    ap.add_argument("--slot", default="1")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    errors, results = shoot(args.out, args.prefix, args.rigs,
                            {"pb": args.pb, "spooky": args.spooky},
                            args.slot, args.width, args.height)
    print("results:", results)
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
