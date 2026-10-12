"""PAD-534 proof shots: a picture the game draws turned.

    python scripts/shot_pad534.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project and takes, under the same names
before and after:

- scenes_turned.png  The Planet X map (scene 34856963) with the bridge's pointer selected, as
                     DragonRR had it: a south-pointing picture the game draws turned 48
                     degrees, while Turn reads 0.  After: the Selected panel says the game
                     draws it turned 48 degrees clockwise.
- images_turned.png  That picture on the Images tab.  After: the preview names the scene it is
                     in and how the game turns it there.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

MAP = "/godzilla_le/assets/lcd/auto_loaded/34856963ab6044d7ca3e1d26b71f70996b2b3ca1"
PIC = "images/scene_textures/radimg_unnamed_instance_1_52x72_e5086fb6.png"


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad534-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tv = lambda: (state().get("text_scenes") or {}).get("tree_view") or {}  # noqa: E731
    from playwright.sync_api import sync_playwright

    def settle(page, wait=1.5):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                               # noqa: BLE001
            print("toasts still up", flush=True)
        time.sleep(wait)

    def shot(page, name, sels):
        page.mouse.move(5, 1750)
        settle(page)
        boxes = [page.locator(s).first.bounding_box() for s in sels]
        x0 = min(r["x"] for r in boxes) - 12
        y0 = min(r["y"] for r in boxes) - 12
        x1 = max(r["x"] + r["width"] for r in boxes) + 12
        y1 = max(r["y"] + r["height"] for r in boxes) + 12
        page.screenshot(path=out(name), clip={"x": x0, "y": y0, "width": x1 - x0,
                                              "height": y1 - y0})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1800})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open', '0');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", MAP + "/scene.radium") or api("text_scenes.select", MAP)
            time.sleep(10)
            page.locator("button", has_text="Hide list").first.click()
            time.sleep(2)
            layers = tv().get("layers") or []
            bridge = next(l["id"] for l in layers if l["name"] == "IconBridge_Instance")
            ptr = next(l["id"] for l in layers
                       if l["parent"] == bridge and l["name"] == "unnamed_instance_2")
            api("text_scenes.tree_select", ptr)
            time.sleep(4)
            print("props:", {k: v for k, v in (tv().get("props") or {}).items()
                             if k in ("name", "rotate", "game_turn", "pic")}, flush=True)
            shot(page, "scenes_turned.png", [".tree-canvas", ".tree-side"])

            api("text_scenes.close")
            time.sleep(2)
            api("ui.select_tab", "images")
            time.sleep(2)
            api("images.select", PIC)
            end = time.time() + 30
            while time.time() < end:
                pv = (state().get("images") or {}).get("preview") or {}
                if not after or "where" in (pv.get("scenes") or ""):
                    break
                time.sleep(0.5)
            time.sleep(3)
            print("preview scenes:", ((state().get("images") or {}).get("preview") or {})
                  .get("scenes"), flush=True)
            shot(page, "images_turned.png", [".img-prev"])
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))
    print("scratch", scratch)


if __name__ == "__main__":
    main()
