"""PAD-513 proof shots: the boxes Scenes marks as filled in by the game.

    python scripts/shot_pad513.py <repo> <out_png> [project] [--scene <dir>] [--pick <layer>]
                                  [--reread]

Serves <repo> on a scratch copy (images and text only) of David's stock Godzilla LE 1.16
project (default the Desktop's gzho), opens Scenes on a screen and picks a layer.  The marked
layers go to the console.

- Default: Tank Attack Multiball's start screen (scene 4567f96c, DragonRR's shot) with the
  last T of ATTACK picked.  Before PAD-513 every T of TANK ATTACK and the MULTIBALL title were
  marked; the game's Tank Attack code names only the instruction line on that screen.
- Round 2, with --reread (the project's game-program reading is done again from its card by
  <repo>'s code, as the Text tab does for a project read by an older build):
  ``--scene fb84341a.../7ec20395... --pick Mulitball_Instance``, Bridge Attack's super jackpot
  intro, whose code fills BRIDGE, ATTACK and MULTIBALL; ``--scene 99cd5ccc.../49ac2e40...
  --pick Line1_Left_Instance``, the battle vs Ebirah's screen, whose LEFT / CENTER / RIGHT the
  code does not name.
- Round 4, with --text <words>: then the Text tab with that scene's line of those words picked
  (a line the game writes itself takes no new words).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

LCD = "/godzilla_le/assets/lcd/auto_loaded/"
SCENE = "687f744516db566f57937aa3345db2e82c3e10ea/4567f96cb9de3e97ef274b7cec9e74f7ddd8298b"
PICK = "Letter_7T_Instance"
REREAD = r'''
import sys
sys.path.insert(0, sys.argv[1])
from pinball_decryptor.plugins.stern import engine
print("re-read from the card:", engine.refresh_program_text_flags(sys.argv[2]))
'''


def _opt(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    args = [a for i, a in enumerate(sys.argv[1:], 1)
            if not a.startswith("--") and sys.argv[i - 1] not in ("--scene", "--pick", "--text")]
    repo, out = args[:2]
    source = args[2] if len(args) > 2 else r"C:\Users\david\OneDrive\Desktop\gzho"
    scene, pick = LCD + _opt("--scene", SCENE), _opt("--pick", PICK)
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
    if "--reread" in sys.argv:
        shutil.copy2(os.path.join(source, ".extract_source.json"), project)
        subprocess.run([sys.executable, "-c", REREAD, os.path.abspath(repo), project],
                       check=True)
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
            api("text_scenes.select", scene)
            rig._wait(lambda: not scenes().get("rebuilding"), 600)
            rig._wait(lambda: scenes().get("tree_view") and scenes().get("frames"), 120)
            rig._wait(lambda: not scenes().get("tree_busy"), 60)
            time.sleep(2)
            tv = scenes().get("tree_view") or {}
            filled = [(l["name"], l["filled"]) for l in tv.get("layers") or () if l.get("filled")]
            print("filled layers:", len(filled), flush=True)
            for name, f in filled:
                print("   ", name, f, flush=True)
            nid = next(l["id"] for l in tv.get("layers") or () if l["name"] == pick)
            api("text_scenes.tree_select", nid)
            rig._wait(lambda: not scenes().get("tree_busy"), 60)
            time.sleep(2.5)
            props = (scenes().get("tree_view") or {}).get("props") or {}
            print("picked:", props.get("name"), "filled:", props.get("filled"),
                  "words:", props.get("words"), flush=True)
            words = _opt("--text", "")
            if words:
                # round 4: the same line on the Text tab, picked in its list
                text = lambda: webui_shot.state(url).get("text") or {}    # noqa: E731
                page.locator(".rail").get_by_text("Text", exact=True).first.click()
                rig._wait(lambda: text().get("rows") and not text().get("scanning"), 300, 0.5)
                box = page.locator(".text-page .search input").first
                box.click()
                box.fill(words)
                time.sleep(1.5)
                rows = text().get("rows") or []
                hit = next(i for i, r in enumerate(rows)
                           if r and r.get("o") == words and r.get("sc") != "game program"
                           and scene.rsplit("/", 1)[-1][:5] in (r.get("sc") or ""))
                api("text.select", hit)
                time.sleep(1.5)
                print("text row:", rows[hit], "locked:", text().get("locked"), flush=True)
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
