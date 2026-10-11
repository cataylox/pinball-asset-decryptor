"""PAD-515 proof shots: the Scenes outlines and the Selected panel's sections.

    python scripts/shot_pad515.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project, opens the score panel (scene
9d578751: the game fills in the HIGH SCORE label and paints the players' scores itself) and
takes, under the same names before and after:

- scenes_plain_line.png    Credits_Text (a line the game neither fills nor paints) selected,
                           the mouse off the preview.  Before: every box the game fills keeps
                           a teal outline on the preview, and the Selected panel has no
                           game-fills / game-paints rows.  After: no outline but the
                           selection, and both rows are there, greyed out.
- scenes_filled_line.png   The HIGH SCORE label (the game fills it) selected, the mouse on
                           the active player's score (the game paints it).  Before: the selection is the
                           usual amber with the teal dotted outline on it, the hover white.
                           After: the selection is teal, the hover the painted colour.
- scenes_painted_line.png  The active player's score selected, the mouse on the HIGH SCORE label.
- scenes_picture.png       A picture (the top panel) selected: Words and Font controls.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

SCORE = "/godzilla_le/assets/lcd/auto_loaded/9d57875196c613785a1eee010c55223a0f1aa821"
HISCORE_LABEL, CREDITS, TOP_PANEL = 2111, 2473, 2463


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad515-")
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
        time.sleep(wait)

    def over(page, nid):
        """The mouse on node *nid* in the preview (or off the page with None)."""
        if nid is None:
            page.mouse.move(5, 1750)
            return
        view = tv()
        hit = next(h for h in view.get("hits") or [] if h["id"] == nid)
        xs, ys = [q[0] for q in hit["pts"]], [q[1] for q in hit["pts"]]
        sx, sy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        W, H = view["stage"]
        r = page.locator(".tree-canvas").first.bounding_box()
        page.mouse.move(r["x"] + sx * r["width"] / W - 3, r["y"] + sy * r["height"] / H - 3)
        page.mouse.move(r["x"] + sx * r["width"] / W, r["y"] + sy * r["height"] / H, steps=3)

    def shot(page, name, nid, hover=None):
        api("text_scenes.tree_select", nid)
        time.sleep(4)
        props = tv().get("props") or {}
        print(name, "picked:", props.get("name"), props.get("kind"),
              "filled:", props.get("filled"), "painted:", bool(props.get("game_colors")),
              flush=True)
        page.mouse.move(5, 1750)
        settle(page)
        over(page, hover)
        time.sleep(0.8)
        # the preview and the Selected panel, at full size
        a = page.locator(".tree-canvas").first.bounding_box()
        b = page.locator(".tree-side").first.bounding_box()
        x0, y0 = a["x"] - 12, min(a["y"], b["y"]) - 12
        x1, y1 = b["x"] + b["width"] + 12, max(a["y"] + a["height"], b["y"] + b["height"]) + 12
        page.screenshot(path=out(name), clip={"x": x0, "y": y0, "width": x1 - x0,
                                              "height": y1 - y0})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1800})
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
            api("text_scenes.select", SCORE + "/scene.radium") or api("text_scenes.select", SCORE)
            time.sleep(10)
            # the scene list out of the way: the preview as wide as it goes
            page.locator("button", has_text="Hide list").first.click()
            time.sleep(2)
            hits = tv().get("hits") or []
            print("filled hits:", [h["id"] for h in hits if h.get("filled")],
                  "painted hits:", [h["id"] for h in hits if h.get("painted")], flush=True)
            print("hits:", [(h["id"], h["name"], h["kind"]) for h in hits], flush=True)
            # the player who is up's score: the box the game paints gold
            score = next(h["id"] for h in hits if h["name"] == "score")
            shot(page, "scenes_plain_line.png", CREDITS)
            shot(page, "scenes_filled_line.png", HISCORE_LABEL, hover=score)
            shot(page, "scenes_painted_line.png", score, hover=HISCORE_LABEL)
            shot(page, "scenes_picture.png", TOP_PANEL)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))
    print("scratch", scratch)


if __name__ == "__main__":
    main()
