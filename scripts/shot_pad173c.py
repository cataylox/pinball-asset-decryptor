"""PAD-173 proof shots: the Extract card row, and the Select card page at a
given screen size.

    python scripts/shot_pad173c.py <out.png> <tab> <width> <height> [card.raw]

``tab`` is "extract" (the card row, which no longer carries its own ⓘ) or
"card" (the page whose details tile has to be visible without scrolling on a
wide screen).  The viewport is passed in because that is the whole point of
the second pair: 1920x1080 is what a 4K monitor reports at 200%.

No WSL and no rig (webui_shot sets PAD_UI_NO_RIG); playwright at PAD_PWLIB.
"""

import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402

CARD = (r"D:\Pinball\images\Stern\spike2"
        r"\jurassic_park_the_pin-1_05_0.Release.8G.sdcard.raw")


def main():
    out = os.path.abspath(sys.argv[1])
    tab = sys.argv[2]
    w, h = int(sys.argv[3]), int(sys.argv[4])
    card = sys.argv[5] if len(sys.argv) > 5 else CARD
    if not os.path.isfile(card):
        raise SystemExit("no card at %s" % card)
    import site
    import tempfile
    scratch = tempfile.mkdtemp(prefix="pad173c-")
    proc, url = webui_shot.start_server(
        None, scratch, extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.set", "extract", "input", card)
        webui_shot.api(url, "ui.select_tab", tab)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            # the card's report is read on a worker either way
            for _ in range(60):
                time.sleep(1)
                info = (webui_shot.state(url).get("card") or {}).get("info") \
                    or {}
                if info.get("state") == "ready":
                    break
            time.sleep(2)
            box = page.locator(".c-info").first
            if box.count():
                b = box.bounding_box()
                pane = page.locator(".page").first.bounding_box()
                print("details top %.0f | pane bottom %.0f | visible %s"
                      % (b["y"], pane["y"] + pane["height"],
                         b["y"] < pane["y"] + pane["height"]), flush=True)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
