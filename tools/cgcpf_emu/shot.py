#!/usr/bin/env python3
"""shot.py [--front] <out.png> [fb.bin] - the picture on Pulp Fiction's
HDMI output now.

pfshim.c keeps the game's DRM dumb buffers in $CGCPF_RIG/io/fb.bin: a 4 KiB
"PFFB" header (width, height, pitch, bpp, the on-screen buffer's offset,
the flip count, the buffers' count and offsets), then the buffers.  The
game draws RGB565.

The HDMI output is the game's service monitor, and it paints that page a
slice at a time into its three buffers in turn, so any one buffer holds
part of it; a monitor shows the three in quick succession and a person sees
the whole page.  So the picture is the three laid over each other (a pixel
lit in any of them is lit, the one on screen winning); --front takes the
on-screen buffer alone.
"""
import os
import struct
import sys
import zlib


def read_frames(path, front_only=False):
    """(w, h, pitch, bpp, flips, raw): raw is the picture's bytes."""
    with open(path, "rb") as f:
        hdr = f.read(4096)
        if hdr[:4] != b"PFFB":
            raise SystemExit("shot.py: %s is not a Pulp Fiction frame buffer" % path)
        w, h, pitch, bpp, front, flips, nbuf = struct.unpack_from("<7I", hdr, 4)
        offs = struct.unpack_from("<8I", hdr, 32)[:min(nbuf, 8)]
        if not front or not w:
            raise SystemExit("shot.py: nothing on screen yet")
        f.seek(front)
        raw = f.read(pitch * h)
        if front_only or bpp != 16:
            return w, h, pitch, bpp, flips, raw
        pix = list(struct.unpack("<%dH" % (len(raw) // 2), raw))
        for off in offs:
            if off == front:
                continue
            f.seek(off)
            other = struct.unpack("<%dH" % (len(raw) // 2), f.read(pitch * h))
            pix = [a or b for a, b in zip(pix, other)]
    return w, h, pitch, bpp, flips, struct.pack("<%dH" % len(pix), *pix)


def to_rgb(w, h, pitch, bpp, raw):
    rows = []
    for y in range(h):
        line = raw[y * pitch:y * pitch + w * (bpp // 8)]
        out = bytearray(w * 3)
        if bpp == 16:
            px = struct.unpack("<%dH" % w, line)
            for x, v in enumerate(px):
                r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
                out[3 * x] = (r << 3) | (r >> 2)
                out[3 * x + 1] = (g << 2) | (g >> 4)
                out[3 * x + 2] = (b << 3) | (b >> 2)
        else:  # XRGB8888
            for x in range(w):
                out[3 * x + 2], out[3 * x + 1], out[3 * x] = line[4 * x:4 * x + 3]
        rows.append(bytes(out))
    return rows


def png(path, w, h, rows):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    body = b"".join(b"\0" + r for r in rows)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(body, 6)) + chunk(b"IEND", b""))
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def lit_fraction(rows):
    """Share of pixels that are not black: 0 = blank screen."""
    lit = total = 0
    for r in rows[::8]:
        for x in range(0, len(r), 24):
            total += 1
            lit += (r[x] | r[x + 1] | r[x + 2]) > 24
    return lit / max(total, 1)


def main():
    args = [a for a in sys.argv[1:] if a != "--front"]
    if not args:
        raise SystemExit(__doc__)
    fb = args[1] if len(args) > 1 else os.path.join(
        os.environ.get("CGCPF_RIG", "/var/tmp/pad_cgcpf/rig%s" % os.environ.get("PAD_SLOT", "0")),
        "io", "fb.bin")
    w, h, pitch, bpp, flips, raw = read_frames(fb, "--front" in sys.argv)
    rows = to_rgb(w, h, pitch, bpp, raw)
    png(args[0], w, h, rows)
    print("%s %dx%d flips=%d lit=%.3f" % (args[0], w, h, flips, lit_fraction(rows)))


if __name__ == "__main__":
    main()
