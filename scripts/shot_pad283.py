"""PAD-283 proof shots: Ctrl+Z and Ctrl+Y in the scene editor after a side-panel button.

    python scripts/shot_pad283.py <repo> <project copy> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project copy> (a scratch copy: the
editor writes scene_edits.json into it), opens Scenes on Godzilla's HUD, selects the
Credits_Text picture and presses "Draw 1:1" (the keyboard focus is then on that button, not
the preview), then:

- <prefix>_ctrl_z.png  after pressing Ctrl+Z
- <prefix>_ctrl_y.png  after pressing Ctrl+Y
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402
from shot_pad277 import HUD, NODE  # noqa: E402


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad283-")
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
            api("text_scenes.tree_select", NODE)
            rig._wait(lambda: (state()["tree_view"].get("props") or {}).get("id") == NODE, 30)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            page.get_by_role("button", name="Draw 1:1").first.click()
            rig._wait(lambda: state()["tree_view"]["edits"] > 0, 30)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            time.sleep(1.5)
            print("after 1:1:", state()["tree_view"]["edits"], "edit(s)")
            for key, name in (("Control+z", "ctrl_z"), ("Control+y", "ctrl_y")):
                page.keyboard.press(key)
                time.sleep(1.0)
                rig._wait(lambda: not state().get("tree_busy"), 60)
                time.sleep(2)
                tv = state()["tree_view"]
                print("after %s: %d edit(s), picture drawn at %s%%" % (
                    key, tv["edits"], ((tv.get("props") or {}).get("pic") or {}).get("sx")))
                page.screenshot(path=os.path.join(out, "%s_%s.png" % (prefix, name)))
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
