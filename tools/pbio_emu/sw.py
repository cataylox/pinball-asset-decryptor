#!/usr/bin/env python3
"""sw.py - press the switches of the game on this slot's rig board.

    sw.py <switch> [on|off|pulse [ms]]   default: pulse (500 ms)
    sw.py drain | plunge | reset         a ball back to the trough / the
                                         Launch button / every ball home
    sw.py --list                         every switch name and number
    sw.py --state                        the board's switch states now

<switch> is a name from the running title's table (pbiotitles.py; case and
spaces do not matter, a unique part will do), an alias (start, launch, coin,
tilt, enter, escape, up, down) or a number.  PAD_SLOT picks the slot.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pbioctl  # noqa: E402
import pbiotitles  # noqa: E402


def running_title():
    root = os.environ.get("PBIO_ROOT", "/var/tmp/pad_pbio")
    try:
        with open(os.path.join(root, "rig%s" % os.environ.get("PAD_SLOT", "0"),
                               "title")) as f:
            return f.read().strip() or "alien"
    except OSError:
        return "alien"


TITLE = pbiotitles.get(running_title())
SWITCHES = {n: s for n, s in TITLE["switches"].items() if s != "UNUSED"}
ALIASES = TITLE["buttons"]


def key(s):
    return "".join(c for c in s.lower() if c.isalnum())


def lookup(s):
    if s.isdigit():
        return int(s)
    k = key(s)
    if k in ALIASES:
        return ALIASES[k]
    for n, name in SWITCHES.items():
        if key(name) == k:
            return n
    hits = [n for n, name in SWITCHES.items() if k in key(name)]
    if len(hits) == 1:
        return hits[0]
    sys.exit("sw.py: %s switch: %s" % ("ambiguous" if hits else "no such", s))


def ask(line):
    try:
        return pbioctl.ask(pbioctl.connect(os.environ.get("PAD_SLOT", "0")),
                           line)
    except OSError as e:
        sys.exit("sw.py: no rig running (%s)" % e)


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__.strip())
        return
    if a[0] == "--list":
        for n, name in sorted(SWITCHES.items()):
            print("%3d  %s" % (n, name))
        return
    if a[0] == "--state":
        st = json.loads(ask("state"))
        for n, v in sorted(st["switches"].items(), key=lambda kv: int(kv[0])):
            if v:
                print("%3d  %s" % (int(n), SWITCHES.get(int(n), "?")))
        print("balls: %(trough)d in the trough, %(shooter)d in the shooter "
              "lane, %(in_play)d in play" % st["balls"])
        return
    if a[0] in ("drain", "plunge", "reset"):
        print(ask(a[0]))
        return
    n = lookup(a[0])
    act = a[1] if len(a) > 1 else "pulse"
    if act not in ("on", "off", "pulse"):
        sys.exit("sw.py: on, off or pulse, not %s" % act)
    if act == "pulse":
        req = "tap %d %s" % (n, a[2] if len(a) > 2 else "500")
    else:
        req = "sw %d %d" % (n, 1 if act == "on" else 0)
    print("%s %s: %s" % (SWITCHES.get(n, n), act, ask(req)))


if __name__ == "__main__":
    main(sys.argv[1:])
