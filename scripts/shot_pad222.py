"""PAD-222 proof shots: a Labyrinth extract on a Mac that has no GDRE Tools.

    python scripts/shot_pad222.py <outdir> <prefix>

Writes ``<prefix>_extract.png`` (the Extract tab with its finished-run box),
``<prefix>_audio.png`` and ``<prefix>_video.png`` (the Replace tabs right
after that extract) into *outdir*.

The server runs from THIS tree against a scratch settings folder and
stands in for cooltoy's Mac:

- gpg and tar are the real ones (WSL on this Windows box: the same shell
  steps the Mac runs natively);
- GDRE Tools is asked for at the Mac's path
  (``~/.local/share/gdre_tools/Godot RE Tools``), which does not exist -
  nothing installs it on a Mac;
- the prerequisite strip is the Mac's (``build_prerequisites("darwin")``,
  every ``wsl`` row "n/a");
- the .fun is synthetic: a Godot 4.5 pack (format v3, plaintext
  directory, first entry a compiled script) named like Labyrinth's
  ``GDCraze_linux_20260130.x86_64`` with two sounds and one video in it.
  The pack is not BOF's May layout, which is what sent the extract to
  GDRE Tools before the fix.
"""

import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

HOST = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import prereqs
prereqs._probe_wsl = lambda cmd: (True, "n/a (non-Windows)", "")
if hasattr(prereqs, "_native_location"):
    prereqs._native_location = lambda: "host"
from pinball_decryptor.plugins.bof import manufacturer as bm
from pinball_decryptor.plugins.bof import pipeline as bp
if hasattr(bm, "build_prerequisites"):
    bm.BOFManufacturer.prerequisites = bm.build_prerequisites("darwin")
# The Mac's GDRE invocation, verbatim from cooltoy's log: the binary is
# not there, so bash answers "No such file or directory".
bp._BasePipeline._gdre_prefix = lambda self: (
    "GODOT_SILENCE_ROOT_WARNING=1 "
    "'/Users/cooltoy/.local/share/gdre_tools/Godot RE Tools' --headless ")
if hasattr(bp, "_mac_gdre_binary"):
    bp._mac_gdre_binary = lambda: (
        "/Users/cooltoy/.local/share/gdre_tools/Godot RE Tools")
    bp._platform = lambda: "darwin"
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


# --- the synthetic Labyrinth-like pack --------------------------------------

def _audio_sample(payload_bytes, rate=44100):
    """A Godot AudioStreamWAV .sample the source converter decodes (the
    shape tests/test_bof_source_converter.py builds)."""
    from pinball_decryptor.plugins.bof import source_converter as sc
    payload_class = b"AudioStreamWAV"
    cls = struct.pack("<I", len(payload_class) + 1) + payload_class + b"\x00"
    pre = b"RSRC" + b"\x00" * 16 + cls + b"\x00" * 64
    int_res = cls
    int_res += struct.pack("<I", 5)
    int_res += struct.pack("<II", 2, sc._VTYPE_PBA)
    int_res += struct.pack("<I", len(payload_bytes))
    int_res += payload_bytes
    int_res += b"\x00" * ((4 - len(payload_bytes) % 4) % 4)
    trailer = (struct.pack("<III", 3, 3, 1) +
               struct.pack("<III", 7, 3, rate) +
               struct.pack("<III", 8, 2, 0) +
               b"\x00" * 12 +
               b"RSRC")
    return pre + int_res + trailer


def _tone(seconds, hz, rate=44100):
    n = int(seconds * rate)
    return b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * hz
                                                            * i / rate)))
                    for i in range(n))


def _ogv_bytes():
    """A real 2 s Theora clip when ffmpeg is reachable (WSL), else Ogg
    bytes that only look like one."""
    import subprocess
    tmp = os.path.join(tempfile.gettempdir(), "pad222_intro.ogv")
    try:
        subprocess.run(
            ["wsl.exe", "--", "ffmpeg", "-y", "-loglevel", "error", "-f",
             "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
             "-c:v", "libtheora", "-q:v", "3",
             "/mnt/c/" + tmp[3:].replace("\\", "/")],
            check=True, timeout=120, capture_output=True)
        with open(tmp, "rb") as f:
            return f.read()
    except Exception as exc:                          # noqa: BLE001
        print("ffmpeg unavailable (%s); fake OggS bytes" % exc, flush=True)
        return b"OggS" + b"\x00" * 4000


def _pck_binary(files, base=104):
    """A Godot binary carrying a stock v3 PCK: plaintext directory at
    ``dir_offset``, entries laid out contiguously from ofs 0."""
    body = bytearray()
    blob = bytearray()
    ofs = 0
    for path, data in files:
        praw = path + b"\x00" * (((len(path) + 3) // 4 * 4) - len(path))
        body += struct.pack("<I", len(praw)) + praw
        body += struct.pack("<QQ", ofs, len(data))
        body += hashlib.md5(data).digest() + struct.pack("<I", 0)
        blob += data
        ofs += len(data)
    hdr = bytearray(104)
    hdr[0:4] = b"GDPC"
    struct.pack_into("<I", hdr, 4, 3)
    struct.pack_into("<III", hdr, 8, 4, 5, 1)
    struct.pack_into("<I", hdr, 20, 2)
    struct.pack_into("<Q", hdr, 24, base)
    struct.pack_into("<Q", hdr, 32, base + ofs)
    pck = bytes(hdr) + bytes(blob) + struct.pack("<I", len(files)) + bytes(body)
    return (b"\x7fELF" + b"\x00" * 508 + pck
            + struct.pack("<Q", len(pck)) + b"GDPC")


def _sidecar(res_path, imported):
    return ("[remap]\n\nimporter=\"wav\"\ntype=\"AudioStreamWAV\"\n"
            "uid=\"uid://b%s\"\npath=\"res://%s\"\n"
            % (hashlib.md5(res_path.encode()).hexdigest()[:10],
               imported)).encode()


def make_fun(out_path):
    from tests import synthetic
    sounds = [("goblin_song", 1.6, 330), ("oubliette_hit", 0.4, 880)]
    entries = [(b"res://scripts/main.gdc", b"GDSC" + b"\x00" * 300)]
    for name, secs, hz in sounds:
        h = hashlib.md5(name.encode()).hexdigest()
        imported = ".godot/imported/%s.wav-%s.sample" % (name, h)
        entries.append((("res://assets/audio/%s.wav.import" % name).encode(),
                        _sidecar("assets/audio/%s.wav" % name, imported)))
        entries.append((("res://" + imported).encode(),
                        _audio_sample(_tone(secs, hz))))
    entries.append((b"res://assets/videos/intro_magic_dance.ogv",
                    _ogv_bytes()))
    binary = _pck_binary(entries)
    files = {
        "GDCraze_linux_20260130.x86_64": binary,
        "update/update.sh": b"#!/bin/bash\necho update\n",
        "update/updatecode.sh": b"#!/bin/bash\necho code\n",
        "update/main": b"#!/bin/bash\n",
        "update/updated_updatecode":
            b"# Godot Code looks for the date on the next line\n# 2026.01.30 \n",
        "md5": (hashlib.md5(binary).hexdigest()
                + "  GDCraze_linux_20260130.x86_64\n").encode(),
    }
    return synthetic.make_bof_fun(out_path, game_key="labyrinth",
                                  files=files)


# --- driving the web UI -----------------------------------------------------

def reply(url, mid, value):
    base = url.split("/?")[0]
    token = url.split("t=")[1].split("&")[0]
    req = urllib.request.Request(
        base + "/api/reply", data=json.dumps({"id": mid, "v": value}).encode(),
        headers={"Content-Type": "application/json", "X-PAD-Token": token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def wait_finished(url, project, timeout=240):
    """The run is over when a box is up (a failed extract) or the baseline
    checksums have been written (the last thing a run does); a success
    shows in the tab, not in a box.  Returns the open modal, if any."""
    marker = os.path.join(project, ".checksums.md5")
    for _ in range(timeout * 2):
        time.sleep(0.5)
        open_ = webui_shot.state(url).get("modals", {}).get("open") or []
        if open_:
            return open_[-1]
        if os.path.isfile(marker) and time.time() - os.path.getmtime(marker) > 3:
            return None
    return None


def main():
    outdir = os.path.abspath(sys.argv[1])
    prefix = sys.argv[2] if len(sys.argv) > 2 else "before"
    os.makedirs(outdir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad222-")
    fun = os.path.join(scratch, "Labyrinth", "lab.fun")
    os.makedirs(os.path.dirname(fun))
    make_fun(fun)
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
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_PREREQS": ""}
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print("repo", REPO, "url", url, "project", project, flush=True)
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    from playwright.sync_api import sync_playwright
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "bof")
        webui_shot.api(url, "ui.select_tab", "extract")
        time.sleep(6)
        st = webui_shot.state(url)
        print("prereqs:", json.dumps(st["shell"].get("prereqs"))[:400],
              flush=True)
        tabs = {t["ns"]: t for t in st["shell"]["tabs"]}
        print("tabs:", list(tabs), flush=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "extract.start")
            modal = wait_finished(url, project)
            print("modal:", json.dumps(modal)[:900], flush=True)
            time.sleep(3)
            page.screenshot(path=os.path.join(outdir, prefix + "_extract.png"))
            if modal:
                reply(url, modal["id"], "ok")
                time.sleep(1)
            for ns in ("audio", "video"):
                target = next((t for t in tabs if ns in t.lower()), None)
                if not target:
                    print("no tab for", ns, flush=True)
                    continue
                webui_shot.api(url, "ui.select_tab", target)
                time.sleep(6)
                page.screenshot(path=os.path.join(outdir,
                                                  "%s_%s.png" % (prefix, ns)))
            browser.close()
        pck = os.path.join(project, "pck")
        n = sum(len(fs) for _, _, fs in os.walk(pck)) if os.path.isdir(pck) else -1
        print("pck files:", n, flush=True)
        for name in sorted(os.listdir(outdir)):
            if name.startswith(prefix):
                print("shot", name,
                      os.path.getsize(os.path.join(outdir, name)), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
