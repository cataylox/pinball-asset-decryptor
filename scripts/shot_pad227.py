"""PAD-227 proof shots: the Modes tab's Mode page, "Starts on" section.

    python scripts/shot_pad227.py <out.png> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings
folder. The project is a scratch folder holding the Godzilla Pro 1.15 example
modes; the card is faked (no image is read), and the Modes preview is on.
The last example mode is opened, so the "only after" choice has three other
modes to offer.
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
CARD = MP.ProjectCard(r"C:\fake\godzilla_pro-1_15_0.Release.8G.sdcard.raw", "godzilla_pro", "1.15.0", "test")
tab.ModesTab._title_card = lambda self, project: (CARD, "project")
tab.ModesTab.title_read = lambda self, card: ("none", None)
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''

SEED = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.plugins.stern import mode_project as MP
for i, (_n, spec) in enumerate(MP.examples_for(MP.GODZILLA_PRO_1_15)):
    if spec.name == "MECHAGODZILLA":      # what the after shot shows filled in (the before tree ignores it)
        spec.extra.update(start_also=[["Left ramp", 2]], after="KAIJU RUSH", after_when="game")
        for k, v in list(spec.extra.items()):
            if hasattr(spec, k):
                setattr(spec, k, v)
                del spec.extra[k]
    MP.save(%(project)r, "%%d_%%s" %% (i + 1, MP.slugify(spec.name)), spec)
'''


def main():
    out = os.path.abspath(sys.argv[1])
    repo = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else HERE
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad227-")
    project = os.path.join(scratch, "gz project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project})
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
            page = browser.new_page(viewport={"width": 1440, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            rows = page.get_by_text("MECHAGODZILLA", exact=False)
            if rows.count():
                rows.first.click()
                time.sleep(2)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
