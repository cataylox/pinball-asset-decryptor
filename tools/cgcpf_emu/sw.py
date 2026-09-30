#!/usr/bin/env python3
"""sw.py - Pulp Fiction's switches on the rig (io.bin, shared with pfshim.c).

  sw.py list                      every switch: number, name, closed?
  sw.py home                      balls home: the trough full, all else open
  sw.py on|off <switch>...        hold a switch closed / let it go
  sw.py tap <switch> [ms]         close it for ms (default 150), then open
  sw.py coin [n]                  n taps of Coin Left (default 1)
  sw.py launch                    plunge: the lane's ball past Shooter Upper
  sw.py drain                     a ball in play drains into the trough
  sw.py state                     JSON: switches closed, board exchanges,
                                  cabinet reads, FRAM commands

A switch is its number (0-79) or its name from the game's own table
(case and spaces don't matter: "coin left", "COIN_LEFT", "Trough 1").
The rig is $CGCPF_RIG, else /var/tmp/pad_cgcpf/rig<PAD_SLOT>.
"""
import json
import mmap
import os
import struct
import sys
import time

# The game's switch table (pin 1.0.2, the name pointers at 0xea584): numbers
# 0-63 come from the playfield board in the PRU's 'C' packet, 64-79 from the
# cabinet's GPIO bus.  None = no switch there.
NAMES = [
    "Trough Jam", "Trough 1", "Trough 2", "Trough 3", "Trough 4",
    "Subway 1", "Subway 2", "Subway 3",
    "Subway 4", "Subway Entry", "Subway Popper", "Drop Left", "Drop Middle",
    "Drop Right", "EOS Left", "Outlane Left",
    "Kicker Left", "Return Left", "Kicker Right", "Outlane Right",
    "Return Right", "EOS Right", "Shooter", "With Cheese",
    "Standup Left Bottom", "Standup Left Top", "Shooter Upper", "Left AdvX",
    "Case Popper", None, None, None,
    "Case 4", "Case 3", "Case 2", "Case 1", "Case Left", "Case Right",
    "Standup Right Top", "Standup Right Bottom",
    "Saucer Right", "Magnet", "Spinner Right", "MPH", "Jet Right",
    "Jet Center", "Jet Left", "Loop Upper Right",
    "Rubber Right", "Lane Top Left", "Loop Lower Right", "Case Exit",
    "Saucer Top", "Right AdvX", "Single Drop Right", None,
    "Spinner Left", "Lane Top Right", "Rubber Left", "Loop Upper Left",
    "Loop Lower Left", "Single Drop Left Bottom", "Single Drop Left Middle",
    "Single Drop Left Top",
    "Start", None, "Plumb", "Coin Door", "Flipper Upper Left",
    "Flipper Upper Right", "Flipper Lower Left", "Flipper Lower Right",
    "Coin Left", "Coin Center", "Coin Right", "Slam", "Escape",
    "Volume Down", "Volume Up", "Enter",
]
TROUGH = [1, 2, 3, 4]          # Trough 1..4: four balls
SHOOTER = 22
SHOOTER_UPPER = 26             # the lane's exit: the ball has been plunged
COIN_DOOR = 67                  # closed = the door is shut
# Optos: a ball in the beam drives the input HIGH, the opposite of every
# other switch.  The game keeps each switch's kind at run time (a byte per
# switch at 0x456ee4 in pin 1.0.2, 1 = opto): the trough and its jam, the
# subway, the case popper and the briefcase stack.
OPTOS = set(range(0, 11)) | {28, 32, 33, 34, 35}

# io.bin (struct pf_io in pfshim.c)
MAGIC = b"PFI2"
OFF_XFERS, OFF_SW, OFF_EXT, OFF_OUT = 4, 8, 24, 32
OFF_FRAM, OFF_TYPE, OFF_CAB = 72, 76, 80


def rig_dir():
    r = os.environ.get("CGCPF_RIG")
    if r:
        return r
    return "/var/tmp/pad_cgcpf/rig%s" % os.environ.get("PAD_SLOT", "0")


def key(s):
    return "".join(c for c in s.lower() if c.isalnum())


def number(s):
    if s.isdigit() and int(s) < len(NAMES):
        return int(s)
    k = key(s)
    for i, n in enumerate(NAMES):
        if n and key(n) == k:
            return i
    raise SystemExit("sw.py: no switch %r (sw.py list)" % s)


class IO:
    def __init__(self, path=None):
        path = path or os.path.join(rig_dir(), "io", "io.bin")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
        if os.fstat(fd).st_size < 4096:
            os.ftruncate(fd, 4096)
        self.m = mmap.mmap(fd, 4096)
        os.close(fd)
        if self.m[:4] != MAGIC:
            self.m[:4096] = bytes(4096)
            self.m[:4] = MAGIC

    # io.bin holds the WIRE: bit set = input pulled low.  closed()/set()
    # speak switches: an opto is "closed" when its beam is blocked.
    def low(self, n):
        return bool(self.m[OFF_SW + n // 8] & (1 << (n % 8)))

    def closed(self, n):
        return self.low(n) != (n in OPTOS)

    def set(self, n, on):
        low = on != (n in OPTOS)
        b = self.m[OFF_SW + n // 8]
        b = b | (1 << (n % 8)) if low else b & ~(1 << (n % 8))
        self.m[OFF_SW + n // 8] = b

    def home(self):
        for n in range(80):
            self.set(n, n in TROUGH or n == COIN_DOOR)

    def u32(self, off):
        return struct.unpack_from("<I", self.m, off)[0]

    def state(self):
        return {
            "closed": [NAMES[n] or str(n) for n in range(80) if self.closed(n)],
            "xfers": self.u32(OFF_XFERS),
            "cab_reads": self.u32(OFF_CAB),
            "fram_ops": self.u32(OFF_FRAM),
            "out": self.m[OFF_OUT:OFF_OUT + 40].hex(),
        }


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    io = IO()
    cmd, args = argv[0], argv[1:]
    if cmd == "list":
        for i, n in enumerate(NAMES):
            if n:
                print("%2d  %-24s %s" % (i, n, "closed" if io.closed(i) else ""))
    elif cmd == "home":
        io.home()
    elif cmd in ("on", "off"):
        for a in args:
            io.set(number(a), cmd == "on")
    elif cmd == "tap":
        n = number(args[0])
        ms = int(args[1]) if len(args) > 1 else 150
        io.set(n, True)
        time.sleep(ms / 1000)
        io.set(n, False)
    elif cmd == "coin":
        for _ in range(int(args[0]) if args else 1):
            io.set(72, True)
            time.sleep(0.15)
            io.set(72, False)
            time.sleep(0.25)
    elif cmd == "launch":
        io.set(SHOOTER, False)
        io.set(SHOOTER_UPPER, True)
        time.sleep(0.06)
        io.set(SHOOTER_UPPER, False)
    elif cmd == "drain":
        for n in TROUGH:
            if not io.closed(n):
                io.set(n, True)
                break
    elif cmd == "state":
        print(json.dumps(io.state()))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
