"""PAD-540 proof shots: the edits line opens a list of the edits (DragonRR).

    python scripts/shot_pad540.py <repo> <godzilla LE project> <out_dir> [--after]

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one, its scene edits are dropped), makes an edit on one scene and three on KAIJU BATTLE
SELECT, then clicks "3 edits, not written yet" under the preview.  Under the same name before
and after:

- edits_list.png  The page after that click.  Before: nothing happens (it is only words).
                  After: the scene list makes way for the Edits list, every scene's edits
                  by scene, each with Reset.

After only, it also clicks the other scene's edit in the list and logs what is selected,
then Resets it and Undoes that, logging the edit counts.
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


def main():
    repo, source, out_dir = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad540-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json", "scene_edits_carried.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    print("serving", repo, flush=True)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    from playwright.sync_api import sync_playwright

    def settle():
        rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
        rig._wait(lambda: not state().get("tree_busy"), 60)

    def drawn(kind):
        return [l for l in state()["tree_view"]["layers"] if l["drawn"] and l["kind"] == kind]

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
            rig._wait(lambda: state().get("alive") and state().get("scenes"), 60)
            other = None
            for row in state()["scenes"]:
                if row["d"] == SCENE or not api("text_scenes.select", row["d"]):
                    continue
                time.sleep(1)
                if state().get("tree_view") and state()["tree_view"]["card"]:
                    settle()
                    pics = drawn("Bitmap")
                    if pics:
                        other = (row["d"], pics[0])
                        break
            print("other scene:", other and (other[0], other[1]["name"]), flush=True)
            assert api("text_scenes.tree_move", other[1]["id"], 40, 0)
            settle()
            assert api("text_scenes.select", SCENE)
            settle()
            pics, lines = drawn("Bitmap"), drawn("Text")
            assert api("text_scenes.tree_move", pics[0]["id"], 12, -8)
            settle()
            assert api("text_scenes.tree_tint", pics[1]["id"], "#ff8040", 100)
            settle()
            assert api("text_scenes.tree_visible", lines[0]["id"], False)
            settle()
            api("text_scenes.tree_select", None)
            settle()
            print("edits here:", state()["tree_view"]["edits"],
                  "all:", state()["tree_view"]["all_edits"], flush=True)
            page.mouse.move(5, 995)
            time.sleep(2)
            line = page.locator(".scenes-stagebar", has_text="not written yet")
            line.get_by_text("not written yet").first.click()
            time.sleep(3)
            page.mouse.move(5, 995)
            time.sleep(1)
            page.screenshot(path=out("edits_list.png"))
            if after:
                rows = state().get("edit_list") or []
                print("list:", [(g["label"], [(e["name"], e["what"]) for e in g["edits"]])
                                for g in rows], flush=True)
                page.locator(".sc-edit-row", has_text=other[1]["name"]).first.click()
                time.sleep(3)
                settle()
                print("picked: scene", state()["sel"] == other[0],
                      "node", state()["tree_view"]["sel"] == other[1]["id"], flush=True)
                n = state()["tree_view"]["all_edits"]
                page.locator(".sc-edit-row", has_text=other[1]["name"]).first.locator(
                    "button", has_text="Reset").click()
                time.sleep(3)
                settle()
                print("reset: all edits", n, "->", state()["tree_view"]["all_edits"], flush=True)
                page.screenshot(path=os.path.join(out_dir, "after_reset_probe.png"))
                assert api("text_scenes.tree_undo")
                settle()
                print("undo: all edits ->", state()["tree_view"]["all_edits"], flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
