#!/usr/bin/env python3
"""sw.py - press the switches of the game on this slot's rig board.

    sw.py <switch> [on|off|pulse [ms]]   default: pulse (500 ms)
    sw.py drain | plunge                 a ball back to the trough / the
                                         shooter lane's ball into play
    sw.py --list                         every switch name and number
    sw.py --state                        the board's switch states now

<switch> is a name from the running game's table (spktitles.py; case and
'_'/'-'/' ' do not matter), an alias (start, coin, launch, action, tilt,
enter, back, up, down, shooter, lflip, rflip, ulflip, urflip - each title's
own numbers: Halloween's differ) or a number.  PAD_SLOT picks the slot.
The board (spkwarden.py) reports the change to the game the way the Warden
does; the trough and shooter lane move by themselves when the game fires
the eject and launch coils.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spktitles  # noqa: E402


def running_title():
    """The title on this slot's rig (run_game.sh wrote it), else
    $SPK_TITLE, else Beetlejuice."""
    root = os.environ.get("SPK_ROOT", "/var/tmp/pad_spooky")
    try:
        with open(os.path.join(root, "rig%s" % os.environ.get("PAD_SLOT", "0"),
                               "title")) as f:
            return f.read().strip() or None
    except OSError:
        return None


TITLE = spktitles.get(running_title())
SWITCHES = TITLE["switches"]
ALIASES = spktitles.aliases(running_title())


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
        # Long enough for a game at llvmpipe frame rates to see it and, for
        # Evil Dead, to read it back from the board (its Start "verify").
        req = "tap %d %s" % (n, a[2] if len(a) > 2 else "500")
    else:
        req = "sw %d %d" % (n, 1 if act == "on" else 0)
    print("%s %s: %s" % (SWITCHES.get(n, n), act, ask(req)))


if __name__ == "__main__":
    main(sys.argv[1:])
