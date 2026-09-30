#!/usr/bin/env python3
"""Press a switch in this slot's running Dutch Pinball game.

    sw.py <switch> [tap|down|up] [ms]      e.g.  sw.py startButton
    sw.py --list                           every switch, and its key if any

The game runs on its own FakePinPROC, which maps KEYS to switches through
the running build's config/keyboard.yaml.  The rig's copy of that file
gives every switch in machine.yaml a key of its own (dpswitches.py writes
them, with the table in the rig's switches.json); this looks the switch up
there - or in the build's own map (1 = startButton, n = flipperLwL ...) -
and writes the key to the game's input FIFO, where dpinput.so pushes it
onto SDL's event queue.  A key name (a single character, or an SDL keysym
number like 274) is accepted in place of a switch name.

Uses the slot in PAD_SLOT, as every rig script does.
"""
import json
import os
import sys

ROOT = os.environ.get("DP_ROOT", "/var/tmp/pad_dp")
RIG = os.path.join(ROOT, "rig%s" % os.environ.get("PAD_SLOT", "0"))


def keymap():
    """{switch name: keysym} from the running build's keyboard.yaml.  The
    file is flat `key: name[,name]` lines under keyboard_switch_map, so no
    YAML library is needed (PAD-Runtime's python has none)."""
    out, section = {}, None
    try:
        ver = open(os.path.join(RIG, "ver")).read().strip()
        lines = open(os.path.join(RIG, "game", ver, "config", "keyboard.yaml"),
                     encoding="utf-8-sig").readlines()
    except OSError:
        return out               # Alice: no keyboard.yaml (table() has all)
    for raw in lines:
        line = raw.split("#")[0].rstrip()
        if not line.strip():
            continue
        if not line[0].isspace():
            section = line.rstrip(":").strip()
            continue
        if section != "keyboard_switch_map" or ":" not in line:
            continue
        key, names = (p.strip() for p in line.split(":", 1))
        sym = int(key) if key.isdigit() and len(key) > 1 else ord(key)
        if sym >= 1000:          # the rig's own per-switch keys (table())
            continue
        for n in names.split(","):
            out.setdefault(n.strip(), sym)
    return out


def table():
    """{switch name: (n, title)} from the rig's switches.json, or {}."""
    try:
        with open(os.path.join(RIG, "switches.json"), encoding="utf-8") as f:
            return {s["name"]: (s["n"], s["title"]) for s in json.load(f)["switches"]}
    except (OSError, ValueError, KeyError):
        return {}


def main(argv):
    if not os.path.exists(os.path.join(RIG, "input")):
        sys.exit("sw.py: rig %s is not running (run_game.sh)" % RIG)
    km = keymap()
    tb = table()
    if not argv or argv[0] in ("-h", "--help"):
        sys.exit(__doc__)
    if argv[0] == "--list":
        for name in sorted(set(km) | set(tb)):
            key = km.get(name)
            print("%-26s %-30s %s" % (name, tb.get(name, ("", ""))[1],
                                     ("key " + (chr(key) if key < 128 else str(key))) if key else ""))
        return
    name, action = argv[0], (argv[1] if len(argv) > 1 else "tap")
    if action not in ("tap", "down", "up"):
        sys.exit("sw.py: action is tap, down or up")
    if name in tb and name not in km:
        # the rig's own table: dpctl.py knows how this game takes a press
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import dpctl
        ctl = dpctl.Ctl(os.environ.get("PAD_SLOT", "0"))
        n = str(tb[name][0])
        words = ({"tap": ["tap", n] + argv[2:3], "down": ["sw", n, "1"],
                  "up": ["sw", n, "0"]})[action]
        r = ctl.run(words)
        if not r.get("ok"):
            sys.exit("sw.py: %s" % (r.get("error") or "the game is not reading its input"))
        print(" ".join(words))
        return
    if name in km:
        sym = km[name]
    elif len(name) == 1:
        sym = ord(name)
    elif name.isdigit():
        sym = int(name)
    else:
        sys.exit("sw.py: no switch or key %s (--list)" % name)
    line = "%s %d" % (action, sym)
    if action == "tap" and len(argv) > 2:
        line += " %d" % int(argv[2])
    # Non-blocking: with no game holding the FIFO open, a plain open() would
    # wait for one forever.
    try:
        fd = os.open(os.path.join(RIG, "input"), os.O_WRONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        sys.exit("sw.py: the game in %s is not reading its input (stopped?)" % RIG)
    try:
        os.write(fd, (line + "\n").encode())
    finally:
        os.close(fd)
    print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
