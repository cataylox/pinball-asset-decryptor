"""PAD-282 proof shots: zooming the Scenes preview (Ctrl / Shift + wheel, and + / - / fit buttons).

    python scripts/shot_pad282.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project> (only read: the rig never
edits), opens Scenes on Godzilla's KAIJU BATTLE SELECT, turns the wheel up three notches with
Ctrl held over the top-left portrait, and writes:

- <prefix>_zoom.png    the page after the Ctrl + wheel
- <prefix>_notes.txt   the canvas size before and after, and any page errors
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

SIZE = "() => { const c = document.querySelector('.tree-canvas'); return c ? [c.offsetWidth, c.offsetHeight] : null; }"


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad282-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = ["repo %s" % repo]
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
            time.sleep(2)
            notes.append("canvas before: %s" % (page.evaluate(SIZE),))
            box = page.locator(".tree-canvas").bounding_box()
            page.mouse.move(box["x"] + box["width"] * 0.2, box["y"] + box["height"] * 0.3)
            page.keyboard.down("Control")
            for _ in range(3):
                page.mouse.wheel(0, -100)
                time.sleep(0.3)
            page.keyboard.up("Control")
            time.sleep(1.5)
            notes.append("canvas after Ctrl + wheel: %s" % (page.evaluate(SIZE),))
            notes.append("zoom label: %s" % page.evaluate(
                "() => { const z = document.querySelector('.scenes-zoom-pct'); return z ? z.textContent : null; }"))
            page.mouse.move(5, 995)                     # no tooltip, no hover outline
            time.sleep(0.8)
            page.screenshot(path=os.path.join(out, "%s_zoom.png" % prefix))
            # the buttons: + twice, - once, then back to the whole screen (checked, not shot)
            pct = "() => { const z = document.querySelector('.scenes-zoom-pct'); return z ? z.textContent : null; }"
            scroll = "() => { const s = document.querySelector('.scenes-stage'); return [s.scrollLeft, s.scrollTop]; }"
            notes.append("scroll after Ctrl + wheel: %s" % (page.evaluate(scroll),))
            for name in ("Zoom in", "Zoom in", "Zoom out", "Back to the whole screen"):
                btn = page.get_by_role("button", name=name, exact=False).first
                if not btn.count():
                    notes.append("no %r button" % name)
                    continue
                btn.click()
                time.sleep(0.5)
                notes.append("after %s: %s canvas %s" % (name, page.evaluate(pct), page.evaluate(SIZE)))
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
