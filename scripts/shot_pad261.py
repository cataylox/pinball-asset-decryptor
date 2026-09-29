"""PAD-261 proof shots: the Scenes tab's Play on Godzilla's credits scene (120 frames).

    python scripts/shot_pad261.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project> (only read: the rig selects
and plays, never edits), opens Scenes on the credits console scene, presses Play and writes:

- <prefix>_starting.png  1.5 s after Play
- <prefix>_playing.png   once every frame is drawn, mid-loop
- <prefix>_timing.txt    when the first frame showed, and how many of the scene's frames were
                         actually on the canvas over one loop (4 s at 30 fps)
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

CREDITS = ("/godzilla_le/assets/lcd/demand_loaded/"
           "2f312db041ab13dba5b5d617f116e2625da727ae")

# every 16 ms: the frame counter, and the picture actually painted on the canvas (an <img>
# still loading keeps showing the one before it; a <canvas> says what it drew)
PROBE = r'''
(ms) => new Promise((done) => {
  const out = [];
  const t0 = performance.now();
  let painted = "";
  const tick = () => {
    const c = document.querySelector(".tree-canvas");
    const lab = document.querySelector(".tree-playing");
    if (!lab) painted = "";
    const cv = c && c.querySelector("canvas[data-src]");
    const img = c && c.querySelector("img");
    if (!lab) {} else if (cv) painted = cv.getAttribute("data-src") || painted;
    else if (img && img.complete && img.naturalWidth > 0) painted = img.getAttribute("src");
    out.push([Math.round(performance.now() - t0), lab ? lab.textContent : "", painted]);
    if (performance.now() - t0 < ms) setTimeout(tick, 16); else done(out);
  };
  tick();
})
'''


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    shot = lambda page, name: page.screenshot(path=os.path.join(out, "%s_%s.png" % (prefix, name)))  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad261-")
    proc, url = rig._serve(repo, scratch, project)
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
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", CREDITS)
            rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                      state()["text_scenes"].get("frames"), 60)
            time.sleep(1.5)
            page.get_by_role("button", name="Play").first.click()
            t0 = time.time()
            probe = page.evaluate_handle(PROBE, 1500)
            time.sleep(1.5)
            shot(page, "starting")
            first = [s for s in probe.json_value() if s[2]]
            notes.append("first frame on the canvas: %s" % (
                "%d ms after Play" % first[0][0] if first else "not within 1.5 s"))
            rig._wait(lambda: (state()["text_scenes"].get("tree_play") or {}).get("done"), 180, 0.5)
            play = state()["text_scenes"]["tree_play"]
            notes.append("every frame drawn %.1f s after Play (%d distinct of %d)"
                         % (time.time() - t0, len(play.get("srcs") or []), play["frames"]))
            loop = page.evaluate(PROBE, 8000)
            shot(page, "playing")
            painted = [s[2] for s in loop[len(loop) // 2:]]        # one settled loop (4 s)
            seen = {s[1] for s in loop[len(loop) // 2:]}
            notes.append("over the last 4 s of playing: counter showed %d frame numbers, the "
                         "canvas painted %d different pictures"
                         % (len(seen), len({x for x in painted if x})))
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
