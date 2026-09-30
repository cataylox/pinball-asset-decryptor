"""PAD-290 proof shot: an eye hides a layer on the card, and the Scenes tab says so.

    python scripts/shot_pad290.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project>, opens Scenes on Godzilla's
KAIJU BATTLE SELECT, hides the Gigan body sprite as its eye does when Gigan is the monster
shown (DragonRR's edit) and, with the
project's scene_edits.json copied first and put back byte for byte at the end, writes:

- <prefix>_layers.png   the Layers list and the status line with Gigan hidden
- <prefix>_notes.txt    the eye's tooltip and the status line's words
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

SPRITE = "GiganFullBody_instance"


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad290-")
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
            api("text_scenes.tree_clear")
            time.sleep(1.5)
            layers = state()["text_scenes"]["tree_view"]["layers"]
            gig = [l for l in layers if l["name"] == SPRITE][0]
            row = page.locator('.tree-layers [data-node="%d"]' % gig["id"])
            row.scroll_into_view_if_needed()
            assert api("text_scenes.tree_visible", gig["id"], False)
            time.sleep(0.5)
            rig._wait(lambda: not state()["text_scenes"].get("tree_busy"), 30)
            time.sleep(2.0)
            row.scroll_into_view_if_needed()
            page.mouse.move(5, 995)
            time.sleep(0.5)
            page.screenshot(path=os.path.join(out, "%s_layers.png" % prefix))
            notes.append("eye tooltip: %s" % row.locator(".ly-eye").get_attribute("title"))
            notes.append("row: %s" % row.inner_text().replace("\n", " | "))
            notes.append("status: %s" % page.locator(".warn-ink").all_inner_texts())
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
