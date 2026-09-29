"""PAD-278 proof shots: the Scenes tab's list of parts the game switches, on Godzilla's
KAIJU BATTLE SELECT.

    python scripts/shot_pad278.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project> (only read: the rig opens
the scene and the list, never edits) and writes:

- <prefix>_closed.png  the side panel with the list folded shut, as it first shows
- <prefix>_open.png    the side panel with the list opened
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
    scratch = tempfile.mkdtemp(prefix="pad278-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
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
            rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", rig.BATTLE)
            rig._wait(lambda: (state()["text_scenes"].get("tree_view") or {}).get("states"), 120)
            time.sleep(3)
            side = page.locator(".tree-side").first
            side.screenshot(path=os.path.join(out, "%s_closed.png" % prefix))
            page.locator(".tree-states summary").first.click()
            time.sleep(1)
            page.set_viewport_size({"width": 1600, "height": 2400})
            time.sleep(1)
            side.screenshot(path=os.path.join(out, "%s_open.png" % prefix))
            print("summary:", page.locator(".tree-states summary").first.inner_text())
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
