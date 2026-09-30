#!/usr/bin/env python3
"""prepare.py - turn an American Pinball game-code .pkg into a runnable build.

usage: prepare.py PKG [--name NAME] [--force]

A .pkg is [8B size LE][16B IV][AES-256-CBC of a ZIP of the game folder] - the
folder the machine keeps at /game/<title>.  This decrypts it with the rig
env's openssl (PAD-Runtime's python has no AES module; setup.sh provides
openssl), unpacks it to $AP_CACHE/<name>/ and records which launcher starts
it (`launcher`) and the folder it lives in on the machine (`machine_dir`,
/game/<it>; py/machinedir.py).  The ZIP is deleted afterwards; the .pkg is only read.

<name> defaults to the .pkg's name without "-gamecode" (houdini_21.10.25).
macOS litter (.DS_Store, ._*, __MACOSX/) is skipped.
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
AP_ROOT = os.environ.get("AP_ROOT", "/var/tmp/pad_ap")
AP_CACHE = os.path.join(AP_ROOT, "cache")
OPENSSL = os.path.join(AP_ROOT, "py27", "bin", "openssl")

# The script the machine's xinitrc runs (`cd <its folder>; python2 <it>`);
# the first one present wins.  Oktoberfest keeps it in its game folder, with
# procgame/ and ApiLib/ one level up (its `go` script puts both on the path).
# Hot Wheels' xinitrc runs hotWheels/launcher.py (the top-level one is old).
LAUNCHERS = ("houdini.py", "hotWheels/launcher.py", "launcher.py", "oktoberfest/oktoberfest.py")


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
    key = ap_key()
    with open(pkg, "rb") as src, open(out_zip, "wb") as dst:
        src.seek(24)
        p = subprocess.Popen([OPENSSL, "enc", "-d", "-aes-256-cbc", "-nopad",
                              "-K", key.hex(), "-iv", iv.hex()],
                             stdin=src, stdout=dst)
        if p.wait() != 0:
            sys.exit("prepare.py: openssl failed on %s" % pkg)
    os.truncate(out_zip, size)


def litter(name):
    base = name.rstrip("/").rsplit("/", 1)[-1]
    return base == ".DS_Store" or base.startswith("._") or name.startswith("__MACOSX/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pkg")
    ap.add_argument("--name")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not os.path.exists(OPENSSL):
        sys.exit("prepare.py: no %s - run setup.sh first" % OPENSSL)
    name = a.name or os.path.basename(a.pkg).rsplit(".", 1)[0].replace("-gamecode", "")
    dest = os.path.join(AP_CACHE, name)
    if os.path.exists(os.path.join(dest, "launcher")) and not a.force:
        print("%s: already prepared (--force to redo)" % dest)
        return
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    tmp = dest + ".zip"
    print("decrypting %s ..." % a.pkg, flush=True)
    decrypt(a.pkg, tmp)
    try:
        with zipfile.ZipFile(tmp) as z:
            n = 0
            for i in z.infolist():
                if litter(i.filename) or i.is_dir():
                    continue
                z.extract(i, dest)
                if i.filename.rsplit("/", 1)[-1] == "apiav":     # the zip keeps no modes
                    os.chmod(os.path.join(dest, i.filename), 0o755)
                n += 1
    finally:
        os.remove(tmp)
    launcher = next((l for l in LAUNCHERS if os.path.exists(os.path.join(dest, l))), None)
    if not launcher:
        sys.exit("prepare.py: %s has none of %s" % (dest, ", ".join(LAUNCHERS)))
    # Where it lives on the machine (/game/<dir>): run_game.sh puts it there.
    mdir = subprocess.check_output([os.path.join(AP_ROOT, "py27", "bin", "python2"),
                                    os.path.join(HERE, "py", "machinedir.py"), dest]).decode().strip()
    with open(os.path.join(dest, "machine_dir"), "w") as f:
        f.write(mdir + "\n")
    with open(os.path.join(dest, "launcher"), "w") as f:
        f.write(launcher + "\n")
    print("%s: %d files, launcher %s, on the machine /game/%s" % (dest, n, launcher, mdir))


if __name__ == "__main__":
    main()
