"""PAD-221 proof shots: Install Missing on a Mac whose MacPorts was
installed for an older macOS (cooltoy's Labyrinth Mac, the day after
PAD-220).

    python scripts/shot_pad221.py <out.png> consent|failed|prereqs

The server runs from THIS tree against a scratch settings folder and stands
in for that Mac:

- the prerequisite probes are PAD-220's (gpg missing on the host, every
  WSL row n/a), the plugin's executor a stub;
- the package manager is MacPorts at /opt/local/bin/port;
- ``port version`` (when the tree asks) answers with cooltoy's "OS platform
  mismatch" refusal;
- the install run itself is canned: it prints the same refusal and fails.

``consent`` presses Install Missing and shows the consent dialog;
``failed`` answers it Yes and shows what comes after the failed run;
``prereqs`` shows the window right after the prerequisite check.
"""

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

MISMATCH = [
    'Error: Current platform "darwin 25" does not match expected platform '
    '"darwin 24"',
    "Error: Please run 'sudo port migrate' or follow the migration "
    "instructions: https://trac.macports.org/wiki/Migration",
    "OS platform mismatch",
    "    while executing",
    '"mportinit ui_options global_options global_variations"',
    "Error: /opt/local/bin/port: Failed to initialize MacPorts, OS "
    "platform mismatch",
    "0:223: execution error: The command exited with a non-zero status. (1)",
]

HOST = r'''
import sys
sys.path.insert(0, %(repo)r)
MISMATCH = %(mismatch)r
from pinball_decryptor.core import prereqs
prereqs._probe_wsl = lambda cmd: (True, "n/a (non-Windows)", "")
_host = prereqs._probe_host
def _mac_host(cmd):
    if "gpg" in cmd:
        return False, "exit code 1"
    return _host(cmd)
prereqs._probe_host = _mac_host
if hasattr(prereqs, "_native_location"):
    prereqs._native_location = lambda: "host"
from pinball_decryptor.plugins.bof import executor as bx
from pinball_decryptor.plugins.bof import manufacturer as bm
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
bm.BOFManufacturer.prerequisites = bm.build_prerequisites("darwin")
from pinball_decryptor.core import mac_install
PORT = ("MacPorts", "/opt/local/bin/port", True)
mac_install.package_manager = lambda: PORT
class _Done:
    returncode = 1
    stdout = ("\n".join(MISMATCH[:6]) + "\n").encode()
if hasattr(mac_install, "macports_health"):
    _health = mac_install.macports_health
    mac_install.macports_health = lambda tool: _health(
        tool, run=lambda argv, **kw: _Done())
def run_plan(plan, log, popen=None):
    for argv in (plan.get("commands") or [plan["install"]]):
        log(" ".join(argv))
    for line in MISMATCH:
        log(line)
    log("%%s did not finish (exit 1)." %% plan["label"])
    return False
mac_install.run_plan = run_plan
import pinball_decryptor.app as app_module
_orig_launch = app_module.App._launch_install_prereqs
def _mac_launch(self):
    # what the darwin branch of _launch_install_prereqs does, without
    # flipping sys.platform for the whole server
    if not self._install_prereqs_darwin():
        _orig_launch(self)
app_module.App._launch_install_prereqs = _mac_launch
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


def reply(url, mid, value):
    base = url.split("/?")[0]
    token = url.split("t=")[1].split("&")[0]
    req = urllib.request.Request(
        base + "/api/reply", data=json.dumps({"id": mid, "v": value}).encode(),
        headers={"Content-Type": "application/json", "X-PAD-Token": token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def wait_modal(url, timeout=30):
    for _ in range(timeout * 2):
        time.sleep(0.5)
        open_ = webui_shot.state(url).get("modals", {}).get("open") or []
        if open_:
            return open_[-1]
    return None


def main():
    out = os.path.abspath(sys.argv[1])
    which = sys.argv[2] if len(sys.argv) > 2 else "consent"
    scratch = tempfile.mkdtemp(prefix="pad221-")
    fun = os.path.join(scratch, "Labyrinth", "lab.fun")
    os.makedirs(os.path.dirname(fun))
    with open(fun, "wb") as f:
        f.write(bytes(65536))
    project = os.path.join(scratch, "Labyrinth Code")
    os.makedirs(project)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO, "mismatch": MISMATCH})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "bof",
                   "manufacturers": {"bof": {"extract_input": fun,
                                             "extract_output": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_PREREQS": ""}
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "bof")
        webui_shot.api(url, "ui.select_tab", "extract")
        time.sleep(6)
        if which in ("consent", "failed"):
            # install_prereqs blocks on the consent dialog: fire it aside
            threading.Thread(
                target=lambda: webui_shot.api(url, "shellx.install_prereqs"),
                daemon=True).start()
            modal = wait_modal(url)
            print("modal:", json.dumps(modal)[:900], flush=True)
            if which == "failed" and modal:
                reply(url, modal["id"], "yes")
                time.sleep(4)
                later = wait_modal(url, timeout=10)
                print("after run:", json.dumps(later)[:900], flush=True)
        st = webui_shot.state(url)
        print("prereqs:", json.dumps(st["shell"].get("prereqs"))[:600],
              flush=True)
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
