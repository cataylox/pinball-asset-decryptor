"""PAD-226 proof shots: the Multi-boot tab says which images keep high scores of
their own, and the Edit image dialog is where an image is given them.

    python scripts/shot_pad226.py <out-dir> <prefix>

writes <out-dir>/<prefix>_table.png (the tab) and <prefix>_edit.png (Edit
image... on the modded image).  The server runs from THIS tree against a
scratch settings folder (no WSL, no rig).  The card is a canned inspect
report: three Godzilla Pro 1.15 images - stock, a modded one that keeps its
own scores on the card (images.conf scores=1|heisei) and a re-theme that
shares - fed to the panel's own load_inspect when the tab is first shown.
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
REPORT, CARD, MEDIA = json.load(open(%(spec)r))
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    if not getattr(self, "_pad226_done", False):
        self._pad226_done = True
        self.load_inspect(REPORT, CARD, MEDIA)
    return _orig(self, *a, **k)
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''

IMAGES = [("GODZILLA", "Stock Stern 1.15", None),
          ("HEISEI", "Custom modes", "heisei"),
          ("ORCHESTRAL", "Re-themed music", None)]


def main():
    out_dir, prefix = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad226-")
    cards = os.path.join(scratch, "pinball_spike2_multiboot", "cards")
    os.makedirs(cards)
    card = os.path.join(cards, "Godzilla_multi.raw")
    with open(card, "wb") as f:
        f.write(bytes(16))
    sys.path.insert(0, REPO)
    from pinball_decryptor.webui.multiboot_core import loaded_media_dir
    media = loaded_media_dir(card)
    os.makedirs(media, exist_ok=True)
    devs = ["/dev/mmcblk0p3", "/dev/mmcblk0p7:img1", "/dev/mmcblk0p7:img2"]
    images = [{"index": i, "device": d, "title": t, "subtitle": s, "art": None,
               "anim": None, "music": None, "art_source": "none",
               "anim_source": "none", "source": None, "source_exists": False,
               "title_dir": "godzilla_pro", "bypass": True, "version": "1.15.0",
               "own_scores": own}
              for i, (d, (t, s, own)) in enumerate(zip(devs, IMAGES))]
    report = {
        "card": card, "size": 31914983424, "layout": "multi",
        "images": images, "timeout": 15, "default": 0, "volume": 35,
        "mixer_volume": None, "sound_move": "synth", "sound_confirm": "none",
        "media": [], "has_media_json": True, "has_build_json": True,
        "selector": {"bytes": 41272, "version": "codeselect 3.0"},
        "warnings": []}
    spec = os.path.join(scratch, "spec.json")
    with open(spec, "w", encoding="utf-8") as f:
        json.dump([report, card, media], f)
    host = os.path.join(scratch, "host.py")
    with open(host, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO, "spec": spec})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    # the scratch APPDATA moves Python's user site too, and Pillow may live there
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
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            table = os.path.join(out_dir, prefix + "_table.png")
            page.screenshot(path=table)
            print("shot", table, flush=True)
            webui_shot.api(url, "multiboot.edit", 1)
            time.sleep(3)
            edit = os.path.join(out_dir, prefix + "_edit.png")
            page.screenshot(path=edit)
            print("shot", edit, flush=True)
            webui_shot.api(url, "multiboot.edit_cancel")
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
