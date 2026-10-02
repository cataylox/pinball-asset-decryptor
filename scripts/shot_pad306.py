"""PAD-306 proof: a mode's own screen and clip on Metallica Remastered 1.04, through Try it.

    python scripts/shot_pad306.py <repo> <out_dir> <prefix> [--rig]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of the commit
before it for the "before" shot). Writes <out_dir>/<prefix>_show.png: the Modes tab's Show
page for a scratch Metallica Remastered 1.04 project holding one mode. With --rig it then
presses Try it on David's 1.04 library card, pinned to rig slot 3 (never his own rig: no
PAD_TICKET) and muted, starts a game and the mode, and saves the guest's framebuffer before
and during the mode as <out_dir>/<prefix>_glass_*.png, counting the panel's magenta pixels.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
CARD = (r"C:\Users\david\Documents\development\pinball-asset-decryptor\images\Stern\spike2"
        r"\metallica_spike-1_04_0.Release.32G.sdcard.raw")
RIGSH = "/mnt/c/tmp/pad306_rig.sh"
SLOT = "3"


def rig(*args, timeout=120):
    r = subprocess.run(["wsl", "-d", "PAD-Runtime", "-u", "root", "--", "bash", RIGSH] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def win_to_wsl(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:])


def magenta(png):
    from PIL import Image
    im = Image.open(png).convert("RGB")
    return sum(1 for r, g, b in im.getdata() if r > 200 and b > 200 and g < 80)


def tryit_state(url):
    st = webui_shot.state(url).get("modes", {})
    return st.get("tryit") or {}, st


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    with_rig = "--rig" in sys.argv[4:]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad306-")
    project = os.path.join(scratch, "Metallica 1.04 Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "1.04"}, f)
    prof = MP.profile_for_card("metallica_spike", "1.04")
    spec = MP.blank_spec(prof, name="METAL LOOP FEST")
    spec.start_count = 1
    spec.seconds = 30
    spec.screen = True
    spec.panel_color = "#ff00ff"
    spec.clip = "title"
    spec.clip_seconds = 4.0
    slug, _ = MP.new_mode(project, spec=spec)
    print("mode", slug, "start shot", spec.start_shot, flush=True)
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes", [])
    launcher = os.path.join(scratch, "launch306.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": codes, "emulate_card": CARD,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    # a rig run is always muted: the Emulate tab hands the rig this file's level
    cfgdir = os.path.join(scratch, "cfg", "pinball_decryptor")
    os.makedirs(cfgdir, exist_ok=True)
    with open(os.path.join(cfgdir, "audio_ctl.json"), "w", encoding="utf-8") as f:
        json.dump({"gain": 0.0, "muted": True}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    if with_rig:
        tmp = os.path.join(scratch, "tmp")     # a Try it set of its own, never David's
        os.makedirs(tmp, exist_ok=True)
        env.update({"TEMP": tmp, "TMP": tmp})
        env.update({"PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "1", "PAD_SLOT": SLOT,
                    "PAD_TICKET": "", "PAD_LABEL": "PAD-306-check"})
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    print("server", url.split("?")[0], "scratch", scratch, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            st = webui_shot.state(url).get("modes", {})
            dis = st.get("dis") or {}
            print("dis screen/clip/show_order:", dis.get("screen"), dis.get("clip"),
                  dis.get("show_order"), flush=True)
            print("show_all reason:", (st.get("reasons") or {}).get("show_all"), flush=True)
            show = page.locator("text=Show").first
            try:
                show.click(timeout=5000)
                time.sleep(2)
            except Exception as e:                    # noqa: BLE001
                print("no Show tab to click:", e, flush=True)
            out = os.path.join(out_dir, "%s_show.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            if not with_rig:
                browser.close()
                return
            print("rig before:", rig("ps")[1].strip() or "(nothing running)", flush=True)
            webui_shot.api(url, "modes.tryit")
            t0, last = time.time(), None
            while time.time() - t0 < 3600:
                ts, st = tryit_state(url)
                now = (ts.get("state"), (ts.get("reason") or "")[:200])
                if now != last:
                    print("%5ds tryit %s" % (time.time() - t0, now), flush=True)
                    last = now
                if ts.get("state") in ("live", "ended", "failed"):
                    break
                time.sleep(10)
            if (ts.get("state") or "") != "live":
                return
            if "--hold" in sys.argv[4:]:
                # driven by hand: the run stays up until <out_dir>/STOP appears (40 min at most)
                stop = os.path.join(out_dir, "STOP")
                print("holding: live on slot %s; touch %s to stop" % (SLOT, stop), flush=True)
                t1 = time.time()
                while not os.path.exists(stop) and time.time() - t1 < 2400:
                    time.sleep(3)
                browser.close()
                return
            # the guest's first picture, then a game
            time.sleep(60)
            for k in ("coin", "game"):
                print(k, rig(k)[1].strip()[-200:], flush=True)
            time.sleep(25)
            rig("plunge")
            time.sleep(15)
            g = os.path.join(out_dir, "%s_glass_before_mode.png" % prefix)
            print("shot before", rig("shot", win_to_wsl(g))[1].strip()[-200:], flush=True)
            if os.path.isfile(g):
                print("  magenta before:", magenta(g), flush=True)
            webui_shot.api(url, "modes.start_now")
            for i, wait in enumerate((1.0, 1.5, 2.5, 4.0, 6.0)):
                time.sleep(wait)
                g = os.path.join(out_dir, "%s_glass_mode_%d.png" % (prefix, i))
                rig("shot", win_to_wsl(g))
                if os.path.isfile(g):
                    print("  t+%d shot %s magenta %d" % (i, os.path.basename(g), magenta(g)),
                          flush=True)
            print("mode.log tail:\n" + rig("modelog", "40")[1], flush=True)
            page.screenshot(path=os.path.join(out_dir, "%s_modes_after_run.png" % prefix))
            browser.close()
    finally:
        try:
            if with_rig:
                webui_shot.api(url, "ui.select_tab", "emulate")
                st = webui_shot.state(url).get("emulate", {})
                if st.get("up") or st.get("running"):
                    webui_shot.api(url, "emulate.toggle")
                    time.sleep(20)
        except Exception as e:                        # noqa: BLE001
            print("stop:", e, flush=True)
        proc.terminate()
        if with_rig:
            print("rig after:", rig("ps")[1].strip() or "(nothing running)", flush=True)


if __name__ == "__main__":
    main()
