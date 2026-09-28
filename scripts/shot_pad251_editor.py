"""PAD-251 proof shots: the Scenes window's scene editor, driven like a user.

    python scripts/shot_pad251_editor.py <repo> <project copy> <out_dir> <prefix> [--edit]

Serves <repo> on a settings copy whose Stern project is <project copy> (a scratch copy: the
editor writes scene_edits.json into it), opens the Scenes window on Godzilla's KAIJU BATTLE
SELECT and writes:

- <prefix>_language.png, <prefix>_hud.png, <prefix>_battle_select.png   each scene as it opens
- with --edit: <prefix>_selected.png (the portrait clicked) and <prefix>_edited.png (dragged
  80 px left and 40 px up, enlarged from a corner, tinted)

Needs Playwright (``pip install --target C:/tmp/pad251/pw playwright``; PYTHONPATH it) and the
installed Edge.
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
BATTLE = ("/godzilla_le/assets/lcd/auto_loaded/"
          "cac32730af42b9d26d26c4bb6e667b07da53113e")
LANGUAGE = ("/godzilla_le/assets/lcd/demand_loaded/"
            "762a9b99fc0c933b6c6c4822cb48911fa92bbd97")
HUD = ("/godzilla_le/assets/lcd/auto_loaded/"
       "9d57875196c613785a1eee010c55223a0f1aa821")


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch251e.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def main():
    repo, project, out, prefix = sys.argv[1:5]
    edit = "--edit" in sys.argv
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad251e-")
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            api("ui.select_tab", "images")
            time.sleep(2)
            assert api("images.open_scenes")
            time.sleep(1)
            for scene, name in ((LANGUAGE, "language"), (HUD, "hud"), (BATTLE, "battle_select")):
                assert api("text_scenes.select", scene)
                time.sleep(6)
                page.screenshot(path=os.path.join(out, prefix + "_%s.png" % name))
            if edit:
                page.get_by_text("Hide the scene list").click()
                time.sleep(1)
                canvas = page.locator(".tree-canvas")
                box = canvas.bounding_box()
                sx = box["width"] / 1360.0
                sy = box["height"] / 768.0
                # the Ebirah portrait sits at about (650, 420) on the glass
                px, py = box["x"] + 650 * sx, box["y"] + 420 * sy
                page.mouse.click(px, py)
                time.sleep(2)
                box = canvas.bounding_box()
                sx, sy = box["width"] / 1360.0, box["height"] / 768.0
                px, py = box["x"] + 650 * sx, box["y"] + 420 * sy
                page.screenshot(path=os.path.join(out, prefix + "_selected.png"))
                page.mouse.move(px, py)
                page.mouse.down()
                page.mouse.move(px - 40 * sx, py - 20 * sy, steps=5)
                page.mouse.move(px - 80 * sx, py - 40 * sy, steps=5)
                page.mouse.up()
                time.sleep(3)
                tv = state()["text_scenes"]["tree_view"]
                p_ = tv["props"]
                box = canvas.bounding_box()           # focusing the canvas scrolls the window
                sx, sy = box["width"] / 1360.0, box["height"] / 768.0
                # a corner of the selection, dragged outwards to enlarge it
                cxp = box["x"] + (p_["x"] + p_["w"]) * sx
                cyp = box["y"] + (p_["y"] + p_["h"]) * sy
                page.mouse.move(cxp, cyp)
                page.mouse.down()
                page.mouse.move(cxp + 40 * sx, cyp + 50 * sy, steps=6)
                page.mouse.up()
                time.sleep(3)
                api("text_scenes.tree_tint", p_["id"], "#80c0ff", 100)
                time.sleep(4)
                page.screenshot(path=os.path.join(out, prefix + "_edited.png"))
                print("edits:", state()["text_scenes"]["tree_view"]["edits"])
            print("page errors:", errors)
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
