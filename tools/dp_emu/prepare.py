#!/usr/bin/env python3
"""Prepare a Dutch Pinball build for the rig: $DP_CACHE/<name>/.

A runnable game folder is what the machine has in /home/dp/game:

    assets/          the BASE assets (DMD dot sheet, fonts, most sounds)
    <version>/       the program (`start`, a PyInstaller build) and the
                     assets that version changed; the game looks for an
                     asset in <version>/assets first, then ../assets
    version          which <version>/ run.sh starts

The update zips (TBL-v1.00.zip ...) carry only a <version>/ folder, and
not a whole one: the machine's updater copies the INSTALLED version folder
and lays the zip over it (a zip's <version>/delta lists the versions it may
be laid over), so each version folder on a machine holds files that no zip
does (1.10 on one image: 173 of them), and ~1,400 base assets are in no zip
at all.  So a build always starts from a machine's disk image:

    prepare.py image <disk.img> [--name N] [--all]
        the current <version>/ folder (--all: every one) and the base
        assets off the image's /home/dp/game (read-only loop mount, as root)

    prepare.py zip <update.zip> [...] --base <prepared image build> [--name N]
        the base build's current version folder with the updates laid over
        it in version order, as the machine installs them; each must list
        the version it lands on.  The base assets are the base build's.

Run as root in PAD-Runtime.  Prints the prepared folder.
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.environ.get("DP_ROOT", "/var/tmp/pad_dp")
CACHE = os.path.join(ROOT, "cache")


def die(msg):
    print("prepare.py: " + msg, file=sys.stderr)
    sys.exit(2)


def partitions(img):
    """(start_byte, size_bytes) of every partition in an MBR or GPT image."""
    with open(img, "rb") as f:
        mbr = f.read(512)
        if mbr[510:512] != b"\x55\xaa":
            return [(0, os.path.getsize(img))]      # a bare filesystem
        ents = [struct.unpack_from("<B3xB3xII", mbr, 446 + 16 * i) for i in range(4)]
        if any(e[1] == 0xEE for e in ents):         # protective MBR -> GPT
            f.seek(512)
            hdr = f.read(92)
            lba, count, esize = struct.unpack_from("<QII", hdr, 72)
            f.seek(lba * 512)
            out = []
            for _ in range(count):
                e = f.read(esize)
                first, last = struct.unpack_from("<QQ", e, 32)
                if e[:16] != b"\0" * 16:
                    out.append((first * 512, (last - first + 1) * 512))
            return out
        return [(e[2] * 512, e[3] * 512) for e in ents if e[1] and e[3]]


def find_game(mnt):
    for rel in ("dp/game", "home/dp/game"):
        g = os.path.join(mnt, rel)
        if os.path.isfile(os.path.join(g, "version")):
            return g
    return None


def version_dirs(game):
    return sorted(d for d in os.listdir(game)
                  if os.path.isfile(os.path.join(game, d, "start")))


def copy_clean(src, dst):
    """Copy a tree, leaving out macOS AppleDouble '._*' files (junk some
    images carry; the game's loaders trip over them)."""
    shutil.copytree(src, dst, symlinks=True,
                    ignore=lambda d, names: [n for n in names if n.startswith("._")])


def from_image(img, name, every):
    if os.geteuid() != 0:
        die("run as root (it loop-mounts the image)")
    out = os.path.join(CACHE, name)
    for start, size in partitions(img):
        mnt = tempfile.mkdtemp(prefix="dpimg")
        r = subprocess.run(["mount", "-o", "ro,noload,loop,offset=%d,sizelimit=%d"
                            % (start, size), img, mnt],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            os.rmdir(mnt)
            continue
        try:
            game = find_game(mnt)
            if not game:
                continue
            vers = version_dirs(game)
            cur = open(os.path.join(game, "version")).read().strip()
            if cur not in vers:
                cur = vers[-1]
            if os.path.exists(out):
                shutil.rmtree(out)
            os.makedirs(out)
            copy_clean(os.path.join(game, "assets"), os.path.join(out, "assets"))
            for v in (vers if every else [cur]):
                copy_clean(os.path.join(game, v), os.path.join(out, v))
            with open(os.path.join(out, "version"), "w") as f:
                f.write(cur)
            print("versions %s, current %s" % (" ".join(vers), cur), file=sys.stderr)
            return out
        finally:
            subprocess.run(["umount", mnt])
            os.rmdir(mnt)
    die("no /home/dp/game on any partition of " + img)


def vkey(v):
    return tuple(int(p) if p.isdigit() else p for p in v.split("."))


def zip_version(path):
    """(version, [compatible versions]) - the zip's top folder and its
    <version>/delta marker ('' for none)."""
    with zipfile.ZipFile(path) as z:
        top = sorted({n.split("/")[0] for n in z.namelist() if "/" in n})
        if len(top) != 1:
            die("%s: expected one top folder, found %s" % (path, top))
        v = top[0]
        try:
            compat = z.read(v + "/delta").decode().strip()
        except KeyError:
            compat = ""
    return v, [c for c in compat.split(",") if c]


def extract_into(path, zver, dest):
    """Unpack <zver>/... of a zip into dest/ (the version prefix dropped),
    replacing what is there."""
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            rel = info.filename[len(zver) + 1:]
            if not rel or rel == "delta" or info.is_dir():
                continue
            if rel.startswith("/") or ".." in rel.split("/"):
                die("%s: unsafe entry %s" % (path, info.filename))
            if os.path.basename(rel).startswith("._"):
                continue
            target = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.lexists(target):
                os.remove(target)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            mode = info.external_attr >> 16
            os.chmod(target, (mode & 0o777) or 0o644)


def from_zips(zips, base, name):
    cur = open(os.path.join(base, "version")).read().strip()
    chain = sorted((zip_version(z) + (z,) for z in zips), key=lambda t: vkey(t[0]))
    for zv, compat, z in chain:
        if compat and cur not in compat:
            die("%s installs onto %s, not %s" % (os.path.basename(z), ",".join(compat), cur))
        cur = zv
    cur = open(os.path.join(base, "version")).read().strip()
    top = chain[-1][0]
    out = os.path.join(CACHE, name)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    vdir = os.path.join(out, top)
    # Hard-linked copy of the installed folder; extract_into unlinks before
    # it writes, so the base build is never changed through a shared inode.
    subprocess.run(["cp", "-al", os.path.join(base, cur), vdir], check=True)
    for zv, compat, z in chain:
        extract_into(z, zv, vdir)
        print("laid %s over %s" % (zv, cur), file=sys.stderr)
        cur = zv
    os.chmod(os.path.join(vdir, "start"), 0o755)
    os.symlink(os.path.join(base, "assets"), os.path.join(out, "assets"))
    with open(os.path.join(out, "version"), "w") as f:
        f.write(top)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("image")
    a.add_argument("img")
    a.add_argument("--name")
    a.add_argument("--all", action="store_true", help="every version folder, not just the current one")
    b = sub.add_parser("zip")
    b.add_argument("zips", nargs="+")
    b.add_argument("--base", required=True,
                   help="a prepared image build (its assets/ are the base)")
    b.add_argument("--name")
    args = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    if args.cmd == "image":
        name = args.name or os.path.splitext(os.path.basename(args.img))[0]
        out = from_image(args.img, name, args.all)
    else:
        base = args.base if os.path.isabs(args.base) else os.path.join(CACHE, args.base)
        if not os.path.isdir(os.path.join(base, "assets")):
            die("--base %s has no assets/ (prepare an image first)" % base)
        top = max((zip_version(z)[0] for z in args.zips), key=vkey)
        name = args.name or "zip-" + top
        out = from_zips(args.zips, os.path.realpath(base), name)
    print(out)


if __name__ == "__main__":
    main()
