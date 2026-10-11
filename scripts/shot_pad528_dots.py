"""PAD-528 proof shots and end-to-end check: No change after a Black and white Write.

    python scripts/shot_pad528_dots.py <repo> <out_dir> [--after]

On a stock copy of shot_pad312's Godzilla project set up as DragonRR had his (shot_pad524's
--all project: Black and white the individual files profile, every game picture switched
on, one KAIJU BATTLE SELECT line with a yellow profile of its own), <repo>'s own code stages
three of KAIJU BATTLE SELECT's pictures and a Write is recorded, as a Write leaves them: Black
and white on the card.  Then the individual files profile goes to No change (All images with
No change) and, under the same names before and after:

- scenes_list_no_change.png  Scenes on KAIJU BATTLE SELECT.  Before: every scene's dot
                             orange, as if each had edits of its own.  After: blue, changed
                             only by the profile applied to all, as Black and white was.

Then <repo>'s staging runs again on the three pictures and the console says whether each is
the game's own picture again (before: still Black and white; after: back).  Needs Playwright
(the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(sys.argv[1])
sys.path.insert(0, REPO)                       # the staging and the Write record: <repo>'s
sys.path.insert(1, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402
import shot_pad524 as s524  # noqa: E402

PICS = ["images/scene_textures/radimg_530x726_90dbdeb2.png",
        "images/scene_textures/radimg_530x726_7d50e4f5.png",
        "images/scene_textures/radimg_Tokyo_220x234_1aa7769d.png"]


def _stage(project):
    """<repo>'s image staging on PICS only: ``{rel: "game's own" | "changed"}``."""
    from pinball_decryptor.core import image_slots, staged_originals
    from pinball_decryptor.core.image import detect_image_info
    slots = {}
    for rel in PICS:
        f = os.path.join(project, *rel.split("/"))
        if os.path.isfile(f):
            slots[rel] = image_slots.ImageSlot(rel_path=rel, abs_path=f, ext=".png",
                                               info=detect_image_info(f),
                                               size=os.path.getsize(f), probed=True)
    print("staged:", image_slots.stage_replacements(slots, {}, assets_dir=project), flush=True)
    from PIL import Image
    out = {}
    for rel, sl in slots.items():
        snap = staged_originals.snapshot_path(project, rel)
        if not snap:
            out[rel] = "no snapshot: never changed"
            continue
        same = (Image.open(sl.abs_path).convert("RGBA").tobytes()
                == Image.open(snap).convert("RGBA").tobytes())
        out[rel] = "game's own" if same else "changed"
    return out


def main():
    out_dir = os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad528d-")
    project = s524._project(scratch, every=True)
    print("Black and white staging:", _stage(project), flush=True)
    from pinball_decryptor.plugins.stern import scene_edit
    t = time.time()
    scene_edit.mark_built(project)
    print("Write recorded in %.1f s" % (time.time() - t), flush=True)
    print("serving", REPO, "project", project, flush=True)
    proc, url = base._serve(REPO, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright

    def counts():
        rows = (state().get("text_scenes") or {}).get("scenes") or []
        got = {}
        for r in rows:
            got[r.get("state") or "same"] = got.get(r.get("state") or "same", 0) + 1
        return got, len(rows)
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
            assert api("images.open_scenes", PICS[0])
            time.sleep(2)
            api("text_scenes.select", base.BATTLE)
            time.sleep(10)
            print("as written:", counts(), flush=True)
            # All images with No change: the individual files profile No change
            api("color.set_mode", "assets")
            time.sleep(1)
            print("preset none:", api("color.preset", "none"), flush=True)
            time.sleep(8)
            print("No change:", counts(), flush=True)
            page.mouse.move(5, 990)
            time.sleep(1.5)
            page.screenshot(path=out("scenes_list_no_change.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("No change staging:", _stage(project), flush=True)
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
