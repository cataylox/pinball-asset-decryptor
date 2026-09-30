"""PAD-293 proof shot: the game's eye (red) no longer changes the preview; the preview has its
own eye (blue).

    python scripts/shot_pad293.py <repo> <project copy> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project copy> (a scratch copy: the
editor writes scene_edits.json into it), opens Scenes on Godzilla's KAIJU BATTLE SELECT, puts
the monster picker on Gigan, hides Gigan's body in the game (DragonRR's PAD-290 edit) and
writes:

- <prefix>_eyes.png     the preview and the Layers list with Gigan hidden in the game
- <prefix>_menu.png     the same, right-clicking Gigan's row
- <prefix>_notes.txt    the row's eyes' tooltips and the status line's words
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

SPRITE = "GiganFullBody_instance"


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    edits = os.path.join(project, "images", "scene_textures", "scene_edits.json")
    if os.path.isfile(edits):
        os.remove(edits)
    scratch = tempfile.mkdtemp(prefix="pad293-")
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
            time.sleep(1.5)
            idle = lambda: rig._wait(                      # noqa: E731
                lambda: not state()["text_scenes"].get("tree_busy"), 60)
            tv = state()["text_scenes"]["tree_view"]
            # the picker on Gigan, as DragonRR had it
            for st in tv["states"]:
                opt = [o for o in st["options"] if "gigan" in o["label"].lower()
                       and "select" in o["label"].lower()]
                if opt:
                    notes.append("state %s -> %s" % (st["name"], opt[0]["label"]))
                    api("text_scenes.tree_state", st["node"], opt[0]["value"])
                    break
            time.sleep(0.5)
            idle()
            layers = state()["text_scenes"]["tree_view"]["layers"]
            gig = [l for l in layers if l["name"] == SPRITE][0]
            row = page.locator('.tree-layers [data-node="%d"]' % gig["id"])
            row.scroll_into_view_if_needed()
            mark = row.locator(".ly-game")
            if mark.count():                            # the card mark (PAD-293 build)
                row.hover()
                mark.click()
            else:
                assert api("text_scenes.tree_visible", gig["id"], False)
            time.sleep(0.5)
            idle()
            time.sleep(2.0)
            row.scroll_into_view_if_needed()
            page.mouse.move(5, 995)
            time.sleep(0.5)
            page.screenshot(path=os.path.join(out, "%s_eyes.png" % prefix))
            for i, eye in enumerate(row.locator(".ly-eye, .ly-game").all()):
                notes.append("control %d tip: %s" % (
                    i, eye.get_attribute("data-tip") or eye.get_attribute("title")))
            notes.append("row tip: %s" % row.get_attribute("title"))
            # hovering the eye and the card mark: one tooltip each (no title="" anywhere up the
            # row, or the browser's own comes up late beside it)
            for name, sel in (("tip_eye", ".ly-eye"), ("tip_game", ".ly-game")):
                ctl = row.locator(sel)
                if not ctl.count():
                    continue
                ctl.hover()
                time.sleep(0.6)
                titled = ctl.evaluate("el => { const o = []; for (let e = el; e; e = e.parentElement)"
                                      " if (e.getAttribute && e.getAttribute('title')) o.push(e.className);"
                                      " return o; }")
                notes.append("%s: native titles up the chain: %s" % (name, titled))
                box = row.bounding_box()
                page.screenshot(path=os.path.join(out, "%s_%s.png" % (prefix, name)),
                                clip={"x": box["x"] - 330, "y": box["y"] - 190,
                                      "width": 660, "height": 330})
            # right-click on the row: the layer's menu
            row.click(button="right")
            time.sleep(0.8)
            page.screenshot(path=os.path.join(out, "%s_menu.png" % prefix))
            notes.append("menu: %s" % page.locator(".menu button, [role=menu] button")
                         .all_inner_texts())
            page.keyboard.press("Escape")
            time.sleep(0.3)
            notes.append("row: %s" % row.inner_text().replace("\n", " | "))
            notes.append("status: %s" % page.locator(".warn-ink").all_inner_texts())
            hits = [h["name"] for h in state()["text_scenes"]["tree_view"]["hits"]]
            notes.append("Gigan drawn in the preview: %s" % any("Gigan" in h for h in hits))
            notes.append("page errors: %s" % errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        if os.path.isfile(edits):
            os.remove(edits)
    with open(os.path.join(out, prefix + "_notes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    print("\n".join(notes))
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
