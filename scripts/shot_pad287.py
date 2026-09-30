"""PAD-287 proof shots: the Layers / Contents switch and the Images-tab button on a layer.

    python scripts/shot_pad287.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project>, opens Scenes on Godzilla's
KAIJU BATTLE SELECT and writes:

- <prefix>_layers.png    the right-hand panel: the switch and the Layers list
- <prefix>_notes.txt     what the page shows; with the button there, which picture it jumped to
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
    scratch = tempfile.mkdtemp(prefix="pad287-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = ["repo " + repo]
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
            time.sleep(2.0)
            page.mouse.move(5, 995)                     # no tooltip over the list
            time.sleep(0.5)
            page.locator(".scenes-top").first.screenshot(
                path=os.path.join(out, "%s_layers.png" % prefix))
            layers = state()["text_scenes"]["tree_view"]["layers"]
            with_pic = [l for l in layers if l.get("pics")]
            notes.append("%d layers, %d with a picture button" % (len(layers), len(with_pic)))
            btns = page.locator(".tree-layers .ly-img")
            notes.append("buttons on the page: %d" % btns.count())
            one = [l for l in with_pic if len(l["pics"]) == 1]
            if one:
                l = one[0]
                row = page.locator('.tree-layers [data-node="%d"]' % l["id"])
                row.scroll_into_view_if_needed()
                row.locator(".ly-img").click()
                time.sleep(2.5)
                im = state().get("images") or {}
                notes.append("clicked the button on %s (%s): wants %s; Images tab selection %s"
                             % (l["name"], l["kind"], l["pics"][0],
                                im.get("sel") or im.get("selected") or im.get("focus")))
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
