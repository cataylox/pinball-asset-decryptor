"""PAD-535 round 2 proof shots: layers an earlier Write hid, in a project extracted from that card.

    python scripts/shot_pad535_baked.py <repo> <godzilla LE project> <out_dir> [--after]

Copies the project's images/ and text/ to a scratch folder (its scene edits dropped) and gives
KAIJU BATTLE SELECT's two Ebirah text lines (Ebirah_Textbox_instance, unnamed_instance_26)
the never-shown keyframes a Write leaves on the card when it hides them: DragonRR's project,
extracted from a card he had written that way.  Takes, under the same names before and after:

- baked_layers.png    Layers with EbirahFullBody_instance selected.  Before: the two lines
                      greyed out with a green tick, no edit, no way to tell.  After: struck
                      through with a red stop sign, as any layer hidden in the game.
- baked_put_back.png  The preview and Layers after clicking the first line's mark.  Before:
                      a hide edit is added and nothing changes.  After: the line is back.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402
from shot_pad339_scenes import SCENE  # noqa: E402

LINES = ("Ebirah_Textbox_instance", "unnamed_instance_26")
GROUP = "EbirahFullBody_instance"


def _hide_in_scene(project, repo):
    """The two lines as a project extracted from a card Write hid them on has them."""
    sys.path.insert(0, repo)
    from pinball_decryptor.webui.text_scenes_tree import _walk_man
    path = os.path.join(project, "images", "scene_textures", "scene_tree.json")
    with open(path, encoding="utf-8") as f:
        trees = json.load(f)
    man = trees[[k for k in trees if SCENE.rsplit("/", 1)[-1] in k][0]]
    group = [n for n, _p, _d in _walk_man(man) if n["name"] == GROUP][0]
    done = []
    for n, p, _d in _walk_man(man):
        if p is group and n["name"] in LINES:
            n["kf"] = [[1, 0]]
            done.append(n["id"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trees, f)
    return done


def main():
    repo, source, out_dir = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad535b-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    ids = _hide_in_scene(project, repo)
    print("serving", repo, "hidden in the scene:", ids, flush=True)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1400})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state().get("alive"), 30)
            assert api("text_scenes.select", SCENE)
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            layers = state()["tree_view"]["layers"]
            group = [l for l in layers if l["name"] == GROUP][0]
            assert api("text_scenes.tree_select", group["id"])
            time.sleep(3)
            row = page.locator('.tree-layers [data-node="%s"]' % ids[0])
            row.evaluate("el => el.scrollIntoView({block: 'center'})")
            page.mouse.move(5, 1395)
            time.sleep(3)
            got = {l["id"]: l for l in state()["tree_view"]["layers"]}
            print("before click:", [(got[i]["name"], got[i]["hidden"], got[i]["drawn"])
                                    for i in ids], flush=True)
            page.locator(".tree-layers").first.screenshot(path=out("baked_layers.png"))

            mark = row.locator(".ly-ingame")
            mark.click(no_wait_after=True)
            time.sleep(2)
            if page.locator(".modal").count():               # the first-hide warning
                page.locator(".modal button", has_text="Hide in the game").first.click()
            rig._wait(lambda: not state().get("tree_busy"), 60)
            time.sleep(4)
            page.mouse.move(5, 1395)
            time.sleep(1)
            got = {l["id"]: l for l in state()["tree_view"]["layers"]}
            print("after click:", [(got[i]["name"], got[i]["hidden"]) for i in ids],
                  "edits:", state()["tree_view"].get("edits"), flush=True)
            boxes = [page.locator(s).first.bounding_box() for s in (".tree-canvas", ".tree-side")]
            x0 = min(b["x"] for b in boxes) - 8
            y0 = min(b["y"] for b in boxes) - 8
            x1 = max(b["x"] + b["width"] for b in boxes) + 8
            y1 = max(b["y"] + b["height"] for b in boxes) + 8
            page.screenshot(path=out("baked_put_back.png"),
                            clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
