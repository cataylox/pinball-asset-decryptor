#!/usr/bin/env python3
"""prepare.py <image> [cache] - carve Pulp Fiction's root filesystem out of
CGC's card image, once, for run_game.sh.

CGC ships Pulp Fiction as a BeagleBone SD-card "installer": a small boot
partition, and an ext4 partition holding /emmc.img - the image the installer
writes to the board's eMMC.  The game runs from that eMMC image's second
partition (Ubuntu 12.10, the game in /home/ubuntu/pin).  So the rootfs is a
partition inside a file inside a partition; /emmc.img is fragmented, so this
reads it through its ext4 extent map (debugfs), and writes the rootfs as a
sparse <cache>/<build>/rootfs.img that run_game.sh mounts read-only.

An image that is itself the eMMC image (no /emmc.img) is taken as it is.
Only Pulp Fiction is taken: the WPC remakes and Cactus Canyon run CGC's
PinMAME-based program (another rig); anything without /home/ubuntu/pin/pin
exits 4.

Prints the build folder.  Needs debugfs (e2fsprogs).
"""
import os
import re
import struct
import subprocess
import sys

BS_CHUNK = 1 << 20


def debugfs(img, offset, cmd):
    r = subprocess.run(["debugfs", "-R", cmd, "%s?offset=%d" % (img, offset)],
                       capture_output=True, text=True)
    return r.stdout


def partitions(read):
    mbr = read(0, 512)
    if mbr[510:512] != b"\x55\xaa":
        return []
    out = []
    for i in range(4):
        e = mbr[0x1BE + 16 * i:0x1CE + 16 * i]
        start, count = struct.unpack("<II", e[8:16])
        if count:
            out.append((i + 1, e[4], start * 512, count * 512))
    return out


def extents(img, offset, path):
    """[(logical_first, logical_last, physical_first)] in fs blocks, and
    the block size, for <path> in the ext fs at <offset> of <img>."""
    bs = 4096
    m = re.search(r"Block size:\s+(\d+)", debugfs(img, offset, "stats"))
    if m:
        bs = int(m.group(1))
    out = []
    rows = debugfs(img, offset, "dump_extents " + path).splitlines()
    depth = 0
    for line in rows:
        m = re.match(r"\s*(\d+)/\s*(\d+)\s", line)
        if m:
            depth = max(depth, int(m.group(2)))
    for line in rows:
        m = re.match(r"\s*(\d+)/\s*(\d+)\s+\d+/\s*\d+\s+(\d+)\s*-\s*(\d+)\s+(\d+)\s*-\s*(\d+)\s+\d+\s*(\S*)",
                     line)
        if m and int(m.group(1)) == depth and "Uninit" not in m.group(7):
            out.append((int(m.group(3)), int(m.group(4)), int(m.group(5))))
    return out, bs


class Nested:
    """A file inside an ext fs inside an image, read through its extents."""

    def __init__(self, img, fs_offset, path):
        self.f = open(img, "rb")
        self.base = fs_offset
        self.ext, self.bs = extents(img, fs_offset, path)
        if not self.ext:
            raise SystemExit("prepare.py: no extents for %s" % path)

    def read(self, off, n):
        out = bytearray()
        while n > 0:
            lb = off // self.bs
            within = off % self.bs
            e = next((x for x in self.ext if x[0] <= lb <= x[1]), None)
            if e is None:                       # a hole: zeros to the next extent
                nxt = min((x[0] for x in self.ext if x[0] > lb), default=lb + 1)
                take = min(n, (nxt - lb) * self.bs - within)
                out += bytes(take)
            else:
                take = min(n, (e[1] - lb + 1) * self.bs - within)
                self.f.seek(self.base + (e[2] + lb - e[0]) * self.bs + within)
                out += self.f.read(take)
            off += take
            n -= take
        return bytes(out)


class Plain:
    def __init__(self, img):
        self.f = open(img, "rb")

    def read(self, off, n):
        self.f.seek(off)
        return self.f.read(n)


def find_emmc(img):
    """The eMMC image, as something with read(off, n)."""
    plain = Plain(img)
    for _, ptype, off, _ in partitions(plain.read):
        if ptype == 0x83 and "Inode:" in debugfs(img, off, "stat /emmc.img"):
            return Nested(img, off, "/emmc.img"), "installer partition at %d" % off
    return plain, "the image itself"


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    img = os.path.abspath(argv[0])
    here = os.path.dirname(os.path.abspath(__file__))
    cache = argv[1] if len(argv) > 1 else subprocess.run(
        ["bash", "-c", '. "%s/cgcpfpath.sh"; echo "$CGCPF_CACHE"' % here],
        capture_output=True, text=True).stdout.strip()
    name = re.sub(r"(Installer)?\.img$", "", os.path.basename(img), flags=re.I)
    out_dir = os.path.join(cache, name)
    out = os.path.join(out_dir, "rootfs.img")
    if os.path.exists(os.path.join(out_dir, ".ready")):
        print(out_dir)
        return
    emmc, where = find_emmc(img)
    parts = [p for p in partitions(emmc.read) if p[1] == 0x83]
    if not parts:
        raise SystemExit("prepare.py: no Linux partition in the eMMC image (%s)" % where)
    os.makedirs(out_dir, exist_ok=True)
    # the rootfs: the Linux partition with the game in it (p2 on Pulp Fiction)
    for num, _, off, size in parts:
        sys.stderr.write("prepare.py: carving partition %d (%d MB) from %s\n"
                         % (num, size >> 20, where))
        with open(out + ".tmp", "wb") as o:
            done = 0
            while done < size:
                n = min(BS_CHUNK, size - done)
                chunk = emmc.read(off + done, n)
                if chunk.count(0) == len(chunk):
                    o.seek(n, 1)                      # keep it sparse
                else:
                    o.write(chunk)
                done += n
            o.truncate(size)
        if "Inode:" in debugfs(out + ".tmp", 0, "stat /home/ubuntu/pin/pin"):
            os.replace(out + ".tmp", out)
            break
        os.remove(out + ".tmp")
    else:
        os.rmdir(out_dir) if not os.listdir(out_dir) else None
        sys.stderr.write("prepare.py: no /home/ubuntu/pin/pin: not Pulp Fiction "
                         "(the WPC remakes and Cactus Canyon are another rig)\n")
        sys.exit(4)
    with open(os.path.join(out_dir, ".pad_source"), "w") as f:
        f.write(img + "\n")
    with open(os.path.join(out_dir, ".ready"), "w") as f:
        f.write("")
    print(out_dir)


if __name__ == "__main__":
    main(sys.argv[1:])
