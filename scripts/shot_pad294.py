"""PAD-294 proof shots: a click outside the scene picture drops the selection, and the Scenes
tab comes back with nothing selected.

    python scripts/shot_pad294.py <repo> <project copy> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project copy>, opens Scenes on
Godzilla's KAIJU BATTLE SELECT, selects a picture and writes:

- <prefix>_outside.png   after a click on the empty stage beside the picture
- <prefix>_return.png    a picture selected, then the Images tab and back to Scenes
- <prefix>_notes.txt     what was selected at each step
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    edits = os.path.join(project, "images", "scene_textures", "scene_edits.json")
    if os.path.isfile(edits):
        os.remove(edits)
    scratch = tempfile.mkdtemp(prefix="pad294-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    sel = lambda: (state()["text_scenes"].get("tree_view") or {}).get("sels")  # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = ["repo " + repo]
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
            rail = page.locator(".rail")
            rail.get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", rig.BATTLE)
            rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                      state()["text_scenes"].get("frames"), 90)
            time.sleep(1.5)
            idle = lambda: rig._wait(                      # noqa: E731
                lambda: not state()["text_scenes"].get("tree_busy"), 60)
            notes.append("on open: %s" % sel())
            hits = state()["text_scenes"]["tree_view"]["hits"]
            pick = [h for h in hits if "ebirah" in h["name"].lower()] or hits[-1:]
            node = pick[0]["id"]
            notes.append("picking %s (%s)" % (pick[0]["name"], node))

            def select():
                api("text_scenes.tree_select", node)
                time.sleep(0.5)
                idle()
                time.sleep(1.0)
                notes.append("selected: %s" % sel())

            # 1: a click on the stage beside the picture
            select()
            stage = page.locator(".scenes-stage").bounding_box()
            canvas = page.locator(".tree-canvas").bounding_box()
            if canvas["x"] - stage["x"] > 20:
                x, y = stage["x"] + 10, stage["y"] + stage["height"] / 2
            else:
                x, y = stage["x"] + stage["width"] / 2, stage["y"] + stage["height"] - 5
                if y <= canvas["y"] + canvas["height"]:
                    stagebar = page.locator(".scenes-stagebar .grow").first.bounding_box()
                    x, y = stagebar["x"] + 5, stagebar["y"] + stagebar["height"] / 2
            notes.append("stage %s canvas %s click at %d,%d" % (stage, canvas, x, y))
            page.mouse.click(x, y)
            time.sleep(1.0)
            idle()
            time.sleep(1.0)
            notes.append("after the outside click: %s" % sel())
            page.mouse.move(5, 995)
            page.screenshot(path=os.path.join(out, "%s_outside.png" % prefix))

            # 2: another tab and back
            select()
            rail.get_by_text("Images", exact=True).first.click()
            time.sleep(1.5)
            rail.get_by_text("Scenes", exact=True).first.click()
            time.sleep(1.0)
            idle()
            time.sleep(1.5)
            notes.append("back on Scenes: %s" % sel())
            page.mouse.move(5, 995)
            page.screenshot(path=os.path.join(out, "%s_return.png" % prefix))
            notes.append("page errors: %s" % errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        if os.path.isfile(edits):
            os.remove(edits)
    with open(os.path.join(out, prefix + "_notes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    print("\n".join(notes))
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
