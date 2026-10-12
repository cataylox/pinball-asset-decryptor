"""PAD-547 proof shots: the Bond owner's own mini-wizard shows its SUPER JACKPOT under the game's status bar, as the game's
own mini-wizards do (Duel on the Disco Volante: "SUPER JACKPOT = 53,200,000").

    python scripts/shot_pad547.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project holds DAF WIZARD, a
blocks mode as the owner made it: its name in the game's bar, a superjackpot variable each Side ramp grows, and (after)
"a line under its name" ticked with SUPER JACKPOT = superjackpot. Shot:
  <before|after>_blocks_info_line.png the settings row and, after, the line's own row under it
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
slug, _c = BM.new_blocks_mode(%(project)r, "DAF WIZARD")
BM.save(%(project)r, slug, BM.normalize({"name": "DAF WIZARD", "seconds": 60, "screen": True, "screen_style": "words",
    "bar": {"on": True, "color": "#1060ff"}, "info": %(info)r,
    "vars": [{"name": "superjackpot", "reset": "mode"}], "scripts": [
    {"hat": {"kind": "mode_start"}, "do": [{"op": "set", "var": "superjackpot", "value": {"k": "num", "v": 5000000}}]},
    {"hat": {"kind": "shot", "shot": "Side ramp enter opto", "when": "running"},
     "do": [{"op": "score", "points": {"k": "var", "name": "superjackpot"}},
            {"op": "change", "var": "superjackpot", "by": {"k": "num", "v": 1000000}}]}]}))
'''

INFO = {"before": {}, "after": {"on": True, "text": "SUPER JACKPOT", "value": {"k": "var", "name": "superjackpot"}}}


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    screen = "blocks_info_line"
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad547-")
    project = os.path.join(scratch, "bond project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project, "info": INFO[which]})
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
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            time.sleep(2)
            rows = page.get_by_text("DAF WIZARD", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
                time.sleep(1)
            page.locator(".bk-settings").first.evaluate("(el) => el.scrollIntoView({block: 'start'})")
            time.sleep(0.5)
            print("line box", page.get_by_text("a line under its name", exact=True).count(),
                  "row", page.get_by_text("Under its name", exact=True).count(), flush=True)
            page.mouse.move(5, 5)
            time.sleep(0.5)
            page.screenshot(path=os.path.join(outdir, "%s_%s.png" % (which, screen)))
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
