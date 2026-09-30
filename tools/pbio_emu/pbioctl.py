#!/usr/bin/env python3
"""pbioctl.py [--slot N] <request...> | --stream - talk to a running rig's
board (pbioboard.py's control socket).

Requests: state, sw <n> <0|1>, tap <n> [ms], rip <n> <0|1>, plunge, drain,
reset, pause <0|1>, leds.  Prints the reply; exit 1 when the rig is not
running or the request was refused.  --stream keeps one connection and
forwards stdin line by line (a switch window cannot wait for wsl.exe per
click).
"""
import os
import socket
import sys


def connect(slot):
    root = os.environ.get("PBIO_ROOT", "/var/tmp/pad_pbio")
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    s.connect(os.path.join(root, "rig%s" % slot, "ctl.sock"))
    return s


def ask(s, line):
    s.sendall((line.strip() + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk:
            raise OSError("rig closed the connection")
        buf += chunk
    return buf.decode().strip()


def main(argv):
    slot = os.environ.get("PAD_SLOT", "0")
    if argv[:1] == ["--slot"]:
        slot, argv = argv[1], argv[2:]
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        s = connect(slot)
        if argv == ["--stream"]:
            for line in sys.stdin:
                if line.strip():
                    print(ask(s, line), flush=True)
            return 0
        reply = ask(s, " ".join(argv))
    except OSError as e:
        print("pbioctl: rig %s not running (%s)" % (slot, e), file=sys.stderr)
        return 1
    print(reply)
    return 1 if '"err"' in reply else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
