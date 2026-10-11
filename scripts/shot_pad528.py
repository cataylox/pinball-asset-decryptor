"""PAD-528 proof shots: the Font bar's Apply to all lines of text.

    python scripts/shot_pad528.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project with the game's own lines unlocked
and the OXYGEN DESTROYER screen's ":10" timer (scene 39455fd1, Time_Instance) selected and
given red on the Font bar (PAD-514).  Then, under the same names before and after:

- font_bar.png          The Font bar's Color section on that line.  Before: the color, Saved,
                        Save a copy and Load, and no way to give it to the other lines.
                        After: Apply to all lines of text under them.

After only: font_bar_confirm.png, the question Apply to all lines of text asks; answered Yes,
font_bar_applied.png, every line red and the scenes blue in the list (changed only by what was
applied to all); then Undo, and the list's colors before and after go to the console.

Needs Playwright (the user site-packages one).
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

SCENE = ("/godzilla_le/assets/lcd/auto_loaded/477760ac3cc07d1aec810758d9fd83b7bc86ee72/"
         "39455fd1cfe1f4e2827846a64e58799c65f3a067")
#: the screen's ":10" timer line (Time_Textbox.Time_Instance)
TIME = 319
RED = "#ff2a1a"


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad528-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tv = lambda: (state().get("text_scenes") or {}).get("tree_view") or {}  # noqa: E731
    from playwright.sync_api import sync_playwright

    def rows():
        return (state().get("text_scenes") or {}).get("scenes") or []

    def counts():
        got = {}
        for r in rows():
            got[r.get("state") or "same"] = got.get(r.get("state") or "same", 0) + 1
        return got

    def settle(page, wait=1.5):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                               # noqa: BLE001
            print("toasts still up", flush=True)
        page.mouse.move(5, 1100)
        time.sleep(wait)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1150})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open', '0');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", SCENE + "/scene.radium") or api("text_scenes.select", SCENE)
            time.sleep(8)
            print("unlocked:", api("text_scenes.tree_color_unlocked", True), flush=True)
            time.sleep(3)
            api("text_scenes.tree_color", TIME, True)
            time.sleep(2)
            print("selected:", api("text_scenes.tree_select", TIME), flush=True)
            time.sleep(4)
            props = tv().get("props") or {}
            print("line:", props.get("name"), props.get("kind"), flush=True)
            print("text colour:", api("text_scenes.tree_text_colour", TIME, RED, 100),
                  flush=True)
            time.sleep(5)
            page.locator('button.fnt-handle').first.click()
            time.sleep(3)
            sec = page.query_selector(".fnt-color-all") or page.query_selector(".fnt-saved")
            if sec:
                sec.scroll_into_view_if_needed()
            settle(page)
            page.screenshot(path=out("font_bar.png"))
            btn = page.query_selector(".fnt-color-all button")
            print("apply to all button:", bool(btn), flush=True)
            if after and btn:
                btn.click()
                time.sleep(4)
                page.screenshot(path=out("font_bar_confirm.png"))
                t = time.time()
                page.click(".modal button:has-text('Yes')")
                while time.time() - t < 120 and not any(
                        r.get("state") for r in rows()):
                    time.sleep(0.5)
                time.sleep(3)
                print("applied to all in %.1f s; list:" % (time.time() - t), counts(), flush=True)
                page.mouse.move(5, 1100)
                time.sleep(1)
                page.screenshot(path=out("font_bar_applied.png"))
                t = time.time()
                print("undo:", api("text_scenes.tree_undo"), flush=True)
                time.sleep(3)
                print("after Undo (%.1f s):" % (time.time() - t), counts(), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
