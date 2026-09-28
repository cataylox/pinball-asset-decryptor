#!/usr/bin/env python3
"""coilcount.py - how often each coil fired, BY NAME, from [nbts] lines on stdin.

    grep -a '^\\[nbts\\]' gzwatch.log | python3 coilcount.py [--game G] [--min N]

PAD-248. motorcheck.sh counted `cmd 40` on one node, which is enough when the
coil is already known and useless for the question "does this title retry any
device from Start". A coil the game keeps firing because nothing answered it
(john_wick_le's drop target: 139 fires in 40 s) stands out by count alone, so
this prints every coil fired at least --min times (default 1), busiest first,
as `NAME=n` joined by commas with spaces in names made underscores - one field
a VERDICT line can carry. An index the device table does not name prints as
`n<node>i<index>`.

The fire frame is coil_publish()'s (hwshim.c): `8N 0b 40 <IDX> ...`, 14 bytes.
Only frames AFTER the boot configuration should be piped in - the caller cuts
the log at Start - because the first 0x40 per coil is its setup, not a fire.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coilmap
import gameinfo


def count(lines):
    """Counter of (node, index) over the cmd 40 fire frames in `lines`."""
    c = collections.Counter()
    for line in lines:
        if not line.startswith("[nbts]") or " cmd=40 " not in line or " len=14 " not in line:
            continue
        h = line.split()[-1]
        try:
            b0, idx = int(h[0:2], 16), int(h[6:8], 16)
        except ValueError:
            continue
        if b0 & 0x80:
            c[(b0 & 0x3f, idx)] += 1
    return c


def names(game=None):
    """(node, index) -> coil name, from the title's built device table."""
    coils = coilmap.load(gameinfo.table("device_xy.txt", gameinfo.active(game)) or "")
    return {(r["node"], r["index"]): r["name"] for r in coils if r.get("node") is not None}


def text(counts, by_addr, least=1):
    out = []
    for addr, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if n >= least:
            name = by_addr.get(addr) or "n%di%d" % addr
            out.append("%s=%d" % (name.strip().replace(" ", "_"), n))
    return ",".join(out) or "-"


def main(argv):
    game, least = None, 1
    if "--game" in argv:
        game = argv[argv.index("--game") + 1]
    if "--min" in argv:
        least = int(argv[argv.index("--min") + 1])
    print(text(count(sys.stdin), names(game), least))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
