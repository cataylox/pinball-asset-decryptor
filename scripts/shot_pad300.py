"""PAD-300 proof shots: Save / load settings on the Images, Audio, Video and Text tabs.

    python scripts/shot_pad300.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of the
commit before it for the "before" shots).  The server runs on a COPY of David's real
settings (so the saved Stern project opens) with PAD_UI_CAPTURE set, so nothing is
written back into that project.  Writes <prefix>_<tab>.png into <out_dir> for each of
images, audio, video, text: the tab after its scan, with the menu that holds Save /
load open (More on the three media tabs, the Save / load button on Text when the
build has one).
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad232 as rig  # noqa: E402

TABS = ("images", "audio", "video", "text")


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    print("serving", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad300-")
    launcher = os.path.join(scratch, "launch300.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(rig.LAUNCHER % repo)
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    import site
    proc, url = webui_shot.start_server(
        real, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            for ns in TABS:
                webui_shot.api(url, "ui.select_tab", ns)
                time.sleep(2)
                deadline = time.time() + 120
                while time.time() < deadline:
                    st = webui_shot.state(url).get(ns) or {}
                    if not st.get("scanning"):
                        break
                    time.sleep(1)
                time.sleep(3)
                name = "Save / load" if ns == "text" else "More"
                btn = page.locator(".page:visible").get_by_role("button", name=name, exact=True)
                if btn.count():
                    btn.first.click()
                    time.sleep(1)
                    print("opened", ns, name, flush=True)
                else:
                    print("no", name, "button on", ns, flush=True)
                out = os.path.join(out_dir, "%s_%s.png" % (prefix, ns))
                page.screenshot(path=out)
                print("shot", out, flush=True)
                page.keyboard.press("Escape")
                time.sleep(0.5)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
