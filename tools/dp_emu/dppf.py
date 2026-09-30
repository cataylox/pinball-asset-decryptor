#!/usr/bin/env python3
"""dppf.py - the Dutch Pinball switch window: the game's own machine view
with every switch on it, and a labelled switch list beside it.

    pythonw tools\\dp_emu\\dppf.py --table <switches.json> [--distro PAD-Runtime]
                                  [--slot 0] [--title "The Big Lebowski"]

The Emulate DP tab opens it once the game is up, as the BoF tab opens
bofpf.py - and for the same reason it runs on WINDOWS, on the app's own
Python (the app's Linux has no GUI toolkit).  The window is a page hosted by
tools/spike2_emu/pfweb.py, like the other rigs' switch windows.

WHERE THE PICTURE AND THE POSITIONS COME FROM - the game itself.  Its
machine.yaml gives every switch a machine_x / machine_y on
assets/display/machine.png, the drawing its developers' own "machine view"
showed; dpswitches.py copied both into the rig's switches.json.  Switches
without a spot are in the list only.

HOW IT REACHES THE GAME: one long-lived ``ctl.sh --stream`` pipe into the
rig (dpctl.py), request then reply, in order - a press is a line down a
pipe already open, not a wsl.exe per click.  The same pipe carries a
``state`` request five times a second; when the game stops reading its
input the window closes itself.

A SWITCH IS HELD WHILE THE MOUSE BUTTON IS DOWN; right-click latches it
until right-clicked again (the coin door, a ball sitting in a trough slot).
Keys, while this window is focused, are the game's own keyboard.yaml ones:
N / M the flippers, 1 Start, 3 a coin, 7 8 9 0 the service buttons.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "spike2_emu"))
import pfweb  # noqa: E402  (the rig windows' shared web host)

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
POLL_S = 0.2
GONE_AFTER = 15          # polls without a live game (~3 s) = it is gone
GEOM_FILE = os.path.join(os.path.expanduser("~"), ".pad_dp_switches.json")

#: switch-name prefixes -> the list's groups (anything else is Playfield)
CABINET = ("startButton", "launchButton", "credit", "menu", "coinDoor",
           "tilt", "slamTilt", "flipper")
HOLD = ("flipper",)


def wsl_path(p):
    p = p.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def win_path(linux_path, distro):
    """A path inside the app's Linux, as Windows reaches it."""
    if not distro or not linux_path.startswith("/"):
        return linux_path
    return "\\\\wsl.localhost\\%s%s" % (distro, linux_path.replace("/", "\\"))


def key_codes(key):
    """keyboard.yaml's key -> the browser's KeyboardEvent.code values."""
    if len(key) == 1 and key.isalpha():
        return ["Key" + key.upper()]
    if len(key) == 1 and key.isdigit():
        return ["Digit" + key, "Numpad" + key]
    return {"Up": ["ArrowUp"], "Down": ["ArrowDown"], "Left": ["ArrowLeft"],
            "Right": ["ArrowRight"]}.get(key, [])


def group_of(name):
    if name.startswith(CABINET):
        return "Cabinet"
    if name.startswith("trough"):
        return "Trough"
    return "Playfield"


def page_model(table, title):
    """Everything the page draws that never changes during a run."""
    order = {"Cabinet": 0, "Playfield": 1, "Trough": 2}
    rows = []
    for s in table.get("switches") or []:
        placed = s.get("x") is not None and s.get("y") is not None
        rows.append({
            "n": s["n"], "label": s.get("title") or s["name"],
            "name": s["name"], "wire": s.get("label", ""),
            "opto": bool(s.get("nc")), "group": group_of(s["name"]),
            "x": s.get("x") or 0, "y": s.get("y") or 0, "placed": placed,
            "key": s.get("key") or "", "codes": key_codes(s.get("key") or ""),
            "hold": s["name"].startswith(HOLD),
        })
    rows.sort(key=lambda r: (order[r["group"]], r["n"]))
    door = [r["n"] for r in rows if r["name"] == "coinDoor"]
    return {"title": title, "switches": rows,
            "coin_door": door[0] if door else None}


class Rig:
    """The ctl.sh --stream pipe: one request, one reply, in order."""

    def __init__(self, distro, slot):
        cmd = ["wsl.exe"] + (["-d", distro] if distro else []) + [
            "-e", "env", "PAD_SLOT=%s" % slot, "bash",
            wsl_path(os.path.join(HERE, "ctl.sh")), "--stream"]
        if sys.platform != "win32":             # a Linux desktop: no wsl.exe
            cmd = ["env", "PAD_SLOT=%s" % slot, "bash",
                   os.path.join(HERE, "ctl.sh"), "--stream"]
        self.cmd = cmd
        self.proc = None
        self.lock = threading.Lock()

    def ask(self, line):
        with self.lock:
            for _attempt in (1, 2):
                try:
                    if self.proc is None or self.proc.poll() is not None:
                        self.proc = subprocess.Popen(
                            self.cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, bufsize=1,
                            universal_newlines=True, encoding="utf-8",
                            errors="replace", creationflags=_CREATE_NO_WINDOW)
                    self.proc.stdin.write(line + "\n")
                    self.proc.stdin.flush()
                    reply = self.proc.stdout.readline()
                    if reply:
                        return reply.strip()
                except (OSError, ValueError):
                    pass
                self.proc = None
            return None

    def close(self):
        p, self.proc = self.proc, None
        if p is not None:
            try:
                p.stdin.close()
                p.wait(timeout=3)
            except Exception:                           # noqa: BLE001
                p.kill()


class App:
    def __init__(self, model, rig, art):
        self.model = model
        self.rig = rig
        self.art = art if art and os.path.isfile(art) else None
        self.live = {"active": [], "up": False}
        self.host = None
        self.misses = 0
        self.stopping = False

    # -- pfweb's four calls -------------------------------------------------
    def state(self, page):
        return dict(self.model, art="/file/art" if self.art else "",
                    live=self.live)

    def api(self, m, args):
        if m == "hold":
            return self.rig.ask("sw %d %d" % (int(args[0]), 1 if args[1] else 0))
        if m == "tap":
            return self.rig.ask("tap %d 150" % int(args[0]))
        raise ValueError("unknown call %r" % m)

    def blob(self, key):
        return None

    def file(self, name):
        return self.art if name == "art" else None

    # -- the live state -----------------------------------------------------
    def poll(self):
        while not self.stopping:
            reply = self.rig.ask("state")
            try:
                st = json.loads(reply) if reply else None
            except ValueError:
                st = None
            if not st or not st.get("up"):
                self.misses += 1
                if self.misses >= GONE_AFTER:
                    self.host.publish("close")
                    time.sleep(0.5)
                    self.host.quit()
                    return
            else:
                self.misses = 0
                live = {"active": sorted(int(k) for k in (st.get("switches") or {})),
                        "up": True}
                if live != self.live:
                    self.live = live
                    self.host.publish("live", live)
            time.sleep(POLL_S)


def load_geom():
    try:
        with open(GEOM_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_geom(host):
    pos = host.geometry("main")
    if pos:
        try:
            with open(GEOM_FILE, "w", encoding="utf-8") as f:
                json.dump({"x": pos[0], "y": pos[1]}, f)
        except OSError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dutch Pinball switch window")
    ap.add_argument("--table", required=True, help="the rig's switches.json")
    ap.add_argument("--distro", default="")
    ap.add_argument("--slot", default=os.environ.get("PAD_SLOT", "0"))
    ap.add_argument("--title", default="Dutch Pinball")
    args = ap.parse_args(argv)
    with open(args.table, encoding="utf-8") as f:
        table = json.load(f)
    model = page_model(table, args.title)
    rig = Rig(args.distro, args.slot)
    app = App(model, rig, win_path(table.get("art") or "", args.distro))
    host = pfweb.WebHost(os.path.join(HERE, "dppage"), app,
                         title="%s - switches" % args.title)
    app.host = host
    host.start()
    threading.Thread(target=app.poll, daemon=True, name="dp-poll").start()
    g = load_geom()
    main_spec = {"page": "main", "width": 980, "height": 900,
                 "title": "%s - switches" % args.title,
                 "x": g.get("x"), "y": g.get("y"), "min_size": (640, 480)}

    def on_close():
        app.stopping = True
        save_geom(host)
        rig.close()
        host.stop()
    host.run(main_spec, on_close)
    return 0


if __name__ == "__main__":
    sys.exit(main())
