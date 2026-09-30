"""PAD-289 proof shots: picking a layer brings it to the front whatever its eye says.

    python scripts/shot_pad289.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project>, opens Scenes on Godzilla's
KAIJU BATTLE SELECT and, with the project's scene_edits.json copied first and put back byte
for byte at the end:

- <prefix>_hidden.png   one picture of the body on screen hidden with its eye, then picked
- <prefix>_parent.png   that sprite picked (its hidden picture included, all on top)
- <prefix>_notes.txt    what each pick drew
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

SPRITE = "FullBody_instance"          # the body the picker shows at rest


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad289-")
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
        top = [names.get(h["id"]) for h in tv["hits"][-4:]]
        notes.append("%s: frame %s, sel %s, peek %s, hidden %s, top hits %s, notes %s"
                     % (tag, tv["frame"], names.get(tv["sel"]), p.get("peek"),
                        p.get("hidden"), top, tv.get("notes")))

    def settle(page):
        time.sleep(0.5)
        rig._wait(lambda: not state()["text_scenes"].get("tree_busy"), 30)
        time.sleep(2.0)
        page.mouse.move(5, 995)                         # no tooltip over the list
        time.sleep(0.5)

    def click_row(page, nid):
        row = page.locator('.tree-layers [data-node="%d"]' % nid)
        row.scroll_into_view_if_needed()
        row.click(position={"x": 120, "y": 8})
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
            layers = state()["text_scenes"]["tree_view"]["layers"]
            at = [i for i, l in enumerate(layers) if l["name"].endswith(SPRITE)
                  and l["kind"] == "Sprite" and l["drawn"]][0]
            sprite = layers[at]
            inside = []
            for l in layers[at + 1:]:
                if l.get("depth", 0) <= sprite.get("depth", 0):
                    break
                inside.append(l)
            kid = [l for l in inside if l["kind"] == "Bitmap" and l["drawn"]][0]
            notes.append("sprite %s (id %d); picture %s (id %d)"
                         % (sprite["name"], sprite["id"], kid["name"], kid["id"]))
            assert api("text_scenes.tree_visible", kid["id"], False)
            settle(page)
            describe("hid " + kid["name"])
            click_row(page, kid["id"])
            settle(page)
            page.screenshot(path=os.path.join(out, "%s_hidden.png" % prefix))
            describe("picked the hidden " + kid["name"])
            click_row(page, sprite["id"])
            settle(page)
            page.screenshot(path=os.path.join(out, "%s_parent.png" % prefix))
            describe("picked " + sprite["name"])
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
