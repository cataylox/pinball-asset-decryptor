"""PAD-251 proof shots: the Scenes window moves and resizes a scene PICTURE.

    python scripts/shot_pad251.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of
the commit before it for the "before" shots).  Serves David's saved Stern
project (a stock Godzilla LE 1.16 extract with previews) on a COPY of the
settings, opens the Scenes window on KAIJU BATTLE SELECT and writes:

- <prefix>_menu.png    right-click on one of the kaiju tiles
- <prefix>_resize.png  the same scene; on the branch, Size… at 200 % live
                       in the preview (nothing is written: the
                       editor is left open, never applied)
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

SCENE = ("/godzilla_le/assets/lcd/auto_loaded/"
         "cac32730af42b9d26d26c4bb6e667b07da53113e")
PIC = "scene_textures/radimg_unnamed_instance_23_220x234_753053a4.png"
ROW = "img::images/" + PIC


def _serve(repo, scratch):
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        stern = json.load(f)["manufacturers"]["stern"]
    project = stern["write_assets"]
    launcher = os.path.join(scratch, "launch251.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": stern.get("extract_input", ""),
                       "extract_output": project,
                       "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def main():
    repo, out, prefix = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad251-")
    proc, url = _serve(repo, scratch)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); }"
                " catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            api("ui.pick_manufacturer", "stern")
            api("ui.select_tab", "images")
            time.sleep(3)
            assert api("images.open_scenes")
            time.sleep(2)
            assert api("text_scenes.select", SCENE)
            api("text_scenes.select_item", ROW)
            time.sleep(4)
            row = page.locator('[data-id="%s"]' % ROW)
            row.scroll_into_view_if_needed()
            row.click(button="right")
            time.sleep(1)
            page.screenshot(path=os.path.join(out, prefix + "_menu.png"))
            page.keyboard.press("Escape")
            time.sleep(0.5)
            key = "picture:" + PIC
            # the base has no picture layout: its layout_start would raise a
            # modal message box and stall the call, so it is not asked
            dlg = (api("text_scenes.layout_start", key, "size")
                   if prefix != "before" else None)
            if dlg:
                # let the editor's own first readout land before typing, or
                # it overwrites the one for the typed size
                time.sleep(2)
                page.fill("#ly-size", "200")
                time.sleep(4)
            page.screenshot(path=os.path.join(out, prefix + "_resize.png"))
            if dlg:
                api("text_scenes.layout_done", None)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
