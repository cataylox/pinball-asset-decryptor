"""PAD-514 proof shots: a line of text in Scenes given a color of its own on the Font bar.

    python scripts/shot_pad514.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project set up the way DragonRR had his:
the individual files profile is his "My profile" (Middle shades red 10.00, Color level red
4.00, green and blue left at 1.00), the game's own lines unlocked, and the OXYGEN DESTROYER
screen's ":10" timer (scene 39455fd1, Time_Instance) switched on and selected.  White is
already full red, so the profile leaves it white.  Then, under the same names before and
after:

- colors_bar.png   The Colors bar on the ":10".  Before: red maxed, the ":10" still white,
                   and nothing says a line can be colored any other way.  After: the bar
                   says lines of text can be colored directly in the Font bar, and its Font
                   text color row shows the red the Font bar gave the line, drawn red.
- font_bar.png     The Font bar on the same line.  Before: font, size, style, spacing, no
                   color.  After: its Text color section (swatch, brightness, saved colors)
                   with red picked, the ":10" drawn red.

The line's colors go to the console.  Needs Playwright (the user site-packages one).
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
#: his "My profile": Middle shades red 10.00 (1 / gamma), Color level red 4.00
HIS_PROFILE = {"gamma": [0.1, 1.0, 1.0], "gain": [4.0, 1.0, 1.0]}
RED = "#ff2a1a"


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad514-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tv = lambda: (state().get("text_scenes") or {}).get("tree_view") or {}  # noqa: E731
    from playwright.sync_api import sync_playwright

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
            api("ui.select_tab", "color")
            time.sleep(1)
            api("color.set_mode", "assets")
            time.sleep(1)
            print("preset none:", api("color.preset", "none"), flush=True)
            time.sleep(1)
            print("his profile:", api("color.set_params", HIS_PROFILE), flush=True)
            time.sleep(1)
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
            if after:
                # the Font bar's own color: red, at full brightness
                print("text colour:", api("text_scenes.tree_text_colour", TIME, RED, 100),
                      flush=True)
                time.sleep(5)
                c = ((tv().get("props") or {}).get("font") or {}).get("colour") or {}
                print("line colour now:", c, flush=True)

            # the Colors bar on the line, his red sliders on show
            page.locator('button.cpd-handle[aria-label="Color profiles"]').first.click()
            deadline = time.time() + 20
            while time.time() < deadline and not (state().get("color") or {}).get("file"):
                time.sleep(0.5)
            f = (state().get("color") or {}).get("file") or {}
            print("colors bar file:", f.get("kind"), f.get("rel"), flush=True)
            time.sleep(4)
            settle(page)
            page.screenshot(path=out("colors_bar.png"))

            # the Font bar on the same line
            page.locator('button.fnt-handle').first.click()
            time.sleep(3)
            settle(page)
            page.screenshot(path=out("font_bar.png"))
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
