"""PAD-228 proof shot: the Modes tab's Mode page with a multiball mode open, where
the Multiball section is (on a tree that has it, its new "Balls come" choice set to
the Action button).

    python scripts/shot_pad228.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of the
commit before it for the "before" shot).  Writes <out_dir>/<prefix>_modes_mode_page.png.
A scratch Godzilla Pro 1.15 card project holds one multiball mode whose balls come on
the Action button (a tree without the field keeps it as an unknown key).  The Modes
tab is a preview feature: the settings copy carries only the preview code from
David's real settings.
"""

import json
import os
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


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad228-")
    project = os.path.join(scratch, "GZ 1.15 Pro Extract")
    os.makedirs(project)
    card = "godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    spec = MP.ModeSpec(name="MEGA MULTIBALL", title=MP.GODZILLA_PRO_1_15.key, seconds=10,
                       multiball=True, balls=3, ball_save=15)
    slug, _ = MP.new_mode(project, spec=spec)
    path = os.path.join(project, "modes", slug, "mode.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    d["multiball_on_shot"] = "Action button"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes", [])
    launcher = os.path.join(scratch, "launch228.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": codes,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
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
            form = st.get("form", {})
            print("form multiball:", form.get("multiball"), "mb_on_shot:", form.get("mb_on_shot"),
                  "dis:", {k: v for k, v in (st.get("dis") or {}).items() if k == "multiball"},
                  "status:", st.get("status"), flush=True)
            # the Multiball section sits below the fold of the Mode page's own scroller
            page.get_by_text("Balls in play", exact=True).first.evaluate(
                "e => e.scrollIntoView({block: 'center'})")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_modes_mode_page.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, os.path.getsize(out), flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
