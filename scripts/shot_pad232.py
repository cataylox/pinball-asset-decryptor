"""PAD-232 proof shots: the Modes tab's ways to make a mode, and the block editor.

    python scripts/shot_pad232.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of the
commit before it for the "before" shots).  Writes into <out_dir>:

- <prefix>_first_mode.png   a Godzilla Pro 1.15 project with no mode yet: the ways in
- <prefix>_new_menu.png     the same project with one form mode: the New menu open
- <prefix>_blocks_editor.png  (a tree with block modes only) a mode made of blocks, open

The Modes tab is a preview feature: the settings copy carries only the preview code
from David's real settings.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _project(scratch, name):
    project = os.path.join(scratch, name)
    os.makedirs(project)
    card = "godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    return project


def _serve(repo, scratch, project):
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes", [])
    launcher = os.path.join(scratch, "launch232.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": codes,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def _shoot(url, fn, height=1000):
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1500, "height": height})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_function("window.__padReady === true", timeout=60000)
        webui_shot.api(url, "ui.select_tab", "modes")
        time.sleep(3)
        fn(page)
        browser.close()
        if errors:
            print("PAGE ERRORS:", errors, flush=True)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP

    # 1. no mode yet: the first-mode page
    scratch = tempfile.mkdtemp(prefix="pad232a-")
    project = _project(scratch, "GZ 1.15 Pro Extract")
    proc, url = _serve(repo, scratch, project)
    try:
        def first(page):
            out = os.path.join(out_dir, "%s_first_mode.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        _shoot(url, first)
    finally:
        proc.terminate()

    # 2. one form mode: the New menu, open
    scratch = tempfile.mkdtemp(prefix="pad232b-")
    project = _project(scratch, "GZ 1.15 Pro Extract")
    MP.new_mode(project, spec=MP.ModeSpec(name="TARGET RUSH", title=MP.GODZILLA_PRO_1_15.key))
    proc, url = _serve(repo, scratch, project)
    try:
        def menu(page):
            page.get_by_role("button", name="New").first.click()
            time.sleep(1)
            out = os.path.join(out_dir, "%s_new_menu.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        _shoot(url, menu)
    finally:
        proc.terminate()

    # 3. a mode made of blocks, open (only a tree that has them)
    try:
        from pinball_decryptor.plugins.stern import block_modes as BM
    except ImportError:
        return
    scratch = tempfile.mkdtemp(prefix="pad232c-")
    project = _project(scratch, "GZ 1.15 Pro Extract")
    slug, _path = BM.new_blocks_mode(project, "RAMP FRENZY", example="ramps")
    proc, url = _serve(repo, scratch, project)
    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            out = os.path.join(out_dir, "%s_blocks_editor.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            page.get_by_role("tab", name="C it makes").click()
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_code.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        _shoot(url, blocks, height=1500)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
