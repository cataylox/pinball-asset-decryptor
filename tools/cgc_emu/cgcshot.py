#!/usr/bin/env python3
"""cgcshot.py <fb file> <out.png> [--scale N] - the picture a Chicago Gaming
game shows now, from the frame buffer file cgcshim.so draws into ($CGC_FB).

The file is one header page (cgcshim.c, struct fbhdr: "CGCF", width, height,
pitch, bpp, front, frames, nbuf, bufsize, offsets) and the game's RGB565
buffers; `front` names the one on screen.  Pure python (zlib), so it runs in
any rig distro: no PIL, no numpy.
"""
import struct
import sys
import zlib


def read_front(path):
    with open(path, "rb") as f:
        hdr = f.read(4096)
        if hdr[:4] != b"CGCF":
            raise SystemExit("cgcshot: %s is not a CGC frame buffer (yet)" % path)
        w, h, pitch, bpp, front, frames, nbuf, bufsize = struct.unpack_from("<8I", hdr, 4)
        offsets = struct.unpack_from("<%dI" % nbuf, hdr, 36)
        f.seek(offsets[front])
        data = f.read(pitch * h)
    return w, h, pitch, frames, data


def rgb565_rows(w, h, pitch, data, scale=1):
    """RGB888 rows (bytes), every `scale`-th pixel of every `scale`-th row."""
    # 64 Ki entry lookup: a 16-bit pixel to its three bytes
    lut = [bytes(((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31))
           for v in range(65536)]
    for y in range(0, h, scale):
        row = data[y * pitch:y * pitch + w * 2]
        px = struct.unpack("<%dH" % w, row)[::scale]
        yield b"".join(lut[v] for v in px)


def write_png(path, w, h, rows):
    raw = b"".join(b"\0" + r for r in rows)

    def chunk(kind, body):
        c = struct.pack(">I", len(body)) + kind + body
        return c + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def main(argv):
    if len(argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    scale = 1
    if "--scale" in argv:
        scale = max(1, int(argv[argv.index("--scale") + 1]))
    w, h, pitch, frames, data = read_front(argv[1])
    ow, oh = (w + scale - 1) // scale, (h + scale - 1) // scale
    write_png(argv[2], ow, oh, rgb565_rows(w, h, pitch, data, scale))
    print("%s: %dx%d, frame %d" % (argv[2], ow, oh, frames))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
