#!/usr/bin/env python3
"""sw.py - press Beetlejuice's switches on this slot's rig board.

    sw.py <switch> [on|off|pulse [ms]]   default: pulse (200 ms)
    sw.py drain | plunge                 a ball back to the trough / the
                                         shooter lane's ball into play
    sw.py --list                         every switch name and number
    sw.py --state                        the board's switch states now

<switch> is a name below (case and '_'/'-'/' ' do not matter) or a number.
PAD_SLOT picks the slot.  The board (spkwarden.py) reports the change to the
game the way the Warden does; the trough and shooter lane move by themselves
when the game fires the eject and launch coils.
"""
import json
import os
import sys

# Switches.cs (Beetlejuice v2026.09.15.11): number -> name.
SWITCHES = {
    0: "TROUGH 7", 1: "TROUGH 6", 2: "TROUGH JAM", 3: "TROUGH 5", 4: "TROUGH 4",
    5: "TROUGH 3", 6: "TROUGH 2", 7: "TROUGH 1", 8: "SHOOTER LANE",
    9: "HANDBOOK", 10: "RIGHT DROP TARGET", 12: "RIGHT SLING",
    13: "RIGHT FLIPPER EOS", 14: "RIGHT INLANE", 15: "RIGHT OUTLANE",
    16: "DROP BANK LEFT", 17: "DROP BANK MIDDLE", 18: "DROP BANK RIGHT",
    19: "LEFT PASSIVE SLING", 20: "LEFT SLING", 21: "LEFT FLIPPER EOS",
    22: "LEFT INLANE", 23: "LEFT OUTLANE", 24: "EXTRA BALL TARGET",
    25: "TOP POP BUMPER", 26: "BOTTOM POP BUMPER", 27: "LEFT ORBIT",
    28: "MIDDLE POP BUMPER", 29: "CAMERA TARGET LEFT", 30: "CAMERA TARGET RIGHT",
    35: "UPPER FLIPPER EOS", 37: "NOW SERVING TARGET LEFT",
    38: "NOW SERVING TARGET RIGHT", 39: "COUCH LOOP", 40: "JUNO SCOOP",
    41: "LOST SOULS SCOOP", 42: "LEFT RAMP", 43: "SANDWORM MOUTH",
    44: "LOST SOULS BACK ENTRY", 45: "COUCH LOCK",
    52: "SANDWORM SUBWAY TARGET RIGHT", 54: "SANDWORM SUBWAY TARGET LEFT",
    55: "SPINNER", 60: "MYSTERY SCOOP", 61: "RIGHT ORBIT", 62: "RIGHT RAMP",
    63: "CAPTIVE BALL", 80: "RIGHT FLIPPER BUTTON", 81: "ACTION BUTTON",
    82: "UPPER RIGHT FLIPPER BUTTON", 83: "UPPER LEFT FLIPPER BUTTON",
    84: "TILT", 85: "LAUNCH BUTTON", 86: "LEFT FLIPPER BUTTON",
    87: "START BUTTON", 90: "COIN DROP", 91: "MENU ENTER", 92: "VOLUME UP",
    93: "VOLUME DOWN", 94: "MENU BACK",
}
ALIASES = {"start": 87, "launch": 85, "coin": 90, "action": 81, "tilt": 84,
           "enter": 91, "back": 94, "shooter": 8, "lflip": 86, "rflip": 80}


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
    """One request to the board (spkctl.py) -> its reply."""
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import spkctl
    try:
        s = spkctl.connect(os.environ.get("PAD_SLOT", "0"))
        return spkctl.ask(s, line)
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
        print("balls: %(trough)d in the trough, %(shooter)d in the shooter lane, "
              "%(in_play)d in play" % st["balls"])
        return
    if a[0] in ("drain", "plunge"):
        print(ask(a[0]))
        return
    n = lookup(a[0])
    act = a[1] if len(a) > 1 else "pulse"
    if act not in ("on", "off", "pulse"):
        sys.exit("sw.py: on, off or pulse, not %s" % act)
    if act == "pulse":
        req = "tap %d %s" % (n, a[2] if len(a) > 2 else "200")
    else:
        req = "sw %d %d" % (n, 1 if act == "on" else 0)
    print("%s %s: %s" % (SWITCHES.get(n, n), act, ask(req)))


if __name__ == "__main__":
    main(sys.argv[1:])
