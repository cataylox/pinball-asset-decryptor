"""PAD-173 proof shot: the Emulate tab with Power on "50 Hz mains, US machine"
and a card whose game has no mains lock.

    python scripts/shot_pad173.py <out.png> [card.raw]

The card defaults to Jurassic Park The Pin, one of the two titles in David's
library with no mains check in the binary at all (the other is Star Wars ELG);
it is the shape of machine the reporter runs.  A build from before PAD-173
shows the row with nothing under it, which is the pair's own control: the tab
promised a refusal the game was never going to give.

No WSL and no rig (webui_shot starts the app with PAD_UI_NO_RIG): the verdict
is read straight off the card with the app's own ext4 reader, so this runs on
Windows with nothing else up.  A cold card takes ~30 s to answer.
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
POWER = "50 Hz mains, US machine"


def main():
    out = os.path.abspath(sys.argv[1])
    card = sys.argv[2] if len(sys.argv) > 2 else CARD
    if not os.path.isfile(card):
        raise SystemExit("no card at %s" % card)
    import site
    import tempfile
    scratch = tempfile.mkdtemp(prefix="pad173-")
    # The user site carries the app's dependencies; without it the plugins do
    # not import and the app has no manufacturers at all (shot_pad205's trap).
    proc, url = webui_shot.start_server(
        None, scratch, extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "emulate")
        webui_shot.api(url, "ui.set", "emulate", "card", card)
        webui_shot.api(url, "ui.set", "emulate", "country", "U.S.A.")
        webui_shot.api(url, "ui.set", "emulate", "power", POWER)
        note = ""
        for _ in range(120):                    # a cold card read is ~30 s
            st = webui_shot.state(url)["emulate"]
            note = st.get("mains_note") or ""
            if note:
                break
            time.sleep(1)
        print("power", webui_shot.state(url)["emulate"].get("power"),
              flush=True)
        print("note", repr(note), flush=True)
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
