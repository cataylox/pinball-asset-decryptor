"""PAD-220 proof shots: Barrels of Fun on a Mac that has no gpg.

    python scripts/shot_pad220.py <out.png> prereqs|dialog

The server runs from THIS tree against a scratch settings folder (no WSL, no
rig) and stands in for a Mac without GnuPG:

- every ``where="wsl"`` prerequisite answers "n/a (non-Windows)", which is
  what a Mac answers;
- a host probe for gpg fails, every other host probe is the real one;
- the plugin's executor is a stub whose gpg commands die with
  ``bash: gpg: command not found`` (cooltoy's log), and the fail-fast text
  is spelled for macOS when the tree carries it.

``prereqs`` shows the main window right after the prerequisite check;
``dialog`` presses Extract on a stand-in lab.fun and shows the failure box.
"""

import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

HOST = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import prereqs
prereqs._probe_wsl = lambda cmd: (True, "n/a (non-Windows)", "")
_host = prereqs._probe_host
def _mac_host(cmd):
    if "gpg" in cmd:
        return False, "bash: gpg: command not found"
    return _host(cmd)
prereqs._probe_host = _mac_host
if hasattr(prereqs, "_native_location"):
    prereqs._native_location = lambda: "host"
if hasattr(prereqs, "_darwin"):
    prereqs._darwin = lambda: True
from pinball_decryptor.plugins.bof import executor as bx
from pinball_decryptor.plugins.bof import manufacturer as bm
from pinball_decryptor.plugins.bof import pipeline as bp
class MacNoGpg(bx.CommandExecutor):
    def run(self, bash_cmd, timeout=120):
        if "gpg" in bash_cmd:
            raise bx.CommandError(bash_cmd, 127, "bash: gpg: command not found")
        return ""
    def stream(self, bash_cmd, timeout=600):
        return iter(())
    def to_exec_path(self, host_path):
        return host_path
    def check_available(self):
        return True, "macOS native"
bm.create_executor = MacNoGpg
bx.create_executor = MacNoGpg
if hasattr(bp, "missing_gpg_text"):
    _text = bp.missing_gpg_text
    bp.missing_gpg_text = lambda platform=None: _text("darwin")
if hasattr(bm, "build_prerequisites"):
    bm.BOFManufacturer.prerequisites = bm.build_prerequisites("darwin")
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


def main():
    out = os.path.abspath(sys.argv[1])
    which = sys.argv[2] if len(sys.argv) > 2 else "prereqs"
    scratch = tempfile.mkdtemp(prefix="pad220-")
    fun = os.path.join(scratch, "Labyrinth", "lab.fun")
    os.makedirs(os.path.dirname(fun))
    with open(fun, "wb") as f:
        f.write(bytes(65536))
    project = os.path.join(scratch, "Labyrinth Code")
    os.makedirs(project)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "bof",
                   "manufacturers": {"bof": {"extract_input": fun,
                                             "extract_output": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    if which == "prereqs":
        env["PAD_UI_NO_PREREQS"] = ""
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "bof")
        webui_shot.api(url, "ui.select_tab", "extract")
        if which == "dialog":
            time.sleep(2)
            webui_shot.api(url, "extract.start")
            for _ in range(60):
                time.sleep(0.5)
                if webui_shot.state(url).get("modals", {}).get("open"):
                    break
        else:
            time.sleep(6)
        st = webui_shot.state(url)
        print("prereqs:", json.dumps(st["shell"].get("prereqs"))[:600],
              flush=True)
        print("modals:", json.dumps(st.get("modals"))[:600], flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(3)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
