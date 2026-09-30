#!/usr/bin/env python3
"""prepare.py - turn a Spooky P-ROC game-code .pkg (Rick and Morty, Alice
Cooper's Nightmare Castle) into a runnable build.

usage: prepare.py PKG [--name NAME] [--force]

A .pkg is [8B size LE][16B IV][AES-256-CBC of a ZIP]; the ZIP is the game
folder the machine keeps at /game/RickAndMorty (Rick and Morty) or
/game/code (Alice Cooper): the game's Python 2.7 bytecode, its own copy of
procgame (SkeletonGame), config/ and assets/ - and for Alice Cooper the
Unity player that draws its screen (uptest/).  This decrypts it with
PAD-Runtime's openssl (its python has no AES module) using the app's own
keys (plugins/spooky/games.py), unpacks it to $SPP_CACHE/<name>/ and deletes
the ZIP; the .pkg is only read.

<name> defaults to <title>_<version>: rm_20220902 (the date in the file
name), ac_<the newest WHATSNEW.txt version>.  `title` in the build says
which game it is (rm | ac).  Total Nuclear Annihilation's key is not known
(exit 4).
"""
import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SPP_ROOT = os.environ.get("SPP_ROOT", "/var/tmp/pad_spkproc")
SPP_CACHE = os.path.join(SPP_ROOT, "cache")

# title: (the .pkg name's prefix, the key's name in games.py, a file only
# that game's ZIP has)
TITLES = {
    "rm": ("rm-gamecode", "RM_AES_KEY", "RMGame.pyc"),
    "ac": ("ac-gamecode", "AC_AES_KEY", "ACGame.py"),
}


def keys():
    """The .pkg keys, read from the app's own Spooky plugin."""
    ns = {}
    with open(os.path.join(REPO, "pinball_decryptor", "plugins", "spooky", "games.py")) as f:
        exec(compile(f.read(), "games.py", "exec"), ns)
    return ns


def title_of(pkg):
    base = os.path.basename(pkg).lower()
    for title, (prefix, _, _) in TITLES.items():
        if base.startswith(prefix):
            return title
    if base.startswith("tna-gamecode"):
        print("prepare.py: Total Nuclear Annihilation's .pkg key is not known", file=sys.stderr)
        sys.exit(4)
    print("prepare.py: not a Spooky P-ROC game-code .pkg (rm-gamecode*, ac-gamecode*): %s" % pkg,
          file=sys.stderr)
    sys.exit(4)


def decrypt(pkg, out_zip, key):
    with open(pkg, "rb") as f:
        size = struct.unpack("<Q", f.read(8))[0]
        iv = f.read(16)
    with open(pkg, "rb") as src, open(out_zip, "wb") as dst:
        src.seek(24)
        p = subprocess.Popen(["openssl", "enc", "-d", "-aes-256-cbc", "-nopad",
                              "-K", key.hex(), "-iv", iv.hex()],
                             stdin=src, stdout=dst)
        if p.wait() != 0:
            sys.exit("prepare.py: openssl failed on %s" % pkg)
    os.truncate(out_zip, size)


def version(title, pkg, out):
    if title == "rm":
        m = re.search(r"(\d{8})", os.path.basename(pkg))
        return m.group(1) if m else "0"
    # Alice Cooper's WHATSNEW.txt opens with its newest version ("v1.23 ...").
    try:
        with open(os.path.join(out, "WHATSNEW.txt"), errors="replace") as f:
            m = re.search(r"[vV](?:ersion)?\s*(\d+(?:\.\d+)+)", f.read())
            if m:
                return m.group(1)
    except OSError:
        pass
    return "0"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pkg")
    ap.add_argument("--name")
    ap.add_argument("--force", action="store_true", help="unpack again over a finished build")
    a = ap.parse_args()
    title = title_of(a.pkg)
    _, key_name, marker = TITLES[title]
    os.makedirs(SPP_CACHE, exist_ok=True)
    # Unpacked under a scratch name first: the version is read from the ZIP.
    tmp = os.path.join(SPP_CACHE, ".unpack-%s-%d" % (title, os.getpid()))
    if a.name and os.path.exists(os.path.join(SPP_CACHE, a.name, "title")) and not a.force:
        print("prepare.py: %s ready (--force to redo)" % os.path.join(SPP_CACHE, a.name))
        return
    shutil.rmtree(tmp, ignore_errors=True)
    tmp_zip = tmp + ".zip"
    decrypt(a.pkg, tmp_zip, keys()[key_name])
    try:
        with zipfile.ZipFile(tmp_zip) as z:
            if marker not in z.namelist():
                sys.exit("prepare.py: %s has no %s - not the game its name says" % (a.pkg, marker))
            for info in z.infolist():
                z.extract(info, tmp)
                mode = info.external_attr >> 16
                if mode & 0o111:
                    os.chmod(os.path.join(tmp, info.filename), mode & 0o777)
    except zipfile.BadZipFile:
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit("prepare.py: %s did not decrypt to a ZIP (wrong key?)" % a.pkg)
    finally:
        os.remove(tmp_zip)
    # Alice Cooper's archive carries no execute bits on its Unity player.
    for exe in ("uptest/main.x86_64",):
        if os.path.exists(os.path.join(tmp, exe)):
            os.chmod(os.path.join(tmp, exe), 0o755)
    name = a.name or "%s_%s" % (title, version(title, a.pkg, tmp))
    out = os.path.join(SPP_CACHE, name)
    if os.path.exists(os.path.join(out, "title")) and not a.force:
        shutil.rmtree(tmp, ignore_errors=True)
        print("prepare.py: %s ready (--force to redo)" % out)
        return
    shutil.rmtree(out, ignore_errors=True)
    with open(os.path.join(tmp, "title"), "w") as f:
        f.write(title + "\n")
    os.rename(tmp, out)
    print("prepare.py: %s (title %s)" % (out, title))


if __name__ == "__main__":
    main()
