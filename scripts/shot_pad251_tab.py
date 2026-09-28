"""PAD-251 proof shots, round 2: the Scenes TAB, its loading states and an edit that never
blanks the canvas.

    python scripts/shot_pad251_tab.py <repo> <project copy> <out_dir> <prefix> [--prepare]

Serves <repo> on a settings copy whose Stern project is <project copy> (a scratch copy: the
editor writes scene_edits.json into it; PAD251_CARD names the card for the Extract tab),
opens Scenes (the rail tab on a build that has it, else the Images tab's Scenes… window) on
Godzilla's KAIJU BATTLE SELECT, picks the Ebirah portrait and drags it, and writes:

- <prefix>_preparing.png  with --prepare: the project has no scene_tree.json yet (the first
  open reads it off the card)
- <prefix>_scenes.png     the scene as it opens
- <prefix>_dragging.png   mid-drag (the portrait's own pixels move on a build with layers)
- <prefix>_released.png   right after the drop, before the redraw lands
- <prefix>_settled.png    the redraw in
- <prefix>_timing.txt     what the canvas showed every 16 ms after the drop: how often it
                          had no picture (blank) and when the redraw landed
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
BATTLE = ("/godzilla_le/assets/lcd/auto_loaded/"
          "cac32730af42b9d26d26c4bb6e667b07da53113e")

# every 16 ms after the drop: does the canvas show a loaded picture, and which?
PROBE = r'''
() => new Promise((done) => {
  const out = [];
  const t0 = performance.now();
  const tick = () => {
    const c = document.querySelector(".tree-canvas");
    const imgs = c ? [...c.querySelectorAll("img")] : [];
    const ok = imgs.length && imgs.every((i) => i.complete && i.naturalWidth > 0);
    out.push([Math.round(performance.now() - t0), ok ? 1 : 0,
              imgs.map((i) => i.getAttribute("src")).join("|"),
              !!document.querySelector(".tree-busy")]);
    if (performance.now() - t0 < 2500) setTimeout(tick, 16); else done(out);
  };
  tick();
})
'''


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch251t.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project,
                                               "extract_input": os.environ.get(
                                                   "PAD251_CARD", "")}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def _wait(fn, timeout=60.0, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:                               # noqa: BLE001
            pass
        time.sleep(step)
    return False


def main():
    repo, project, out, prefix = sys.argv[1:5]
    prepare = "--prepare" in sys.argv
    os.makedirs(out, exist_ok=True)
    shot = lambda page, name: page.screenshot(path=os.path.join(out, "%s_%s.png" % (prefix, name)))  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad251t-")
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = []
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
            tabs = [t["ns"] for t in state()["shell"]["tabs"] if t.get("visible")]
            as_tab = "scenes" in tabs
            notes.append("Scenes is a rail tab: %s" % as_tab)
            if as_tab:
                page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            else:
                api("ui.select_tab", "images")
                time.sleep(2)
                api("images.open_scenes")
            if prepare:
                _wait(lambda: state()["text_scenes"].get("preparing") or
                      state()["text_scenes"].get("rebuilding"), 20, 0.05)
                time.sleep(1.2)
                shot(page, "preparing")
                t0 = time.time()
                _wait(lambda: not state()["text_scenes"].get("rebuilding"), 120)
                notes.append("editor prepared in %.1f s" % (time.time() - t0))
            _wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", BATTLE)
            _wait(lambda: state()["text_scenes"].get("tree_view") and
                  state()["text_scenes"].get("frames"), 30)
            time.sleep(1.5)
            shot(page, "scenes")
            canvas = page.locator(".tree-canvas")
            canvas.scroll_into_view_if_needed()
            box = canvas.bounding_box()
            sx, sy = box["width"] / 1360.0, box["height"] / 768.0
            px, py = box["x"] + 650 * sx, box["y"] + 420 * sy       # the Ebirah portrait
            page.mouse.click(px, py)
            _wait(lambda: (state()["text_scenes"].get("tree_layers") or {}).get("node")
                  == state()["text_scenes"]["tree_view"]["sel"], 10)
            time.sleep(0.5)
            box = canvas.bounding_box()
            sx, sy = box["width"] / 1360.0, box["height"] / 768.0
            px, py = box["x"] + 650 * sx, box["y"] + 420 * sy
            page.mouse.move(px, py)
            page.mouse.down()
            page.mouse.move(px - 60 * sx, py - 30 * sy, steps=6)
            page.mouse.move(px - 120 * sx, py - 60 * sy, steps=6)
            time.sleep(0.3)
            shot(page, "dragging")
            live = page.evaluate("() => !!document.querySelector('.tree-live')")
            notes.append("mid-drag the portrait's own layer moves: %s" % live)
            page.mouse.up()
            t0 = time.time()
            probe = page.evaluate_handle(PROBE)
            time.sleep(0.05)
            shot(page, "released")
            samples = probe.json_value()
            time.sleep(0.5)
            shot(page, "settled")
            blank = [s for s in samples if not s[1]]
            srcs = [s[2] for s in samples]
            changed = next((s[0] for i, s in enumerate(samples) if i and s[2] != srcs[0]), None)
            busy = [s[0] for s in samples if s[3]]
            notes.append("after the drop: %d samples over 2.5 s, %d with no picture on the canvas"
                         % (len(samples), len(blank)))
            if blank:
                notes.append("  blank from %d ms to %d ms" % (blank[0][0], blank[-1][0]))
            notes.append("  the redrawn picture was on the canvas at %s ms" % changed)
            notes.append("  'Updating' tag seen at: %s" % (
                "%d..%d ms" % (busy[0], busy[-1]) if busy else "never"))
            notes.append("page errors: %s" % errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    with open(os.path.join(out, prefix + "_timing.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    print("\n".join(notes))
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
