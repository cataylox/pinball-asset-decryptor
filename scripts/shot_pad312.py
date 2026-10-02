"""PAD-312 proof shots: the color profile on chosen files (per picture, per video).

    python scripts/shot_pad312.py <repo> <out_dir> <prefix> [--after]

Serves <repo> on a settings copy whose Stern project is a SCRATCH COPY of David's
Godzilla project (images, text and scene trees only; no audio, builds or modes) with
one Battle Select portrait replaced by a vivid test picture, and writes:

- <prefix>_color.png    the Color profile tab
- <prefix>_images.png   the Images tab on the replaced portrait
- <prefix>_scenes.png   the Scenes window on Battle Select, Layers open

With --after (the ticket branch) the tab is put on "Chosen files" with every replaced
picture ticked first, so the pair shows the new toggles in use.

Needs Playwright (the user site-packages one) and the installed Edge.
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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
SOURCE = os.environ.get("PAD312_PROJECT", r"C:\Users\david\OneDrive\Desktop\gzho")
BATTLE = ("/godzilla_le/assets/lcd/auto_loaded/"
          "cac32730af42b9d26d26c4bb6e667b07da53113e")
PORTRAIT = "images/scene_textures/radimg_530x726_90dbdeb2.png"
SKIP = ("audio", "build", "logs", "modes", ".write_cache", ".hashcache.json")


def _project(scratch):
    """A copy of the Godzilla project light enough to copy (images, text, trees)."""
    dst = os.path.join(scratch, "gzho")
    shutil.copytree(SOURCE, dst,
                    ignore=lambda d, names: [n for n in names if n in SKIP])
    # one portrait replaced by a vivid picture: grey steps, full colours, a face tone
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (530, 726), (0, 0, 0, 255))
    d = ImageDraw.Draw(im)
    for i, v in enumerate((16, 32, 64, 96, 128, 160, 192, 224, 255)):
        d.rectangle([0, i * 60, 264, i * 60 + 59], fill=(v, v, v, 255))
    cols = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255),
            (255, 0, 255), (234, 192, 160), (24, 80, 128), (255, 255, 255)]
    for i, c in enumerate(cols):
        d.rectangle([266, i * 60, 530, i * 60 + 59], fill=c + (255,))
    for y in range(540, 726):
        v = round((y - 540) * 255 / 185)
        d.line([0, y, 530, y], fill=(v, v // 2, 255 - v, 255))
    rep = os.path.join(scratch, "my_portrait.png")
    im.save(rep)
    side = os.path.join(dst, ".staged_changes.json")
    try:
        with open(side, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.pop("color_profile", None)              # the pair starts from no profile
    data["image"] = {PORTRAIT: rep}
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch312.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def _wait_scan(state, ns, limit=180):
    deadline = time.time() + limit
    while time.time() < deadline:
        st = state().get(ns) or {}
        if st.get("scanning") is False or (st.get("total") and not st.get("scanning")):
            return st
        time.sleep(1)
    return state().get(ns) or {}


def main():
    repo, out, prefix = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad312-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
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
            time.sleep(1)
            # the Images tab first: its scan is what the other screens read
            api("ui.select_tab", "images")
            time.sleep(2)
            st = _wait_scan(state, "images")
            print("images:", st.get("status"), flush=True)
            if after:
                api("ui.select_tab", "color")
                time.sleep(1)
                api("color.set_mode", "assets")
                api("color.set_all", "images", True)
                time.sleep(1)
                print("color:", {k: state()["color"].get(k) for k in
                                 ("mode", "all_images", "all_videos", "asset_counts")},
                      flush=True)
            api("ui.select_tab", "color")
            time.sleep(3)
            page.screenshot(path=os.path.join(out, prefix + "_color.png"))
            api("ui.select_tab", "images")
            time.sleep(1)
            api("ui.set", "images", "search", "530x726")
            time.sleep(2)
            api("images.select", PORTRAIT)
            time.sleep(3)
            page.screenshot(path=os.path.join(out, prefix + "_images.png"))
            assert api("images.open_scenes", PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", BATTLE + "/scene.radium") or api("text_scenes.select", BATTLE)
            time.sleep(8)
            page.screenshot(path=os.path.join(out, prefix + "_scenes.png"))
            tv = (state().get("text_scenes") or {}).get("tree_view") or {}
            print("layers:", len(tv.get("layers") or []), "edits:", tv.get("edits"),
                  flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
