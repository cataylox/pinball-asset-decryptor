#!/usr/bin/env python3
"""Talk to this slot's running American Pinball game: press switches, ask state.

    apctl.py [--slot N] sw <n> 0|1        hold switch n active / let it go
    apctl.py [--slot N] tap <n> [ms]      activate it for ms (default 150)
    apctl.py [--slot N] plunge            the shooter lane lets its ball go
    apctl.py [--slot N] drain             a ball drains into the trough
    apctl.py [--slot N] reset             every ball back in the trough
    apctl.py [--slot N] pause 1|0         freeze / resume the game (and apiav)
    apctl.py [--slot N] state             one line of JSON (below)
    apctl.py [--slot N] --stream          the same commands, one per line on
                                          stdin, one reply line each

n is the switch's P-ROC number (switches.json, apswitches.py).  "Active" is
as the game sees it - an NC opto is activated by opening it; py/aprun.py
turns it into the raw state.  Every command is a line down the game's input
FIFO, as sw.py's are.  The switch window keeps one --stream pipe open, so a
click is a line down an open pipe, not a wsl.exe start.

state: {"up": bool, "held": [n...], "switches": {n: 1}, "lights": {name:
[r, g, b]}, "paused": bool} - `switches` is every switch the GAME has active
(aprun.py rewrites `active` in the rig when they change: balls in the
trough, the one in the shooter lane) plus what this pipe holds; `lights` is
aprun.py's lights.json.  "up" is false once the game has stopped reading its
input, and the window closes itself on that.
"""
import json
import os
import signal
import sys
import threading
import time

#: A press shorter than this is stretched to it: the games debounce their
#: switches, and a mouse click can be ~0 ms (tools/dp_emu learned it).
MIN_HOLD_S = 0.1

ROOT = os.environ.get("AP_ROOT", "/var/tmp/pad_ap")


class Ctl:
    def __init__(self, slot):
        self.rig = os.path.join(ROOT, "rig%s" % slot)
        self.known = set()
        self.shooter = None
        self.held = set()
        self.pressed_at = {}
        self.paused = False
        try:
            with open(os.path.join(self.rig, "switches.json"), encoding="utf-8") as f:
                t = json.load(f)
            self.known = {s["n"] for s in t["switches"]}
            self.shooter = t.get("shooter")
        except (OSError, ValueError, KeyError):
            pass

    def send(self, line):
        """Write one line to the game's FIFO.  False if no game reads it
        (non-blocking: a plain open() would wait for a reader forever)."""
        try:
            fd = os.open(os.path.join(self.rig, "input"), os.O_WRONLY | os.O_APPEND | getattr(os, "O_NONBLOCK", 0))
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
            with open(os.path.join(self.rig, "game.pid")) as f:
                os.kill(int(f.read().strip()), 0)
        except (OSError, ValueError):
            return False
        return self.send("")            # an empty line: is anyone reading?

    def active(self):
        try:
            with open(os.path.join(self.rig, "active")) as f:
                return {int(w) for w in f.read().split()}
        except (OSError, ValueError):
            return set()

    def lights(self):
        try:
            with open(os.path.join(self.rig, "lights.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def slot_pids(self):
        """The game's and apiav's pids: the processes whose environment names
        this rig's log (as appath.sh's ap_slot_pids)."""
        want = ("AP_LOG=%s/rig.log" % self.rig).encode()
        pids = []
        for d in os.listdir("/proc"):
            if d.isdigit():
                try:
                    with open("/proc/%s/environ" % d, "rb") as f:
                        if want in f.read().split(b"\0"):
                            pids.append(int(d))
                except OSError:
                    pass
        return pids

    def pause(self, on):
        sig = signal.SIGSTOP if on else signal.SIGCONT
        n = 0
        for p in self.slot_pids():
            try:
                os.kill(p, sig)
                n += 1
            except OSError:
                pass
        if n:
            self.paused = bool(on)
        return n > 0

    def _hold(self, n, on):
        if on:
            self.pressed_at[n] = time.monotonic()
        else:
            t = self.pressed_at.pop(n, None)
            if t is not None:
                wait = MIN_HOLD_S - (time.monotonic() - t)
                if wait > 0:
                    time.sleep(wait)
        ok = self.send("%d %s" % (n, "close" if on else "open"))
        if ok:
            (self.held.add if on else self.held.discard)(n)
        return ok

    def run(self, words):
        if not words:
            return {"ok": False, "error": "no command"}
        cmd = words[0]
        if cmd == "state":
            on = self.active() | self.held
            # a frozen game reads nothing: it is up while it is paused
            return {"up": self.paused or self.up(), "held": sorted(self.held),
                    "switches": {str(n): 1 for n in sorted(on)},
                    "lights": self.lights(), "paused": self.paused}
        if cmd == "drain":
            return {"ok": self.send("!drain")}
        if cmd == "reset":
            return {"ok": self.send("!reset")}
        if cmd == "pause":
            return {"ok": self.pause(len(words) > 1 and words[1] == "1"),
                    "paused": self.paused}
        if cmd == "plunge":
            if self.shooter is None:
                return {"ok": False, "error": "no shooter lane switch"}
            self.held.discard(self.shooter)
            return {"ok": self.send("%d open" % self.shooter)}
        if cmd in ("sw", "tap"):
            try:
                n = int(words[1])
            except (IndexError, ValueError):
                return {"ok": False, "error": "switch number?"}
            if self.known and n not in self.known:
                return {"ok": False, "error": "no switch %d" % n}
            if cmd == "sw":
                return {"ok": self._hold(n, len(words) > 2 and words[2] == "1")}
            ms = int(words[2]) if len(words) > 2 and words[2].isdigit() else 150
            return {"ok": self.send("%d tap %d" % (n, max(ms, int(MIN_HOLD_S * 1000))))}
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
        # The window went away: never leave the game frozen, and let go of
        # anything it was holding.
        if ctl.paused:
            ctl.pause(False)
        for n in list(ctl.held):
            ctl.run(["sw", str(n), "0"])
        return 0
    print(json.dumps(ctl.run(argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
