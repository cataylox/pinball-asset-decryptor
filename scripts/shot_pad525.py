"""PAD-525 proof shots: the game's own pictures keep their color switches through the Unlock
box going off and on again.

    python scripts/shot_pad525.py <repo> <out_dir> [--after]

Serves <repo> on a stock copy of shot_pad312's Godzilla project with Black and white as the
individual files profile, the game's own pictures unlocked, every picture of KAIJU BATTLE
SELECT and one of its lines switched on, the way DragonRR had his 70th anniversary scenes.
Then, in Scenes on that scene, the advanced "Unlock extracted images and text" box is
unticked and ticked again (as DragonRR did), and, under the same names before and after:

- scenes_unlock.png  Before: the Individual files label reads "on 0 files" and the scene is
                     back in its own colors.  After: every switch is back and the scene is
                     Black and white again.

The switches left on go to the console.  Needs Playwright (the user site-packages one) and
the installed Edge.
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
import shot_pad312 as base  # noqa: E402

CARD = base.BATTLE + "/scene.radium"
LINE = 1239
BW = {"name": "Black and white", "gamma": [1.0, 1.0, 1.0], "gain": [1.0, 1.0, 1.0],
      "lift": [0.0, 0.0, 0.0], "saturation": 0.0}


def _scene_pictures(project):
    with open(os.path.join(project, "images", "scene_textures", "scene_tree.json"),
              encoding="utf-8") as f:
        man = json.load(f)[CARD]
    out = set()
    for o in man["objects"].values():
        if isinstance(o, dict) and o.get("image"):
            out.add("images/" + o["image"])
    return sorted(out)


def _project(scratch):
    """A stock copy of the Godzilla project: Black and white on the battle scene's pictures
    and one of its lines, the game's own pictures unlocked; no picks, no scene edits."""
    dst = os.path.join(scratch, "gzho")
    shutil.copytree(base.SOURCE, dst, ignore=lambda d, names: [
        n for n in names if n in base.SKIP or n.startswith("scene_edits")
        or n == "text_colours_written.json"])
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"image_color_unlocked": True, "asset_color_profile": BW,
                   "image_color_slots": {r: True for r in _scene_pictures(dst)},
                   "text_color_slots": {"%s#%d" % (CARD, LINE): True}}, f, indent=2)
    return dst


def _switches(project):
    with open(os.path.join(project, ".staged_changes.json"), encoding="utf-8") as f:
        data = json.load(f)
    return (len(data.get("image_color_slots") or {}), len(data.get("text_color_slots") or {}),
            bool(data.get("image_color_unlocked")))


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad525-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    print("switches at the start (pictures, lines, unlocked):", _switches(project), flush=True)
    proc, url = base._serve(repo, scratch, project)
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
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open', '0');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE)
            time.sleep(10)
            print("unlock off:", api("text_scenes.tree_color_unlocked", False), flush=True)
            time.sleep(3)
            print("  switches (pictures, lines, unlocked):", _switches(project), flush=True)
            print("unlock on:", api("text_scenes.tree_color_unlocked", True), flush=True)
            time.sleep(8)
            print("  switches (pictures, lines, unlocked):", _switches(project), flush=True)
            page.mouse.move(5, 990)
            time.sleep(1.5)
            page.screenshot(path=out("scenes_unlock.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))
    print("scratch", scratch)


if __name__ == "__main__":
    main()
