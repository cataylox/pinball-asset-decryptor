#!/usr/bin/env python3
"""peek.py <pid> <addr> [n] - read n bytes of the running game's memory.

`pin` runs under qemu-arm (user mode): its 32-bit address space sits inside
the qemu process at a fixed offset, found from where qemu mapped the
program's own file (guest 0x8000).  Root only (/proc/<pid>/mem).
  peek.py <pid> 0x44c208 4      -> hex bytes
  peek.py <pid> u32 0x44c208    -> an unsigned 32-bit value
"""
import struct
import sys

GUEST_TEXT = 0x8000


def guest_base(pid):
    with open("/proc/%d/maps" % pid) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 6 and parts[5].endswith("/pin/pin") and int(parts[2], 16) == 0:
                return int(parts[0].split("-")[0], 16) - GUEST_TEXT
    raise SystemExit("peek.py: no pin mapping in process %d" % pid)


def read(pid, addr, n):
    base = guest_base(pid)
    with open("/proc/%d/mem" % pid, "rb") as f:
        f.seek(base + addr)
        return f.read(n)


def main(a):
    if len(a) < 2:
        raise SystemExit(__doc__)
    pid = int(a[0])
    if a[1] == "u32":
        print(struct.unpack("<I", read(pid, int(a[2], 0), 4))[0])
    else:
        print(read(pid, int(a[1], 0), int(a[2], 0) if len(a) > 2 else 16).hex(" "))


if __name__ == "__main__":
    main(sys.argv[1:])
