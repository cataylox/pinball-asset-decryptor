"""PAD-318 capture: Settings > Manage disk space, after its scan of the
app's real WSL (what it offers to delete).

    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad318.py --out <dir>
        --prefix before_

Run it from the checkout whose app code you want (main's export for the
before shot).  The server runs against a scratch settings folder with the
WSL probes ON (PAD_UI_NO_RIG=0): the dialog scans for real, deletes nothing.
Shoots <prefix>disk_space.png once the scan is done.
"""
import argparse
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot as ws  # noqa: E402


def shoot(args):
    scratch = tempfile.mkdtemp(prefix="padshot318-")
    env = {"PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": ""}
    if os.environ.get("APPDATA"):
        env["PYTHONUSERBASE"] = os.path.join(os.environ["APPDATA"], "Python")
    proc, url = ws.start_server("", scratch, extra_env=env)
    from playwright.sync_api import sync_playwright
    errors, d = [], {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": args.width,
                                              "height": args.height})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            ws.api(url, "ui.settings_action", "disk_space")
            time.sleep(3)
            for _ in range(300):
                d = (ws.state(url).get("shellx") or {}).get("disk") or {}
                if d and not d.get("busy"):
                    break
                time.sleep(1)
            time.sleep(1)
            print("status:", d.get("status"))
            for r in d.get("rows", []):
                print("  " * r["level"] + r["text"], r["size"])
            page.screenshot(path=os.path.join(
                args.out, args.prefix + "disk_space.png"))
            browser.close()
    finally:
        proc.terminate()
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="after_")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1100)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    errors = shoot(args)
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
