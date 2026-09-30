#!/usr/bin/env python3
"""Talk to this slot's running Dutch Pinball game: press switches, ask state.

    dpctl.py [--slot N] sw <n> 0|1        hold switch n closed / let it go
    dpctl.py [--slot N] tap <n> [ms]      close it for ms (default 150)
    dpctl.py [--slot N] state             one line of JSON (below)
    dpctl.py [--slot N] --stream          the same commands, one per line on
                                          stdin, one reply line each

n is the switch's index in the rig's switches.json (dpswitches.py), whose
keysym the rig's keyboard.yaml maps to it; the press goes down the game's
input FIFO to dpinput.so.  The switch window keeps one --stream pipe open,
so a click is a line down an open pipe, not a wsl.exe start.

state: {"up": bool, "held": [n...], "switches": {n: 1}} - what this pipe is
holding closed (the game's own FakePinPROC state is not readable from
outside; the window lights what it pressed).  "up" is false once the game
has stopped reading its input, and the window closes itself on that.
"""
import json
import os
import sys
import threading

ROOT = os.environ.get("DP_ROOT", "/var/tmp/pad_dp")


class Ctl:
    def __init__(self, slot):
        self.rig = os.path.join(ROOT, "rig%s" % slot)
        self.syms = {}
        self.held = set()
        try:
            with open(os.path.join(self.rig, "switches.json"), encoding="utf-8") as f:
                self.syms = {s["n"]: s["sym"] for s in json.load(f)["switches"]}
        except (OSError, ValueError, KeyError):
            pass

    def send(self, line):
        """Write one command to the game's FIFO.  False if no game reads it
        (non-blocking: a plain open() would wait for a reader forever)."""
        try:
            fd = os.open(os.path.join(self.rig, "input"), os.O_WRONLY | getattr(os, "O_NONBLOCK", 0))
        except OSError:
            return False
        try:
            os.write(fd, (line + "\n").encode())
            return True
        except OSError:
            return False
        finally:
            os.close(fd)

    def up(self):
        try:
            pid = open(os.path.join(self.rig, "game.pid")).read().strip()
            os.kill(int(pid), 0)
        except (OSError, ValueError):
            return False
        return self.send("")            # an empty line: is anyone reading?

    def run(self, words):
        if not words:
            return {"ok": False, "error": "no command"}
        cmd = words[0]
        if cmd == "state":
            return {"up": self.up(), "held": sorted(self.held),
                    "switches": {str(n): 1 for n in sorted(self.held)}}
        if cmd in ("sw", "tap"):
            try:
                n = int(words[1])
            except (IndexError, ValueError):
                return {"ok": False, "error": "switch number?"}
            sym = self.syms.get(n)
            if sym is None:
                return {"ok": False, "error": "no switch %d" % n}
            if cmd == "sw":
                on = len(words) > 2 and words[2] == "1"
                ok = self.send("%s %d" % ("down" if on else "up", sym))
                if ok:
                    (self.held.add if on else self.held.discard)(n)
                return {"ok": ok}
            ms = int(words[2]) if len(words) > 2 and words[2].isdigit() else 150
            return {"ok": self.send("tap %d %d" % (sym, ms))}
        return {"ok": False, "error": "unknown command %s" % cmd}


def main(argv):
    slot = os.environ.get("PAD_SLOT", "0")
    if argv[:1] == ["--slot"]:
        slot, argv = argv[1], argv[2:]
    ctl = Ctl(slot)
    if argv[:1] == ["--stream"]:
        lock = threading.Lock()
        for line in sys.stdin:
            with lock:
                reply = ctl.run(line.split())
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()
        # The window went away: let go of anything it was holding.
        for n in list(ctl.held):
            ctl.run(["sw", str(n), "0"])
        return 0
    print(json.dumps(ctl.run(argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
