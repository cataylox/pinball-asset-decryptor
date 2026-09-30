#!/usr/bin/env python3
"""sw.py - press switches on this slot's Predator rig (pbfast.py's ctl.sock).

  sw.py tap <switch> [ms]     press and release (a coin, Start, a target)
  sw.py on|off <switch>       hold / release
  sw.py plunge | drain        the ball model: shooter lane -> play, play -> trough
  sw.py state | leds          the board's view, JSON
  sw.py list                  the named switches

<switch> is a number or a name from pbtitles.py ("START BUTTON", "start").
PAD_SLOT picks the rig (default 0); PB_ROOT as in pbpath.sh.
"""
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pbtitles  # noqa: E402


def rig_dir():
    root = os.environ.get("PB_ROOT", "/var/tmp/pad_pb")
    return os.path.join(root, "rig%s" % os.environ.get("PAD_SLOT", "0"))


def resolve(name, title="predator"):
    if name.isdigit():
        return int(name)
    names = pbtitles.TITLES[title]["switches"]
    want = name.upper().replace("_", " ")
    exact = [int(k) for k, v in names.items() if v == want]
    if exact:
        return exact[0]
    part = [int(k) for k, v in names.items() if want in v]
    if len(part) == 1:
        return part[0]
    raise SystemExit("sw.py: %r matches %s" % (
        name, ", ".join(names[str(p)] for p in part) or "no switch"))


def ctl(line):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(os.path.join(rig_dir(), "ctl.sock"))
    s.sendall((line + "\n").encode())
    out = b""
    while not out.endswith(b"\n"):
        d = s.recv(65536)
        if not d:
            break
        out += d
    s.close()
    return out.decode().strip()


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    try:
        title = open(os.path.join(rig_dir(), "title")).read().strip()
    except OSError:
        title = "predator"
    cmd = argv[0]
    if cmd == "list":
        for k, v in sorted(pbtitles.TITLES[title]["switches"].items(), key=lambda kv: int(kv[0])):
            print("%3s  %s" % (k, v))
        return 0
    if cmd in ("plunge", "drain", "state", "leds"):
        print(ctl(cmd))
        return 0
    if cmd == "tap" and len(argv) >= 2:
        ms = argv[2] if len(argv) > 2 else "150"
        print(ctl("tap %d %s" % (resolve(argv[1], title), ms)))
        return 0
    if cmd in ("on", "off") and len(argv) >= 2:
        print(ctl("sw %d %d" % (resolve(argv[1], title), 1 if cmd == "on" else 0)))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
