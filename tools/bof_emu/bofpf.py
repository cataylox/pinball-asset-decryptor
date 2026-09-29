#!/usr/bin/env python3
"""bofpf.py - the Barrels of Fun switch window: the game's own playfield
drawing with every switch on it, and a labelled switch list beside it.

    pythonw tools\\bof_emu\\bofpf.py --title dune [--distro PAD-Runtime]
                                    [--slot 0] [--art <path to pfart.webp>]

The Emulate BoF tab opens it once the game has found its boards, the way
the Stern tab opens tools/spike2_emu/playfield.py - and for the same reason it
runs on WINDOWS, on the app's own Python: the app's Linux has no GUI toolkit,
the app's Python has pywebview.  The window is a page hosted by
tools/spike2_emu/pfweb.py (a native WebView2 window where pywebview imports,
a browser app window where it does not), in the app's design.

WHERE THE PICTURE AND THE POSITIONS COME FROM - both from the game itself.
Every switch in the title's switch table carries an (x_position, y_position)
for its service menu's switch test, which draws them over
assets/images/service_menu/service_switch_test_background.png.  gen_profile.py
copied the positions into the profile; pfart.py pulled the picture out of the
running build when it was unpacked.  One screen of the game's own, so they
agree by construction.  Switches without both coordinates are ones the test
screen does not draw; they are in the list only.

HOW IT REACHES THE GAME: one long-lived ``ctl.sh --stream`` pipe into the
rig, request then reply, strictly in order.  A press is a line down a pipe
already open - no wsl.exe per click - so a flipper follows the mouse.  The
same pipe carries a ``state`` request ten times a second for the lit
markers and the ball line.  When the rig stops answering the window closes
itself: a switch window for a game that is gone would only mislead.

A SWITCH IS HELD WHILE THE MOUSE BUTTON IS DOWN (a flipper, a ball resting
in a scoop); right-click latches it until right-clicked again (the coin
door, a ball sitting in the trough).  Keys, while this window is focused:
Z / left Shift and / / right Shift the flippers, 1 Start, 5 a coin, Space
Launch, A Action, P Plunge, D Drain.
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
POLL_S = 0.1
GONE_AFTER = 30          # polls without an answer (~3 s) = the game is gone
GEOM_FILE = os.path.join(os.path.expanduser("~"), ".pad_bof_switches.json")

#: profile key -> (keyboard codes, label shown in the list)
KEYS = {
    "flipper_left": (("KeyZ", "ShiftLeft"), "Z"),
    "flipper_right": (("Slash", "ShiftRight"), "/"),
    "start": (("Digit1",), "1"),
    "coin": (("Digit5",), "5"),
    "launch": (("Space",), "Space"),
    "action": (("KeyA",), "A"),
}


def wsl_path(p):
    p = p.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def load_profile(title):
    with open(os.path.join(HERE, "profiles", "%s.json" % title),
              encoding="utf-8") as f:
        return json.load(f)


def page_model(prof):
    """Everything the page draws that never changes during a run."""
    keys = prof.get("keys") or {}
    by_n = {n: k for k, n in keys.items()}
    bics = {int(n) for n in (prof.get("bics_switches") or {})}
    rows = []
    for s in prof.get("switches") or []:
        n = s["n"]
        if n in bics:
            group = "Mechanism"
        elif "cabinet" in (s.get("tags") or []) or n < 24:
            group = "Cabinet"
        else:
            group = "Playfield"
        k = by_n.get(n)
        rows.append({
            "n": n, "label": s.get("label") or s.get("const", ""),
            "opto": bool(s.get("opto")), "group": group,
            "x": s.get("x") or 0, "y": s.get("y") or 0,
            "placed": bool(s.get("x") and s.get("y")),
            "key": KEYS[k][1] if k in KEYS else "",
            "codes": list(KEYS[k][0]) if k in KEYS else [],
            "hold": bool(k and k.startswith("flipper")),
        })
    return {"title": prof.get("title", ""), "switches": rows,
            "coin_door": keys.get("coin_door"),
            "trough": prof.get("trough_switches") or [],
            "balls_total": prof.get("balls")}


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
    def __init__(self, prof, rig, art):
        self.model = page_model(prof)
        self.rig = rig
        self.art = art if art and os.path.isfile(art) else None
        self.live = {"active": [], "balls": {}, "leds_lit": 0, "up": False}
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
        if m in ("plunge", "drain"):
            return self.rig.ask(m)
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
            if st is None:
                self.misses += 1
                if self.misses >= GONE_AFTER:
                    self.host.publish("close")
                    time.sleep(0.5)
                    self.host.quit()
                    return
            else:
                self.misses = 0
                live = {"active": sorted(int(k) for k, v in
                                         (st.get("switches") or {}).items() if v),
                        "balls": st.get("balls") or {},
                        "leds_lit": st.get("leds_lit", 0), "up": True}
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
    ap = argparse.ArgumentParser(description="Barrels of Fun switch window")
    ap.add_argument("--title", required=True, help="profile name (dune, ...)")
    ap.add_argument("--distro", default="")
    ap.add_argument("--slot", default=os.environ.get("PAD_SLOT", "0"))
    ap.add_argument("--art", default="")
    args = ap.parse_args(argv)
    prof = load_profile(args.title)
    rig = Rig(args.distro, args.slot)
    app = App(prof, rig, args.art)
    host = pfweb.WebHost(os.path.join(HERE, "bofpage"), app,
                         title="%s - switches" % prof.get("title", "BoF"))
    app.host = host
    host.start()
    threading.Thread(target=app.poll, daemon=True, name="bof-poll").start()
    g = load_geom()
    main_spec = {"page": "main", "width": 980, "height": 860,
                 "title": "BoF %s - switches" % prof.get("title", ""),
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
