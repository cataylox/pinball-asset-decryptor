"""PAD-513 proof shot: the boxes Scenes marks as filled in by the game on Tank Attack.

    python scripts/shot_pad513.py <repo> <out_png> [project]

Serves <repo> on a scratch copy (images and text only) of David's stock Godzilla LE 1.16
project (default the Desktop's gzho), opens Scenes on Tank Attack Multiball's start screen
(scene 4567f96c, DragonRR's shot) and picks the last T of ATTACK.  Before PAD-513 every T of
TANK ATTACK and the MULTIBALL title were marked (teal dotted outline, gear in Layers,
"Filled in by the game with T!"); the game's Tank Attack code names only the instruction line
on that screen.  The layers marked filled go to the console.

Needs Playwright (the user site-packages one) and the installed Edge.
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

SCENE = ("/godzilla_le/assets/lcd/auto_loaded/687f744516db566f57937aa3345db2e82c3e10ea/"
         "4567f96cb9de3e97ef274b7cec9e74f7ddd8298b")
PICK = "Letter_7T_Instance"


def main():
    repo, out = sys.argv[1:3]
    source = sys.argv[3] if len(sys.argv) > 3 else r"C:\Users\david\OneDrive\Desktop\gzho"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad513-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json", "scene_edits_carried.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    open(os.path.join(project, ".checksums.md5"), "w").close()
    print("serving", repo, "project", project, flush=True)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    scenes = lambda: webui_shot.state(url).get("text_scenes") or {}   # noqa: E731
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
            api("ui.select_tab", "scenes")
            time.sleep(3)
            api("text_scenes.select", SCENE)
            rig._wait(lambda: not scenes().get("rebuilding"), 600)
            rig._wait(lambda: scenes().get("tree_view") and scenes().get("frames"), 120)
            rig._wait(lambda: not scenes().get("tree_busy"), 60)
            time.sleep(2)
            tv = scenes().get("tree_view") or {}
            filled = [(l["name"], l["filled"]) for l in tv.get("layers") or () if l.get("filled")]
            print("filled layers:", len(filled), flush=True)
            for name, f in filled:
                print("   ", name, f, flush=True)
            nid = next(l["id"] for l in tv.get("layers") or () if l["name"] == PICK)
            api("text_scenes.tree_select", nid)
            rig._wait(lambda: not scenes().get("tree_busy"), 60)
            time.sleep(2.5)
            props = (scenes().get("tree_view") or {}).get("props") or {}
            print("picked:", props.get("name"), "filled:", props.get("filled"), flush=True)
            page.mouse.move(5, 995)
            time.sleep(1.5)
            page.screenshot(path=out)
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
