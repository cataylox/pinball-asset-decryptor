"""PAD-281 proof shots: saving modes and scene edits to a file, and loading them back.

    python scripts/shot_pad281.py <repo> <scenes project> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of the commit
before it for the "before" shots). <scenes project> is a Godzilla LE extract with a scene
tree (only read: the rig opens a menu, never picks from it). Writes into <out_dir>:

- <prefix>_modes.png   a Godzilla Pro 1.15 project with one mode, the list's Save / load menu
                       open (on a build that has it)
- <prefix>_scenes.png  Scenes on KAIJU BATTLE SELECT, the Save / load edits menu open (on a
                       build that has it)
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad232 as modes_rig  # noqa: E402
import shot_pad251_tab as scenes_rig  # noqa: E402


def _open_menu(page, name):
    btn = page.get_by_role("button", name=name)
    if btn.count():
        btn.first.click()
        time.sleep(1)
        print("opened", name, flush=True)
    else:
        print("no", name, "button on this build", flush=True)


def main():
    repo = os.path.abspath(sys.argv[1])
    project_scenes = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])
    prefix = sys.argv[4]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP

    # 1. the Modes tab, one mode
    scratch = tempfile.mkdtemp(prefix="pad281a-")
    project = modes_rig._project(scratch, "GZ 1.15 Pro Extract")
    MP.new_mode(project, spec=MP.ModeSpec(name="TARGET RUSH", title=MP.GODZILLA_PRO_1_15.key))
    proc, url = modes_rig._serve(repo, scratch, project)
    try:
        def modes(page):
            _open_menu(page, "Save / load")
            out = os.path.join(out_dir, "%s_modes.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        modes_rig._shoot(url, modes)
    finally:
        proc.terminate()

    # 2. the Scenes tab
    scratch = tempfile.mkdtemp(prefix="pad281b-")
    proc, url = scenes_rig._serve(repo, scratch, project_scenes)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            scenes_rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert webui_shot.api(url, "text_scenes.select", scenes_rig.BATTLE)
            scenes_rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                             state()["text_scenes"].get("frames"), 90)
            time.sleep(2)
            _open_menu(page, "Save / load edits")
            out = os.path.join(out_dir, "%s_scenes.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
