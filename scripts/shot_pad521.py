"""PAD-521 proof shots: the Bond owner's own You Only Live Twice mini-wizard, made to look like the game's own.

    python scripts/shot_pad521.py <out dir> <before|after> [<repo> [<screen> [<seed>]]]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project holds YOLT WIZARD,
a blocks mode as the owner made it: You Only Live Twice done -> Light the mode at the Right ramp with BLOFELD
(before: one insert blinking, all there was; after: the six villains chasing and the film's insert solid). Shot:
  <before|after>_<screen>.png its blocks, the pointer on the block its film event runs
  <before|after>_blocks_yolt_bar.png the settings row: (after) its name in the game's own status bar, its colour
"""

import json
import os
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
from pinball_decryptor.plugins.stern import block_modes as BM
film = %(film)r
slug, _c = BM.new_blocks_mode(%(project)r, "YOLT WIZARD")
BM.save(%(project)r, slug, BM.normalize({"name": "YOLT WIZARD", "seconds": 30, "vars": [], "bar": %(bar)r, "scripts": [
    {"hat": {"kind": "shot", "shot": "Side ramp enter opto", "when": "running"},
     "do": [{"op": "score", "points": {"k": "num", "v": 5000000}}, {"op": "add_time", "seconds": {"k": "num", "v": 5}}]},
    {"hat": {"kind": "event", "event": "film_yolt", "when": "any"}, "do": [film]}]}))
'''

FILM = {"before": {"op": "light_mode", "shot": "Right ramp exit opto", "insert": "BLOFELD", "color": "#00ff40",
                   "pattern": "blink"},
        "after": {"op": "light_mode", "shot": "Right ramp exit opto",
                  "insert": "DR. NO-RIGHT RAMP,ROSA KLEBB,GOLDFINGER-RIGHT RAMP,LARGO,BLOFELD,MR. HENDERSON",
                  "color": "#00ff40", "pattern": "chase", "solid": "Y.O.L.T.", "solid_color": "#ffffff"}}
WORDS = {"before": "Light the mode at", "after": "Light the mode at"}


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    screen = sys.argv[4] if len(sys.argv) > 4 else "blocks_yolt_wizard"
    kind = sys.argv[5] if len(sys.argv) > 5 else which
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad521-")
    project = os.path.join(scratch, "bond project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project, "film": FILM[kind],
                        "bar": {"on": True, "color": "#00c040"} if screen == "blocks_yolt_bar" else {}})
    import subprocess
    subprocess.run([sys.executable, seed], check=True)
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
    print("repo", repo, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "modes")
        time.sleep(4)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1500})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            time.sleep(2)
            rows = page.get_by_text("YOLT WIZARD", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
                time.sleep(1)
            scripts = page.locator(".bk-script")
            if screen == "blocks_yolt_bar":         # the settings row: its name in the game's bar, and its colour
                page.locator(".bk-settings").first.evaluate("(el) => el.scrollIntoView({block: 'center'})")
                time.sleep(0.5)
                box = page.get_by_text("its name in the game's bar", exact=True)
                print("bar box", box.count(), flush=True)
                page.screenshot(path=os.path.join(outdir, "%s_%s.png" % (which, screen)))
                browser.close()
                return
            if scripts.count():
                scripts.last.evaluate("(el) => el.scrollIntoView({block: 'center'})")
                time.sleep(0.5)
            block = page.locator(".bk-script .bk-w", has_text=WORDS[kind])
            print("blocks", block.count(), flush=True)
            if block.count() and os.environ.get("PAD521_HOVER"):
                block.last.hover()
                time.sleep(1.5)
            page.mouse.move(5, 5)
            time.sleep(0.5)
            page.screenshot(path=os.path.join(outdir, "%s_%s.png" % (which, screen)))
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
