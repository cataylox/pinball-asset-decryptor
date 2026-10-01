"""PAD-298 proof shots: a Spike 2 song-video slot (key frame every 4 frames,
like every song video on a Metallica card) with a replacement that matches it
on everything but its key frames (one every 60, the user's own ffmpeg line).

    python scripts/shot_pad298.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (a pre-fix export for the before shot).
Writes <out_dir>/<prefix>_video_convert.png (the Video tab's Convert column)
and <out_dir>/<prefix>_video_slot_needs.png ("What this slot needs").
Every clip is a synthetic test pattern in a scratch folder.
"""

import json
import os
import subprocess
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

SLOT = "MetallicaIfDarknessHadASon_V1.mp4"


def _clip(path, gop, extra=()):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=1360x768:rate=30:duration=4", "-an",
         "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
         "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0"]
        + list(extra) + [path], check=True)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    print("serving", repo, flush=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.core import checksums, staged_changes
    scratch = tempfile.mkdtemp(prefix="pad298-")
    proj = os.path.join(scratch, "metallica")
    _clip(os.path.join(proj, "video", SLOT), 4, ["-level", "3.0"])
    _clip(os.path.join(proj, "video", "BallSaved.mov"), 60)
    mine = os.path.join(scratch, "mine", "test6_1360_fixed.mp4")
    _clip(mine, 60, ["-level", "3.2", "-b:v", "3800k"])
    checksums.generate_checksums(proj)
    staged_changes.save(proj, {"video": {"video/" + SLOT: mine}})

    launcher = os.path.join(scratch, "launch298.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": proj, "write_assets": proj}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PYTHONUSERBASE": os.path.join(os.environ["APPDATA"],
                                                  "Python")})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1560, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(8)
            row = page.get_by_text(SLOT[:-4]).first
            row.click()
            time.sleep(3)
            out = os.path.join(out_dir, "%s_video_convert.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            row.click(button="right")
            time.sleep(1)
            page.get_by_text("What this slot needs…", exact=True).click()
            time.sleep(2)
            out = os.path.join(out_dir, "%s_video_slot_needs.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
