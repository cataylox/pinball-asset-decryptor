#!/usr/bin/env python3
"""prepare.py - turn an apiav-era American Pinball game-code .pkg into a
runnable build.

usage: prepare.py PKG [--name NAME] [--force]

A .pkg is [8B size LE][16B IV][AES-256-CBC of a ZIP] - the ZIP holds the
game folder the machine keeps at /game: launcher.py, procgame/, ApiLib/,
<title>/ (source + assets), config/, and the `apiav` binary the OS installs
as /game/hw/apiav.  This decrypts it with PAD-Runtime's openssl (its python
has no AES module), unpacks it to $AV_CACHE/<name>/ and deletes the ZIP; the
.pkg is only read.  <name> defaults to the .pkg's name without "-gamecode"
(bbq_24.07.04).  macOS litter (.DS_Store, ._*, __MACOSX/) is skipped.

A build is ready when it has launcher.py and apiav; `title` in it names the
folder holding the assets (the one with assets/defs/screens.json).
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
AV_ROOT = os.environ.get("AV_ROOT", "/var/tmp/pad_apav")
AV_CACHE = os.path.join(AV_ROOT, "cache")


def ap_key():
    """The universal AP key, read from the app's own AP plugin."""
    ns = {}
    with open(os.path.join(REPO, "pinball_decryptor", "plugins", "ap", "games.py")) as f:
        exec(compile(f.read(), "games.py", "exec"), ns)
    return ns["AP_AES_KEY"]


def decrypt(pkg, out_zip):
    with open(pkg, "rb") as f:
        size = struct.unpack("<Q", f.read(8))[0]
        iv = f.read(16)
    with open(pkg, "rb") as src, open(out_zip, "wb") as dst:
        src.seek(24)
        p = subprocess.Popen(["openssl", "enc", "-d", "-aes-256-cbc", "-nopad",
                              "-K", ap_key().hex(), "-iv", iv.hex()],
                             stdin=src, stdout=dst)
        if p.wait() != 0:
            sys.exit("prepare.py: openssl failed on %s" % pkg)
    os.truncate(out_zip, size)


def litter(name):
    base = name.rstrip("/").rsplit("/", 1)[-1]
    return base == ".DS_Store" or base.startswith("._") or name.startswith("__MACOSX/")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pkg")
    ap.add_argument("--name")
    ap.add_argument("--force", action="store_true", help="unpack again over a finished build")
    a = ap.parse_args()
    name = a.name or os.path.basename(a.pkg).replace("-gamecode", "").rsplit(".pkg", 1)[0]
    out = os.path.join(AV_CACHE, name)
    if os.path.exists(os.path.join(out, "title")) and not a.force:
        print("prepare.py: %s ready (--force to redo)" % out)
        return
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(AV_CACHE, exist_ok=True)
    tmp_zip = out + ".zip"
    decrypt(a.pkg, tmp_zip)
    try:
        with zipfile.ZipFile(tmp_zip) as z:
            names = z.namelist()
            if "launcher.py" not in names or "apiav" not in names:
                sys.exit("prepare.py: %s is not an apiav-era build (no launcher.py + apiav)" % a.pkg)
            for info in z.infolist():
                if litter(info.filename):
                    continue
                z.extract(info, out)
                mode = info.external_attr >> 16
                if mode & 0o111:
                    os.chmod(os.path.join(out, info.filename), mode & 0o777)
    finally:
        os.remove(tmp_zip)
    os.chmod(os.path.join(out, "apiav"), 0o755)
    titles = sorted(d for d in os.listdir(out)
                    if os.path.isfile(os.path.join(out, d, "assets", "defs", "screens.json")))
    if not titles:
        sys.exit("prepare.py: no <title>/assets/defs/screens.json in %s" % out)
    with open(os.path.join(out, "title"), "w") as f:
        f.write(titles[0] + "\n")
    print("prepare.py: %s (title %s)" % (out, titles[0]))


if __name__ == "__main__":
    main()
