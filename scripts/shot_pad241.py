"""PAD-241 proof shots: a multi-boot image can be a base card plus an edits folder.

    python scripts/shot_pad241.py <out-dir> <prefix>

writes <out-dir>/<prefix>_menu.png (the list's add menu, opened over a card holding the
primary) and <prefix>_rows.png (the list once a base card + edits folder and a random group
from a folder of edits sets are added - where the code has them; the before code has neither,
so its list holds the primary alone).  The server runs from THIS tree against a scratch
settings folder (no WSL, no rig); the edits folders are synthetic override sets naming the
stand-in base card, which is all the tab checks.
"""

import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

HOST = r'''
import json, sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.webui import multiboot_panel as mp
from pinball_decryptor.webui import host
BASE, ONE, SETS, ROWS = json.load(open(%(spec)r))
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    if not getattr(self, "_pad241_done", False):
        self._pad241_done = True
        self.add_image(BASE)
        if ROWS and hasattr(self, "add_edits_image"):
            self.add_edits_image(BASE, ONE)
            self.add_group_from_edits(BASE, SETS)
    return _orig(self, *a, **k)
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''


def _edits(folder, base):
    """A stand-in override set: one edited file and the manifest naming *base*."""
    os.makedirs(os.path.join(folder, "beatles"), exist_ok=True)
    f = os.path.join(folder, "beatles", "image.bin")
    with open(f, "wb") as o:
        o.write(b"edited songs")
    st, fst = os.stat(base), os.stat(f)
    card = {"path": base, "size": st.st_size, "mtime": int(st.st_mtime)}
    with open(os.path.join(folder, "overrides.json"), "w") as o:
        json.dump({"version": 2, "generation": "g", "parent": "", "card": card, "run_card": card,
                   "files": [{"path": "/beatles/image.bin", "size": fst.st_size,
                              "mtime": int(fst.st_mtime), "ranges": [[0, 12]]}]}, o)
    return folder


def shoot(out_dir, prefix, rows):
    scratch = tempfile.mkdtemp(prefix="pad241-")
    base = os.path.join(scratch, "images", "beatles-1_29_0.Release.8G.sdcard.raw")
    os.makedirs(os.path.dirname(base))
    with open(base, "wb") as f:
        f.write(bytes(16))
    one = _edits(os.path.join(scratch, "edits", "abbey_road_side_b"), base)
    sets = os.path.join(scratch, "edits", "jukebox")
    for n in ("rubber_soul", "revolver", "white_album", "let_it_be"):
        _edits(os.path.join(sets, n), base)
    spec = os.path.join(scratch, "spec.json")
    with open(spec, "w", encoding="utf-8") as f:
        json.dump([base, one, sets, rows], f)
    host = os.path.join(scratch, "host.py")
    with open(host, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO, "spec": spec})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, host],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "multiboot")
        time.sleep(4)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            out = os.path.join(out_dir, "%s_%s.png" % (prefix, "rows" if rows else "menu"))
            if not rows:
                page.locator(".mb-images button", has_text="Add image").first.click()
                time.sleep(1)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


def main():
    out_dir, prefix = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    shoot(out_dir, prefix, False)
    shoot(out_dir, prefix, True)


if __name__ == "__main__":
    main()
