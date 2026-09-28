"""PAD-173 proof shot: what the ⓘ beside the picked card does.

    python scripts/shot_pad173b.py <out.png> [card.raw]

Starts the app, picks a card, opens the Extract tab and CLICKS the ⓘ badge
next to the card path, then shoots whatever that leaves on screen.  Before
PAD-173 that is the Image Info window, collecting the report a second time;
after it, the Select card tab with the same report already under the card.

No WSL and no rig (webui_shot sets PAD_UI_NO_RIG).  Needs playwright at
PAD_PWLIB, like the other web rigs.
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
    card = sys.argv[2] if len(sys.argv) > 2 else CARD
    if not os.path.isfile(card):
        raise SystemExit("no card at %s" % card)
    import site
    import tempfile
    scratch = tempfile.mkdtemp(prefix="pad173b-")
    proc, url = webui_shot.start_server(
        None, scratch, extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.set", "extract", "input", card)
        webui_shot.api(url, "ui.select_tab", "extract")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            badge = page.locator(
                '.x-cardpath ~ button, .x-pathrow button[title*="Technical"]')
            if not badge.count():
                badge = page.locator('button[title*="Technical details"]')
            print("badges", badge.count(), flush=True)
            badge.first.click()
            # the report is collected on a worker either way
            for _ in range(60):
                time.sleep(1)
                st = webui_shot.state(url)
                tab = (st.get("shell") or {}).get("tab")
                info = (st.get("card") or {}).get("info") or {}
                win = (st.get("extract") or {}).get("info") or {}
                if (tab == "card" and info.get("state") == "ready") or \
                        win.get("sections"):
                    break
            print("tab", tab, "| card info", info.get("state"),
                  "| window sections", bool(win.get("sections")), flush=True)
            # The report is under the card tile, so bring it into the shot -
            # otherwise the "after" is a picture of the splash and the pair
            # does not show the same thing twice.
            details = page.locator(".c-info")
            if details.count():
                details.first.scroll_into_view_if_needed()
            time.sleep(2)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
