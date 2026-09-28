"""PAD-239 proof shots: Edit image... on a random card has a Games box, so a
random card's games are added, dropped and reordered where the card is edited.

    python scripts/shot_pad239.py <out-dir> <prefix>

writes <out-dir>/<prefix>_group.png (a random card that brings its own four
games: the list with Add files... / Add folder...) and <prefix>_keep.png (a
random card over the images already on the card: one tick per image).  The
server runs from THIS tree against a scratch settings folder (no WSL, no rig);
the rows are added through the panel's own add_image / add_group /
add_random_over_existing when the tab is first shown.
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
PLAIN, SONGS = json.load(open(%(spec)r))
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    if not getattr(self, "_pad239_done", False):
        self._pad239_done = True
        for p in PLAIN:
            self.add_image(p)
        self.add_group(SONGS, title="JUKEBOX")
        self.add_random_over_existing(title="SURPRISE ME")
    return _orig(self, *a, **k)
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''


def _raw(folder, name):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(bytes(16))
    return path


def main():
    out_dir, prefix = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad239-")
    imgs = os.path.join(scratch, "images")
    plain = [_raw(imgs, "godzilla_pro-1_15_0.%s.8G.sdcard.raw" % n)
             for n in ("Release", "Heisei", "Orchestral")]
    songs = [_raw(os.path.join(scratch, "songsets"),
                  "godzilla_pro-1_15_0.Songs%d.8G.sdcard.raw" % n)
             for n in (1, 2, 3, 4)]
    spec = os.path.join(scratch, "spec.json")
    with open(spec, "w", encoding="utf-8") as f:
        json.dump([plain, songs], f)
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
            for row, name in ((3, "group"), (4, "keep")):
                webui_shot.api(url, "multiboot.edit", row)
                time.sleep(3)
                out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
                page.screenshot(path=out)
                print("shot", out, flush=True)
                webui_shot.api(url, "multiboot.edit_cancel")
                time.sleep(1)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
