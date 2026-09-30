"""PAD-286 proof shots: picking a layer inside a sprite that was hidden with its eye.

    python scripts/shot_pad286.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project>, opens Scenes on Godzilla's
KAIJU BATTLE SELECT, hides TitanFullBody_instance (an edit: the project's scene_edits.json is
copied first and put back byte for byte at the end), clicks a picture inside it in the Layers
list and writes:

- <prefix>_pick.png      the page with that picture picked
- <prefix>_notes.txt     what the pick drew and the notes under the Selected panel
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

SPRITE = "TitanFullBody_instance"


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad286-")
    edits = os.path.join(project, "images", "scene_textures", "scene_edits.json")
    keep = os.path.join(scratch, "scene_edits.json.keep")
    had = os.path.isfile(edits)
    if had:
        shutil.copy2(edits, keep)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = ["repo " + repo]

    def describe(tag):
        tv = state()["text_scenes"]["tree_view"]
        names = {l["id"]: l["name"] for l in tv["layers"]}
        p = tv.get("props") or {}
        notes.append("%s: frame %s, sel %s, peek %s, hid_in %s, x %s, notes %s"
                     % (tag, tv["frame"], names.get(tv["sel"]), p.get("peek"),
                        p.get("hid_in"), p.get("x"), tv.get("notes")))
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
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", rig.BATTLE)
            rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                      state()["text_scenes"].get("frames"), 90)
            time.sleep(1.5)
            tv = state()["text_scenes"]["tree_view"]
            layers = tv["layers"]
            at = [i for i, l in enumerate(layers) if l["name"] == SPRITE][0]
            sprite = layers[at]
            kid = [l for l in layers[at + 1:]
                   if l.get("depth", 0) > sprite.get("depth", 0) and l["kind"] == "Bitmap"][0]
            assert api("text_scenes.tree_visible", sprite["id"], False)
            rig._wait(lambda: not state()["text_scenes"].get("tree_busy"), 30)
            time.sleep(1.0)
            describe("hid " + SPRITE)
            row = page.locator('.tree-layers [data-node="%d"]' % kid["id"])
            row.scroll_into_view_if_needed()
            row.locator(".ly-name").click() if row.locator(".ly-name").count() else \
                row.click(position={"x": 120, "y": 8})
            time.sleep(0.5)
            rig._wait(lambda: not state()["text_scenes"].get("tree_busy"), 30)
            time.sleep(2.0)
            page.mouse.move(5, 995)                     # no tooltip over the list
            time.sleep(0.5)
            page.screenshot(path=os.path.join(out, "%s_pick.png" % prefix))
            describe("picked %s (id %d)" % (kid["name"], kid["id"]))
            notes.append("page errors: %s" % errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        if had:
            shutil.copy2(keep, edits)
        elif os.path.isfile(edits):
            os.remove(edits)
    with open(os.path.join(out, prefix + "_notes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    print("\n".join(notes))
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
