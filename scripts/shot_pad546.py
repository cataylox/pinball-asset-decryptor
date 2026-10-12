"""PAD-546 proof shot: the Save automatically tooltip in Settings (the gear).

    python scripts/shot_pad546.py <repo> <out_dir> [--after]

Serves <repo>'s web UI on a scratch settings file and an empty scratch project, opens the
gear, points at Save automatically > Every 5 minutes and waits for its tooltip.  Under the
same name before and after:

- autosave_tip.png  Before: the tooltip lists "modes" among what is saved at once, a word
                    every user sees.  After: the same tooltip without it.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad251_tab as rig  # noqa: E402


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, ("after_" if after else "before_") + "autosave_tip.png")
    scratch = tempfile.mkdtemp(prefix="pad546-")
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    proc, url = rig._serve(repo, scratch, project)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 800})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.locator(".sx-gear button").first.click()
            time.sleep(1)
            page.get_by_text("Save automatically", exact=True).first.hover()
            time.sleep(1)
            page.get_by_text("Every 5 minutes", exact=True).first.hover()
            time.sleep(2.5)
            page.screenshot(path=out)
            print("tooltip:", page.evaluate(
                "() => [...document.querySelectorAll('[role=tooltip], .tip, .tooltip')]"
                ".map(e => e.innerText).filter(Boolean)"), flush=True)
            browser.close()
    finally:
        proc.kill()
    print("wrote", out)


if __name__ == "__main__":
    main()
