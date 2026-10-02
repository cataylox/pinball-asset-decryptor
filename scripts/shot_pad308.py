"""PAD-308 proof shots: Bon Jovi loaded in the web UI.

    PAD_PWLIB=C:\\tmp\\pwlib python scripts/shot_pad308.py <outdir> <prefix> [fun]

Captures, with a real Bon Jovi .fun selected:
  <prefix>_extract.png    - Extract tab (detection)
  <prefix>_imageinfo.png  - Image Info window (the Bon Jovi notice + CTA)
  <prefix>_write.png      - Write tab (the extract-only badge)

Run on the ticket branch for the "after" and on a main export for the
"before" (where the same file is unrecognised).
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

DEFAULT_FUN = r"D:\Pinball\images\BoF\bon-jovi_2026.10.01.fun"


def _shot(page, outdir, name):
    path = os.path.join(outdir, name)
    page.screenshot(path=path)
    print("shot", name, os.path.getsize(path), flush=True)


def main():
    outdir = os.path.abspath(sys.argv[1])
    prefix = sys.argv[2] if len(sys.argv) > 2 else "after"
    fun = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_FUN
    os.makedirs(outdir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad308-")
    project = os.path.join(scratch, "BonJovi Code")
    os.makedirs(project)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "bof",
                   "manufacturers": {"bof": {"extract_input": fun,
                                             "extract_output": project}}}, f)
    proc, url = webui_shot.start_server(settings, scratch)
    print("url", url, "fun", fun, flush=True)
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    from playwright.sync_api import sync_playwright
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "bof")
        webui_shot.api(url, "ui.select_tab", "extract")
        time.sleep(4)
        st = webui_shot.state(url)
        tabs = [t["ns"] for t in st["shell"]["tabs"]]
        print("tabs:", tabs, flush=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            _shot(page, outdir, prefix + "_extract.png")

            # Image Info / card details (the Bon Jovi notice + CTA).
            try:
                webui_shot.api(url, "extract.open_image_info", "input")
                time.sleep(3)
                # Bring the "How you can help" row into view so the full CTA
                # shows (it sits below the fold in the card-details panel).
                try:
                    page.get_by_text("How you can help").scroll_into_view_if_needed(
                        timeout=5000)
                    time.sleep(1)
                except Exception as se:
                    print("scroll-to-CTA skipped:", se, flush=True)
                _shot(page, outdir, prefix + "_imageinfo.png")
                try:
                    webui_shot.api(url, "write.image_info_close")
                except Exception:
                    pass
            except Exception as e:
                print("image info open failed:", e, flush=True)

            # Write tab (the badge).
            wtab = next((t for t in tabs if "write" in t.lower()), "write")
            webui_shot.api(url, "ui.select_tab", wtab)
            time.sleep(4)
            _shot(page, outdir, prefix + "_write.png")
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
