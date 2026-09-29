"""PAD-276 proof shots: clicking a greyed layer in the Scenes tab's Layers list.

    python scripts/shot_pad276.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project> (only read: the rig selects,
never edits), opens Scenes on Godzilla's HUD (the energy meter, one picture per level), clicks
the "Level 6" picture's eye in the Layers list and writes:

- <prefix>_open.png     the scene as it opens (which meter pictures are greyed)
- <prefix>_eye.png      the page after clicking the Level 6 picture's eye
- <prefix>_notes.txt    which moment the scene is at and which layers are greyed
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

HUD = ("/godzilla_le/assets/lcd/auto_loaded/"
       "9d57875196c613785a1eee010c55223a0f1aa821")
LEVEL6 = 2145           # unnamed_instance_16: EnergyMeter_Images_instance's "Level 6" picture


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad276-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = []

    def describe(tag):
        tv = state()["text_scenes"]["tree_view"]
        off = [l["name"] for l in tv["layers"] if not l["drawn"] and 2131 < l["id"] < 2147]
        pins = [s["name"] + "=" + (s["value"] or "rest") for s in tv["states"] if s["value"]]
        notes.append("%s: frame %s, pins %s, sel %s, greyed meter pictures %s, notes %s"
                     % (tag, tv["frame"], pins, tv["sel"], off, tv.get("notes")))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", HUD)
            rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                      state()["text_scenes"].get("frames"), 90)
            time.sleep(1.5)
            describe("opened")
            row = page.locator('.tree-layers [data-node="%d"]' % LEVEL6)

            def snap(name):
                row.scroll_into_view_if_needed()
                page.mouse.move(5, 995)                 # no tooltip over the list
                time.sleep(0.8)
                page.screenshot(path=os.path.join(out, "%s_%s.png" % (prefix, name)))
            snap("open")
            row.locator(".ly-eye").click()
            time.sleep(0.5)
            rig._wait(lambda: not state()["text_scenes"].get("tree_busy"), 30)
            time.sleep(2.0)
            snap("eye")
            describe("after the eye")
            notes.append("page errors: %s" % errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    with open(os.path.join(out, prefix + "_notes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    print("\n".join(notes))
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
