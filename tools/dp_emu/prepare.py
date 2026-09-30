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

    prepare.py image <disk.img> [--name N] [--all] [--keep K]
        the current <version>/ folder (--all: every one) and the base
        assets off the image's /home/dp/game (read-only loop mount, as root).
        Cached: an image already prepared (same size and time) is reused.
        --keep K prunes older image builds (and their zip builds) to K.

        Alice's Adventures in Wonderland ships as a Clonezilla installer
        instead: the game SSD's root is a partclone + zstd image inside it
        (pinball-image/sda2.ext4-ptcl-img.zst).  That is restored whole to
        <name>/root.ext4 (kind "aaiw"; run_aaiw.sh runs it) - the game is
        a native program that wants its own root, not a folder.

    prepare.py zip <update.zip> [...] --base <prepared image build> [--name N]
        the base build's current version folder with the updates laid over
        it in version order, as the machine installs them; each must list
        the version it lands on.  The base assets are the base build's.

Run as root in PAD-Runtime.  Prints `progress N` lines while it copies and
the prepared folder last.  A build is made in <name>.partial and renamed
when whole, so a cancelled one is never mistaken for a build.
Exit: 2 bad input, 3 not enough free space, 4 no Dutch Pinball game on
the image, 5 an update that does not install onto the build.
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


def die(msg, code=2):
    print("prepare.py: " + msg, file=sys.stderr)
    sys.exit(code)


def stamp_of(path):
    st = os.stat(path)
    return "%s %d %d" % (os.path.realpath(path), st.st_size, int(st.st_mtime))


def tree_size(top):
    total = 0
    for d, _dirs, files in os.walk(top):
        for n in files:
            try:
                total += os.lstat(os.path.join(d, n)).st_size
            except OSError:
                pass
    return total


class Progress:
    """`progress N` on stdout each whole percent of `total` bytes copied."""

    def __init__(self, total):
        self.total, self.done, self.last = max(total, 1), 0, -1

    def add(self, n):
        self.done += n
        pct = min(100, self.done * 100 // self.total)
        if pct != self.last:
            self.last = pct
            print("progress %d" % pct, flush=True)


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


def copy_clean(src, dst, progress=None):
    """Copy a tree, leaving out macOS AppleDouble '._*' files (junk some
    images carry; the game's loaders trip over them)."""
    def copy(a, b):
        shutil.copy2(a, b)
        if progress is not None:
            progress.add(os.path.getsize(a))
    shutil.copytree(src, dst, symlinks=True, copy_function=copy,
                    ignore=lambda d, names: [n for n in names if n.startswith("._")])


def running_builds():
    out = set()
    for d in os.listdir(ROOT) if os.path.isdir(ROOT) else ():
        try:
            with open(os.path.join(ROOT, d, "build")) as f:
                out.add(os.path.realpath(f.read().strip()))
        except OSError:
            pass
    return out


def unmount_lower(build):
    """An AAIW build's root.ext4 stays loop-mounted (read-only) as every
    rig's overlay lower layer; let it go before the build is deleted.
    False when it is still in use."""
    lower = os.path.join(ROOT, "lower", os.path.basename(build))
    if os.path.ismount(lower):
        if subprocess.run(["umount", lower], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode != 0:
            return False
    if os.path.isdir(lower):
        os.rmdir(lower)
    return True


def prune(keep, spare):
    """Keep the `keep` newest image builds (and the zip builds laid over
    them); never `spare`, the one just made, or one a rig is running."""
    running = running_builds()
    images = []
    for n in os.listdir(CACHE):
        path = os.path.join(CACHE, n)
        if os.path.isfile(os.path.join(path, "source")) and not n.endswith(".partial"):
            images.append((os.path.getmtime(os.path.join(path, "source")), path))
    images.sort(reverse=True)
    for _t, path in images[keep:]:
        if path == spare or path in running or not unmount_lower(path):
            continue
        for n in os.listdir(CACHE):          # its zip builds point into it
            z = os.path.join(CACHE, n)
            if (z != path and z not in running and os.path.realpath(
                    os.path.join(z, "assets")) == os.path.join(path, "assets")):
                shutil.rmtree(z, ignore_errors=True)
        shutil.rmtree(path, ignore_errors=True)
        print("pruned %s" % os.path.basename(path), file=sys.stderr)


def from_image(img, name, every, keep=0):
    if os.geteuid() != 0:
        die("run as root (it loop-mounts the image)")
    out = os.path.join(CACHE, name)
    stamp = stamp_of(img)
    try:
        with open(os.path.join(out, "source")) as f:
            if f.read().strip() == stamp:
                print("cached %s" % name, file=sys.stderr)
                os.utime(os.path.join(out, "source"))
                return out
    except OSError:
        pass
    part = out + ".partial"
    for start, size in partitions(img):
        mnt = tempfile.mkdtemp(prefix="mnt-", dir=ROOT)
        r = subprocess.run(["mount", "-o", "ro,noload,loop,offset=%d,sizelimit=%d"
                            % (start, size), img, mnt],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            os.rmdir(mnt)
            continue
        try:
            game = find_game(mnt)
            if not game:
                zst = find_clonezilla_root(mnt)
                if not zst:
                    continue
                shutil.rmtree(part, ignore_errors=True)
                from_clonezilla(img, zst, part, stamp)
                if os.path.exists(out):
                    unmount_lower(out)
                    shutil.rmtree(out)
                os.rename(part, out)
                print("%s %s" % (AAIW_TITLE, aaiw_version(img)), file=sys.stderr)
                if keep:
                    prune(keep, out)
                return out
            vers = version_dirs(game)
            if not vers:
                continue
            with open(os.path.join(game, "version")) as f:
                cur = f.read().strip()
            if cur not in vers:
                cur = vers[-1]
            srcs = ["assets"] + (vers if every else [cur])
            need = sum(tree_size(os.path.join(game, d)) for d in srcs)
            shutil.rmtree(part, ignore_errors=True)
            if os.path.exists(out) and out not in running_builds():
                shutil.rmtree(out)
            free = shutil.disk_usage(CACHE).free
            if free < need + (1 << 30):
                die("the build needs %.1f GB; %.1f GB free in the app's Linux"
                    % (need / 1e9, free / 1e9), 3)
            os.makedirs(part)
            prog = Progress(need)
            for d in srcs:
                copy_clean(os.path.join(game, d), os.path.join(part, d), prog)
            with open(os.path.join(part, "version"), "w") as f:
                f.write(cur)
            with open(os.path.join(part, "title"), "w") as f:
                f.write(machine_title(os.path.join(part, cur)))
            with open(os.path.join(part, "source"), "w") as f:
                f.write(stamp)
            if os.path.exists(out):
                shutil.rmtree(out)
            os.rename(part, out)
            print("versions %s, current %s" % (" ".join(vers), cur), file=sys.stderr)
            if keep:
                prune(keep, out)
            return out
        finally:
            subprocess.run(["umount", mnt])
            os.rmdir(mnt)
    die("no Dutch Pinball game (/home/dp/game) on any partition of " + img, 4)


AAIW_TITLE = "Alice's Adventures in Wonderland"


def find_clonezilla_root(mnt):
    """The partclone image of a Clonezilla backup's ext4 root partition
    (the larger one if there are several), or None."""
    best = None
    for d in (mnt, *(os.path.join(mnt, n) for n in sorted(os.listdir(mnt)))):
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if n.endswith(".ext4-ptcl-img.zst"):
                f = os.path.join(d, n)
                if best is None or os.path.getsize(f) > os.path.getsize(best):
                    best = f
    return best


def restore_partclone(zst, raw):
    """zstd -dc <zst> | partclone.restore -W: a raw ext4 file.  Progress is
    the share of the compressed stream fed so far."""
    size = os.path.getsize(zst)
    prog = Progress(size)
    z = subprocess.Popen(["zstd", "-dc"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    pc = subprocess.Popen(["partclone.restore", "-C", "-W", "-s", "-", "-O", raw],
                          stdin=z.stdout, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
    z.stdout.close()
    try:
        with open(zst, "rb") as f:
            while True:
                chunk = f.read(4 << 20)
                if not chunk:
                    break
                z.stdin.write(chunk)
                prog.add(len(chunk))
        z.stdin.close()
    except BrokenPipeError:
        pass
    rz, rp = z.wait(), pc.wait()
    return rz == 0 and rp == 0


def aaiw_version(img):
    """"1.05" from AAIW_1.05_full_image.img; "" when the name says none."""
    import re
    m = re.search(r"(\d+\.\d+)", os.path.basename(img))
    return m.group(1) if m else ""


def from_clonezilla(img, zst, part, stamp):
    """Restore an AAIW installer's game root into part/root.ext4 and check
    it is AAIW (its program and assets are where the game looks)."""
    need = int(os.path.getsize(zst) * 2.5)          # ~7 GB used of 8.5
    free = shutil.disk_usage(CACHE).free
    if free < need + (1 << 30):
        die("the game needs about %.1f GB; %.1f GB free in the app's Linux"
            % (need / 1e9, free / 1e9), 3)
    os.makedirs(part)
    raw = os.path.join(part, "root.ext4")
    if not restore_partclone(zst, raw):
        die("could not restore the game's disk from " + os.path.basename(zst), 4)
    look = tempfile.mkdtemp(prefix="mnt-", dir=ROOT)
    try:
        ok = subprocess.run(["mount", "-o", "ro,loop,noload", raw, look],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode == 0
        is_aaiw = ok and os.path.isfile(os.path.join(look, "opt", "pinterface")) \
            and os.path.isdir(os.path.join(look, "opt", "assets", "alice"))
    finally:
        subprocess.run(["umount", look], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        os.rmdir(look)
    if not is_aaiw:
        die("the disk inside %s is not a Dutch Pinball game this emulator "
            "knows" % os.path.basename(img), 4)
    for n, v in (("kind", "aaiw"), ("title", AAIW_TITLE),
                 ("version", aaiw_version(img)), ("source", stamp)):
        with open(os.path.join(part, n), "w") as f:
            f.write(v)


def machine_title(vdir):
    """The game's name from its machine.yaml's first comment line ("# The
    Big Lebowski Pinball machine configuration"), else the folder's."""
    try:
        with open(os.path.join(vdir, "config", "machine.yaml"), encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") and len(line) > 2:
                    t = line.lstrip("# ").strip()
                    for tail in (" machine configuration", " configuration"):
                        if t.lower().endswith(tail):
                            t = t[:-len(tail)]
                    return t.strip() or os.path.basename(vdir)
                if line:
                    break
    except OSError:
        pass
    return os.path.basename(os.path.dirname(vdir))


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
            die("%s installs onto %s, not %s" % (os.path.basename(z), ",".join(compat), cur), 5)
        cur = zv
    cur = open(os.path.join(base, "version")).read().strip()
    top = chain[-1][0]
    out = os.path.join(CACHE, name)
    part = out + ".partial"
    shutil.rmtree(part, ignore_errors=True)
    os.makedirs(part)
    vdir = os.path.join(part, top)
    # Hard-linked copy of the installed folder; extract_into unlinks before
    # it writes, so the base build is never changed through a shared inode.
    subprocess.run(["cp", "-al", os.path.join(base, cur), vdir], check=True)
    for zv, compat, z in chain:
        extract_into(z, zv, vdir)
        print("laid %s over %s" % (zv, cur), file=sys.stderr)
        cur = zv
    os.chmod(os.path.join(vdir, "start"), 0o755)
    os.symlink(os.path.join(base, "assets"), os.path.join(part, "assets"))
    with open(os.path.join(part, "version"), "w") as f:
        f.write(top)
    with open(os.path.join(part, "title"), "w") as f:
        f.write(machine_title(vdir))
    if os.path.exists(out):
        shutil.rmtree(out)
    os.rename(part, out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("image")
    a.add_argument("img")
    a.add_argument("--name")
    a.add_argument("--all", action="store_true", help="every version folder, not just the current one")
    a.add_argument("--keep", type=int, default=0, help="prune older image builds to this many")
    b = sub.add_parser("zip")
    b.add_argument("zips", nargs="+")
    b.add_argument("--base", required=True,
                   help="a prepared image build (its assets/ are the base)")
    b.add_argument("--name")
    args = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    if args.cmd == "image":
        name = args.name or os.path.splitext(os.path.basename(args.img))[0]
        if not os.path.isfile(args.img):
            die("no such image: " + args.img)
        out = from_image(args.img, name, args.all, args.keep)
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
