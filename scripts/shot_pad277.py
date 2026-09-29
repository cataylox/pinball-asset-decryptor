"""PAD-277 proof shots: the Scenes tab with Godzilla's Credits_Text picture selected.

    python scripts/shot_pad277.py <repo> <project> <out_dir> <prefix> [--one-to-one]

Serves <repo> on a settings copy whose Stern project is <project>, opens Scenes on the HUD
scene that draws Credits_Text (a 1044 x 264 picture the game shrinks to about 477 x 119),
selects it and writes <prefix>_selected.png.  With --one-to-one it also presses "Draw 1:1"
and writes <prefix>_one_to_one.png, then puts the scene back as shipped (Undo), so the
project is left as it was.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

#: gzho's node that draws radimg_Credits_Text_1044x262 (TopPanel_Instance › unnamed_instance_8)
NODE = 2463
HUD = "/godzilla_le/assets/lcd/auto_loaded/9d57875196c613785a1eee010c55223a0f1aa821"


def main():
    repo, project, out, prefix = sys.argv[1:5]
    one = "--one-to-one" in sys.argv
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad277-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
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
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state().get("alive"), 30)
            assert api("text_scenes.select", HUD)
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 90)
            tv = state()["tree_view"]
            # the TopPanel sprite that draws the Credits_Text picture (not the Text of that name)
            hit = [h for h in tv["hits"] if h["id"] == NODE]
            print("hit:", [(h["id"], h["name"], h["kind"], h["path"]) for h in hit])
            nid = hit[0]["id"]
            api("text_scenes.tree_select", nid)
            rig._wait(lambda: (state()["tree_view"].get("props") or {}).get("id") == nid, 30)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            time.sleep(2)
            print("props:", state()["tree_view"]["props"])
            page.screenshot(path=os.path.join(out, "%s_selected.png" % prefix))
            if one:
                page.get_by_role("button", name="Draw 1:1").first.click()
                rig._wait(lambda: state()["tree_view"]["edits"] > 0, 30)
                rig._wait(lambda: not state().get("tree_busy"), 60)
                time.sleep(2)
                print("after 1:1:", state()["tree_view"]["props"])
                page.screenshot(path=os.path.join(out, "%s_one_to_one.png" % prefix))
                api("text_scenes.tree_undo")
                rig._wait(lambda: state()["tree_view"]["edits"] == 0, 30)
            print("page errors:", errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
