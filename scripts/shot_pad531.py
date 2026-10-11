"""PAD-531 proof shots: which look of a switchable part a layer belongs to.

    python scripts/shot_pad531.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project, opens the Planet X map (scene
eae3e084: Power, Tanks and Bridge icons, each a sprite with a Loop, a Select and a Destroyed
look the game's code picks) and takes, under the same names before and after:

- scenes_look_layer.png  The Bridge's Destroyed picture selected, as DragonRR had it: the
                         preview, the Selected panel and the Layers.  After: Layers names the
                         look each row belongs to, and the Selected panel says which look of
                         which part shows it, with a button that shows that look.
- scenes_look_shown.png  (after only) that button pressed: the Bridge shows its Destroyed look.

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

MAP = "/godzilla_le/assets/lcd/auto_loaded/eae3e0844950ec5f071bf3c4e951fbff709a2028"


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad531-")
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

    def shot(page, name):
        page.mouse.move(5, 1750)
        settle(page)
        a = page.locator(".tree-canvas").first.bounding_box()
        b = page.locator(".tree-side").first.bounding_box()
        c = page.locator(".tree-layers").first.bounding_box()
        boxes = [a, b, c]
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
            for l in layers:
                print("  " * l["depth"], l["id"], l["name"], l["kind"], "drawn", l["drawn"],
                      "look", l.get("look"), flush=True)
            # the Bridge's Destroyed picture: the 216 x 216 bitmap inside IconBridge_Instance
            bridge = next(l["id"] for l in layers if l["name"] == "IconBridge_Instance")
            dead = next(l["id"] for l in layers
                        if l["parent"] == bridge and l["name"] == "unnamed_instance_5")
            api("text_scenes.tree_select", dead)
            time.sleep(4)
            print("props:", {k: v for k, v in (tv().get("props") or {}).items()
                             if k in ("name", "kind", "peek", "look")}, flush=True)
            # the Layers scrolled to the Bridge's rows
            page.locator(f'.tree-layers [data-node="{dead}"]').first.scroll_into_view_if_needed()
            shot(page, "scenes_look_layer.png")
            if after:
                page.locator(".tree-look button").first.click()
                time.sleep(4)
                print("states:", [(s["name"], s["value"]) for s in tv().get("states") or []],
                      flush=True)
                shot(page, "scenes_look_shown.png")
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
