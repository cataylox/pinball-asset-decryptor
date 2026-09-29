#!/usr/bin/env python3
"""Press a switch in this slot's running Dutch Pinball game.

    sw.py <switch> [tap|down|up] [ms]      e.g.  sw.py startButton
    sw.py --list                           the switches that have a key

The game runs on its own FakePinPROC, which maps KEYS to switches through
the running build's config/keyboard.yaml (1 = startButton, n = flipperLwL,
3 = credit1, 7..0 = menu1..4, ...).  This looks the switch up there and
writes the key to the game's input FIFO, where dpinput.so pushes it onto
SDL's event queue.  A key name (a single character, or an SDL keysym
number like 274) is accepted in place of a switch name.

Uses the slot in PAD_SLOT, as every rig script does.
"""
import os
import sys

ROOT = os.environ.get("DP_ROOT", "/var/tmp/pad_dp")
RIG = os.path.join(ROOT, "rig%s" % os.environ.get("PAD_SLOT", "0"))


def keymap():
    """{switch name: keysym} from the running build's keyboard.yaml.  The
    file is flat `key: name[,name]` lines under keyboard_switch_map, so no
    YAML library is needed (PAD-Runtime's python has none)."""
    ver = open(os.path.join(RIG, "ver")).read().strip()
    path = os.path.join(RIG, "game", ver, "config", "keyboard.yaml")
    out, section = {}, None
    for raw in open(path, encoding="utf-8-sig"):
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
        for n in names.split(","):
            out.setdefault(n.strip(), sym)
    return out


def main(argv):
    if not os.path.exists(os.path.join(RIG, "input")):
        sys.exit("sw.py: rig %s is not running (run_game.sh)" % RIG)
    km = keymap()
    if not argv or argv[0] in ("-h", "--help"):
        sys.exit(__doc__)
    if argv[0] == "--list":
        for name, sym in sorted(km.items()):
            print("%-14s key %s" % (name, chr(sym) if sym < 128 else sym))
        return
    name, action = argv[0], (argv[1] if len(argv) > 1 else "tap")
    if name in km:
        sym = km[name]
    elif len(name) == 1:
        sym = ord(name)
    elif name.isdigit():
        sym = int(name)
    else:
        sys.exit("sw.py: %s has no key in keyboard.yaml (--list)" % name)
    if action not in ("tap", "down", "up"):
        sys.exit("sw.py: action is tap, down or up")
    line = "%s %d" % (action, sym)
    if action == "tap" and len(argv) > 2:
        line += " %d" % int(argv[2])
    # Non-blocking: with no game holding the FIFO open, a plain open() would
    # wait for one forever.
    try:
        fd = os.open(os.path.join(RIG, "input"), os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        sys.exit("sw.py: the game in %s is not reading its input (stopped?)" % RIG)
    try:
        os.write(fd, (line + "\n").encode())
    finally:
        os.close(fd)
    print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
