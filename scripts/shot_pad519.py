"""PAD-519 proof shot: the Emulate tab's machine row with a Premium/LE card picked, its
Edition list open to what the card's own game program takes (Batman 66: Premium, LE, SLE).

    python scripts/shot_pad519.py <out.png> [card.raw] [edition]

A build from before PAD-519 has no Edition box on the row, which is the pair's control.
No WSL and no rig (webui_shot starts the app with PAD_UI_NO_RIG): the choices are read
straight off the card with the app's own ext4 reader.
"""

import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\batman-1_14_0.Release.8G.sdcard.raw"


def main():
    out = os.path.abspath(sys.argv[1])
    card = sys.argv[2] if len(sys.argv) > 2 else CARD
    edition = sys.argv[3] if len(sys.argv) > 3 else "SLE"
    if not os.path.isfile(card):
        raise SystemExit("no card at %s" % card)
    import site
    import tempfile
    scratch = tempfile.mkdtemp(prefix="pad519-")
    proc, url = webui_shot.start_server(
        None, scratch, extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "emulate")
        webui_shot.api(url, "ui.set", "emulate", "card", card)
        webui_shot.api(url, "ui.set", "emulate", "country", "U.S.A.")
        st = {}
        for _ in range(60):
            st = webui_shot.state(url)["emulate"]
            if st.get("editions_on"):
                break
            time.sleep(1)
        if st.get("editions_on"):
            webui_shot.api(url, "ui.set", "emulate", "edition", edition)
            time.sleep(1)
        st = webui_shot.state(url)["emulate"]
        print("editions", st.get("editions"), "edition", st.get("edition"), flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
