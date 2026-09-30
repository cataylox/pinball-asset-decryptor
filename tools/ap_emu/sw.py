#!/usr/bin/env python3
"""Press a switch in this slot's running American Pinball game.

    sw.py <switch> [tap|close|open] [ms]   e.g.  sw.py startButton
    sw.py --list                           every switch the machine has
    sw.py --state                          log what the game thinks (rig.log):
                                           active switches, ball, players, modes

<switch> is a name from the machine yaml (or its P-ROC number).  `tap`
(the default) activates it for [ms] (150) and lets go; `close` / `open`
hold it active / let it go.  "Active" follows the switch's type, as the
game sees it: an NC opto is activated by opening it.

The line goes to the game's input FIFO, where py/aprun.py hands it to the
game's FakePinPROC (add_switch_event) - any switch works, not only the ones
the title's keyboard map names.

Uses the slot in PAD_SLOT, as every rig script does.
"""
import os
import sys

ROOT = os.environ.get("AP_ROOT", "/var/tmp/pad_ap")
RIG = os.path.join(ROOT, "rig%s" % os.environ.get("PAD_SLOT", "0"))


def switches():
    """[(name, number, type, label)] the running game wrote at boot."""
    out = []
    try:
        with open(os.path.join(RIG, "switches")) as f:
            for line in f:
                parts = line.rstrip("\n").split(" ", 3)
                if len(parts) >= 3:
                    out.append((parts[0], int(parts[1]), parts[2], parts[3] if len(parts) > 3 else ""))
    except OSError:
        pass
    return out


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        sys.exit(__doc__)
    if not os.path.exists(os.path.join(RIG, "input")):
        sys.exit("sw.py: rig %s is not running (run_game.sh)" % RIG)
    known = switches()
    if argv[0] == "--list":
        for name, num, typ, label in known:
            print("%-22s %3d %s  %s" % (name, num, typ, label))
        return
    if argv[0] == "--state":
        line = "!state"
    else:
        line = None
    name, action = argv[0], (argv[1] if len(argv) > 1 else "tap")
    if line is None:
        if known and name not in [k[0] for k in known] and not name.isdigit():
            sys.exit("sw.py: no switch %s (--list)" % name)
        if action not in ("tap", "close", "open"):
            sys.exit("sw.py: action is tap, close or open")
        line = "%s %s" % (name, action)
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
    if line == "!state":
        import time
        time.sleep(0.5)
        with open(os.path.join(RIG, "rig.log")) as f:
            print("".join([l for l in f if " state: " in l][-3:]), end="")


if __name__ == "__main__":
    main(sys.argv[1:])
