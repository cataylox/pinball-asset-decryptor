"""PAD-524 proof shots: a scene whose only change is a color profile on one of its lines.

    python scripts/shot_pad524.py <repo> <out_dir> [--after]

Serves <repo> on a stock copy of shot_pad312's Godzilla project (no scene edits, no Write
recorded) with the game's own lines unlocked and one line of KAIJU BATTLE SELECT switched on
with a yellow profile of its own, the way DragonRR had his CITY BONUS.  Then, under the same
names before and after:

- scenes_list.png  Scenes on KAIJU BATTLE SELECT.  Before: its dot in the scene list is the
                   hollow "not changed" one.  After: the orange "not written yet" dot.

The list's state for the scene goes to the console.  Needs Playwright (the user site-packages
one) and the installed Edge.
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
YELLOW = {"name": "Yellow", "gain": [3.19, 3.17, 0.14], "gamma": [0.22, 0.22, 3.85],
          "lift": [0.0, 0.0, 0.0], "saturation": 1.0}


def _project(scratch):
    """A stock copy of the Godzilla project, one line yellow: no picks, no scene edits."""
    dst = os.path.join(scratch, "gzho")
    shutil.copytree(base.SOURCE, dst, ignore=lambda d, names: [
        n for n in names if n in base.SKIP or n.startswith("scene_edits")
        or n == "text_colours_written.json"])
    rel = "%s#%d" % (CARD, LINE)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"image_color_unlocked": True, "text_color_slots": {rel: True},
                   "text_color_profiles": {rel: YELLOW}}, f, indent=2)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad524-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
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
            assert api("images.open_scenes", "images/scene_textures/radimg_530x726_90dbdeb2.png")
            time.sleep(2)
            api("text_scenes.select", base.BATTLE)
            time.sleep(10)
            rows = (state().get("text_scenes") or {}).get("scenes") or []
            row = next((r for r in rows if r.get("d") == base.BATTLE), None)
            print("battle row:", row, flush=True)
            print("scenes with a state:", sum(1 for r in rows if r.get("state")), "of",
                  len(rows), flush=True)
            page.mouse.move(5, 990)
            time.sleep(1.5)
            page.screenshot(path=out("scenes_list.png"))
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
