"""PAD-299 proof shot: Venom's character select no longer goes black while its camera zooms.

    python scripts/shot_pad299.py <repo> <project> <out_dir> <prefix> [frame,frame...]

Serves <repo> on a settings copy whose Stern project is <project> (a Venom LE 1.07 extract
with images/scene_textures), opens Scenes on the character select (90d12341...), moves the
timeline to each frame (default 12 and 38: where the tester saw the layers vanish) and writes
<prefix>_f<frame>.png.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

SELECT = ("/venom_le/assets/lcd/auto_loaded/1efcd4faac3f1c04bd100debe1e9b33faca543f1/"
          "90d123416750834005ecd91a6398f3394e62b026")


def main():
    repo, project, out, prefix = sys.argv[1:5]
    frames = [int(f) for f in (sys.argv[5] if len(sys.argv) > 5 else "12,38").split(",")]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad299-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", SELECT)
            rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                      state()["text_scenes"].get("frames"), 90)
            for f in frames:
                assert api("text_scenes.tree_moment", f)
                time.sleep(0.5)
                rig._wait(lambda: not state()["text_scenes"].get("tree_busy"), 60)
                time.sleep(2.0)
                page.mouse.move(5, 995)
                page.screenshot(path=os.path.join(out, "%s_f%d.png" % (prefix, f)))
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
