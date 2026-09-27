"""PAD-231 proof shot: a Star Wars 1.27 -> 1.31 mod transfer where 1.31
inserted a clip ahead of Game Over in its scene, so 1.27's Game Over card
path is 1.31's Extra Ball.  Shoots the Video tab of the new-version project
after the transfer.

    python scripts/shot_pad231.py <repo> <out_dir> <prefix>

<repo> is the source tree to plan + apply the transfer with and to serve (a
pre-fix export for the before shot).  Writes <out_dir>/<prefix>_video.png.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

SCENE = "/star_wars_le/assets/lcd/auto_loaded/5f1e/scene.assets/2.asset/"

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _blob(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _extract(folder, clips):
    """clips: [(filename, index in the scene, bytes)]."""
    rows = []
    for name, idx, data in clips:
        _blob(os.path.join(folder, "video", name), data)
        rows.append("%s\t%s%d.asset\t%d" % (name, SCENE, idx, len(data)))
    with open(os.path.join(folder, "video", "manifest.txt"), "w",
              encoding="utf-8") as f:
        f.write("# output\tcard path\tbytes\n" + "\n".join(rows) + "\n")


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.core import checksums, mod_transfer, staged_changes
    scratch = tempfile.mkdtemp(prefix="pad231-")
    old = os.path.join(scratch, "127_ori")
    new = os.path.join(scratch, "SW_131")
    boris = os.path.join(scratch, "127_boris", "video")
    _extract(old, [("Attract_Loop.mov", 0, b"mov attract"),
                   ("gameover.mov", 1, b"mov game over 1.27"),
                   ("extraball.mov", 2, b"mov extra ball"),
                   ("Hoth_BG.mov", 3, b"mov hoth")])
    _extract(new, [("Attract_Loop.mov", 0, b"mov attract"),
                   ("Holocron_BG.mov", 1, b"mov holocron, new in 1.31"),
                   ("gameover.mov", 2, b"mov game over 1.27"),
                   ("extraball.mov", 3, b"mov extra ball"),
                   ("Hoth_BG.mov", 4, b"mov hoth")])
    checksums.generate_checksums(old)
    checksums.generate_checksums(new)
    saved = {}
    for name in ("gameover.mov", "extraball.mov", "Hoth_BG.mov"):
        repl = os.path.join(boris, name)
        _blob(repl, b"boris " + name.encode())
        saved["video/" + name] = repl
    staged_changes.save(old, {"video": saved})
    plan = mod_transfer.plan_transfer(old, new)
    mod_transfer.apply_transfer(old, new, plan)
    for e in plan["video"]["matched"]:
        print("  %s <- %s" % (e["rel"], os.path.basename(e["repl"])))

    launcher = os.path.join(scratch, "launch231.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": new,
                       "write_assets": new}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1560, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(6)
            out = os.path.join(out_dir, "%s_video.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
