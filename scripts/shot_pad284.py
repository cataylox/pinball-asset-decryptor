"""PAD-284 proof shots: picking a layer the game is not drawing, inside a sprite that is off.

    python scripts/shot_pad284.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project> (only read: the rig selects,
never edits), opens Scenes on Godzilla's KAIJU BATTLE SELECT (Ebirah showing), clicks
Gigan_Textbox_instance in the Layers list, then its sprite GiganFullBody_instance, and writes:

- <prefix>_textbox.png   the page with the Gigan text box picked
- <prefix>_body.png      the page after then picking the Gigan body it sits in
- <prefix>_notes.txt     what each pick drew (the layers on the canvas)
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad284-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = ["repo " + repo]

    def describe(tag):
        tv = state()["text_scenes"]["tree_view"]
        names = {l["id"]: l["name"] for l in tv["layers"]}
        notes.append("%s: frame %s, sel %s, %d hits, peek %s"
                     % (tag, tv["frame"], names.get(tv["sel"]), len(tv["hits"]),
                        (tv.get("props") or {}).get("peek")))
        notes.append("   last hits: %s" % [names.get(h["id"]) for h in tv["hits"][-4:]])
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
            assert api("text_scenes.select", rig.BATTLE)
            rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                      state()["text_scenes"].get("frames"), 90)
            time.sleep(1.5)
            describe("opened")
            layers = state()["text_scenes"]["tree_view"]["layers"]
            ids = {l["name"]: l["id"] for l in layers}

            def pick_and_snap(name, shot):
                row = page.locator('.tree-layers [data-node="%d"]' % ids[name])
                row.scroll_into_view_if_needed()
                row.locator(".ly-name").click() if row.locator(".ly-name").count() else \
                    row.click(position={"x": 120, "y": 8})
                time.sleep(0.5)
                rig._wait(lambda: not state()["text_scenes"].get("tree_busy"), 30)
                time.sleep(2.0)
                page.mouse.move(5, 995)                 # no tooltip over the list
                time.sleep(0.5)
                page.screenshot(path=os.path.join(out, "%s_%s.png" % (prefix, shot)))
                describe("picked " + name)
            pick_and_snap("Gigan_Textbox_instance", "textbox")
            pick_and_snap("GiganFullBody_instance", "body")
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
