"""PAD-223 proof shots: the real Labyrinth pack is Godot 4.4 (format v2).

    python scripts/shot_pad223.py <outdir> <prefix>

The PAD-222 rig (``shot_pad222.py``: cooltoy's Mac with no GDRE Tools,
real gpg/tar in WSL, the Web UI driven by Playwright) with one change: the
synthetic ``GDCraze_linux_20260130.x86_64`` carries the pack the way the
real January 2026 Labyrinth binary does, read off David's own lab.fun:

    GDPC, pack_format_version 2, Godot 4.4.1, pack_flags 2 (REL_FILEBASE),
    file_base 940216, u32 file_count at header offset 96 (8512 entries),
    the directory right after it, file data from file_base.

PAD-222 assumed "Godot 4.5" from games.py and only taught the native
reader format v3, so this pack still went to GDRE Tools.
"""

import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shot_pad222  # noqa: E402


def _v2_pck_binary(files, base=None):
    """A Godot 4.4 binary: 96-byte v2 header, u32 file_count + directory at
    offset 96, data from a 16-aligned file_base (REL_FILEBASE)."""
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
    dir_end = 96 + 4 + len(body)
    base = (dir_end + 15) // 16 * 16
    hdr = bytearray(96)
    hdr[0:4] = b"GDPC"
    struct.pack_into("<I", hdr, 4, 2)
    struct.pack_into("<III", hdr, 8, 4, 4, 1)
    struct.pack_into("<I", hdr, 20, 2)
    struct.pack_into("<Q", hdr, 24, base)
    pck = (bytes(hdr) + struct.pack("<I", len(files)) + bytes(body)
           + b"\x00" * (base - dir_end) + bytes(blob))
    return (b"\x7fELF" + b"\x00" * 508 + pck
            + struct.pack("<Q", len(pck)) + b"GDPC")


shot_pad222._pck_binary = _v2_pck_binary

if __name__ == "__main__":
    shot_pad222.main()
