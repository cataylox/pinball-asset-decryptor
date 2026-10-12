"""PAD-547 proof shots: a mode's info line laid out in the Scenes editor, as its screen is (PAD-323).

    python scripts/shot_pad547_layout.py <out dir> <before|after> <one-scene project> [<repo>]

<one-scene project> holds James Bond LE 1.06's HUD scene (hud 7de1c159, its status bar) as an extract makes it; the
server runs from <repo> (default: this tree) on a scratch copy of it holding DAF WIZARD, a blocks mode as the owner makes
their own mini-wizards: its words over the video, its name in the game's bar, SUPER JACKPOT = superjackpot under it.
"Lay out on the screen" is pressed for it. Shot:
  <before|after>_scenes_info_layout.png the Scenes editor on the HUD scene: before, its screen alone; after, its info
  line too, where the build puts it (under the status bar), then dragged lower with the editor's own call
"""

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import webui_shot  # noqa: E402

HOST = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.webui.tabs import modes as tab
CARD = MP.ProjectCard(r"C:\fake\james_bond_le-1_06_0.Release.16G.sdcard.raw", "james_bond_le", "1.06.0", "test")
tab.ModesTab._title_card = lambda self, project: (CARD, "project")
tab.ModesTab.title_read = lambda self, card: ("none", None)
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''

SEED = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.plugins.stern import block_modes as BM, code_modes as CM
slug, _c = BM.new_blocks_mode(%(project)r, "DAF WIZARD")
BM.save(%(project)r, slug, BM.normalize({"name": "DAF WIZARD", "seconds": 60, "screen": True, "screen_style": "words",
    "bar": {"on": True, "color": "#1060ff"},
    "info": {"on": True, "text": "SUPER JACKPOT", "value": {"k": "var", "name": "superjackpot"}},
    "vars": [{"name": "superjackpot", "reset": "mode"}], "scripts": []}))
spec = CM.load(%(project)r, slug)
spec.extra["title"] = "james_bond_le_1_06"
CM.save(%(project)r, slug, spec)
print(slug)
'''


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    source = os.path.abspath(sys.argv[3])
    repo = os.path.abspath(sys.argv[4]) if len(sys.argv) > 4 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad547l-")
    project = os.path.join(scratch, "bond project")
    shutil.copytree(source, project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project})
    import subprocess
    slug = subprocess.run([sys.executable, seed], check=True, capture_output=True, text=True).stdout.strip()
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print("repo", repo, "url", url, "mode", slug, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            print("lay out", webui_shot.api(url, "modes.lay_out_screen", slug), flush=True)
            for _ in range(120):
                if ((webui_shot.state(url).get("text_scenes") or {}).get("tree_view") or {}).get("layers"):
                    break
                time.sleep(0.5)
            webui_shot.api(url, "ui.select_tab", "scenes")
            time.sleep(3)
            st = webui_shot.state(url).get("text_scenes") or {}
            print("mode_layout", st.get("mode_layout"), flush=True)
            print("layers", [(l["id"], l["name"]) for l in (st.get("tree_view") or {}).get("layers") or ()
                             if l.get("mode")], flush=True)
            for label in ("Hide log", "Hide list", "Hide"):    # the log and both lists away: the drawing as big as it goes
                hide = page.get_by_text(label, exact=True)
                try:
                    hide.first.click(timeout=3000)
                    time.sleep(1)
                except Exception as e:                   # noqa: BLE001 - not on this page
                    print("no", label, type(e).__name__, flush=True)
            if which == "after":
                sys.path.insert(0, repo)
                from pinball_decryptor.webui import scene_mode_layout as ML
                webui_shot.api(url, "text_scenes.tree_select", ML.INFO_ART_ID)
                time.sleep(2)
                page.screenshot(path=os.path.join(outdir, "after_scenes_info_layout.png"))
                webui_shot.api(url, "text_scenes.tree_move", ML.INFO_ART_ID, 0, 40)
                time.sleep(3)
                with open(os.path.join(project, "modes", slug, "assets.json"), encoding="utf-8") as f:
                    print("info_layout", json.load(f).get("info_layout"), flush=True)
                page.screenshot(path=os.path.join(outdir, "after_scenes_info_dragged.png"))
            else:
                time.sleep(2)
                page.screenshot(path=os.path.join(outdir, "before_scenes_info_layout.png"))
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
