"""PAD-535 proof shots: in the game or hidden in it, at a glance on every Layers row.

    python scripts/shot_pad535.py <repo> <godzilla LE project> <out_dir> [--after]

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one, its scene edits are dropped), opens Scenes on KAIJU BATTLE SELECT and takes, under the
same names before and after:

- layers.png      The Layers list with Ebirah_Textbox_instance (the BIOLLANTE text DragonRR
                  hid) hidden in the game.  Before: a red card only on that row, nothing on the
                  others.  After: a red stop sign on it and a green tick on every other row.
- first_hide.png  The page after clicking that column on the picture beside it the first time.  Before:
                  hidden at once, no word.  After: the one-time warning with Don't ask again.
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
from shot_pad339_scenes import SCENE  # noqa: E402

LINE = "Ebirah_Textbox_instance"


def main():
    repo, source, out_dir = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad535-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    print("serving", repo, flush=True)
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
            line = [l for l in layers if l["name"].startswith(LINE)][0]
            pic = [l for l in layers if l["parent"] == line["parent"] and l["id"] != line["id"]][0]
            assert api("text_scenes.tree_visible", line["id"], False)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            assert api("text_scenes.tree_select", line["id"])
            time.sleep(2)
            row = page.locator('.tree-layers [data-node="%s"]' % line["id"])
            row.evaluate("el => el.scrollIntoView({block: 'center'})")
            page.mouse.move(5, 1395)
            time.sleep(3)
            got = {l["id"]: l for l in state()["tree_view"]["layers"]}
            print(LINE, "hidden in game:", got[line["id"]]["hidden"], flush=True)
            page.locator(".tree-layers").first.screenshot(path=out("layers.png"))

            prow = page.locator('.tree-layers [data-node="%s"]' % pic["id"])
            mark = prow.locator(".ly-ingame" if after else ".ly-game")
            mark.click(no_wait_after=True)
            time.sleep(3)
            page.mouse.move(5, 1395)
            time.sleep(1)
            print("dialog up:", page.locator(".modal").count(), flush=True)
            page.screenshot(path=out("first_hide.png"))
            if after and page.locator(".modal").count():
                page.locator(".modal button", has_text="Cancel").click()
                time.sleep(2)
            got = {l["id"]: l for l in state()["tree_view"]["layers"]}
            print(pic["name"], "hidden in game:", got[pic["id"]]["hidden"], flush=True)
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
