#!/usr/bin/env python3
"""procctl.py [--slot N] <command...> | --stream - talk to a running rig's board.

Commands are prochw.py's control protocol: sw <sw> <0|1>, closed <sw> <0|1>,
tap <sw> [ms], state, switches, drivers, log [n], leds.  Prints the reply;
exit 1 when the rig is not running or the command was refused.

--stream keeps ONE connection and forwards stdin line by line, printing each
reply (a flipper cannot wait for a new wsl.exe per press).
"""
import os
import socket
import sys


def connect(slot):
    root = os.environ.get("PROC_ROOT", "/var/tmp/pad_proc")
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
        print("procctl: rig %s not running (%s)" % (slot, e), file=sys.stderr)
        return 1
    print(reply)
    return 1 if reply.startswith("err") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
