#!/usr/bin/env python3
"""appf.py - the American Pinball virtual playfield: the Stern rigs' own
virtual-playfield page (tools/spike2_emu/pfpage, unchanged - David: "use the
stern layout of this window as a template ... we should NOT be reinventing
the wheel"), served for an AP game.

    pythonw tools\\ap_emu\\appf.py --table <switches.json> [--distro PAD-Runtime]
        [--slot 0] [--title "Legends of Valhalla"] [--audio-ctl <audio_ctl.json>]
        [--parent-pipe]

The page is data-driven: a snapshot (/state) and live "frame" events, and a
fixed set of calls back (hold, row, svc, door, ball, key, pause, volume...).
This host answers them from the rig's switches.json (apswitches.py) and a
live `ctl.sh --stream` pipe into the game (apctl.py), as playfield.py does
for a Stern card:

* the playfield: the game's own picture with its switches and lights where
  the game puts them (AP's simulator positions, or the developers' layout -
  apswitches.py says which); lights lit in the game's colours.  A game with
  no usable picture gets the page's schematic view: every light as a swatch,
  every switch as a row.
* the key panel: the cabinet and flipper keys the Stern window uses (arrows
  for the flippers, 1 Start, 5 a coin, Space the Action button, T tilt,
  letters for playfield switches), rows that press what they name, the
  coin-door SERVICE buttons (Backspace/Esc, -, =, Enter), the coin door (C),
  and BALLS: the trough, Plunge (F), Drain (D), Reset balls.
* the status bar: Pause (Pause / F9 freezes the game and apiav), and the
  Emulate tab's Volume / Mute (the shared control file, --audio-ctl).

It runs on WINDOWS, on the app's own Python, as every rig's window does; the
game is in the app's Linux.  --parent-pipe: the tab holds stdin open and
closes it on Stop; the window closes then (and on the game's end).
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.join(os.path.dirname(HERE), "spike2_emu")
sys.path.insert(0, SPIKE)
import pfweb  # noqa: E402  (the rig windows' shared web host)

PAGE_DIR = os.path.join(SPIKE, "pfpage")
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
POLL_S = 0.2
GONE_AFTER = 15          # polls without a live game (~3 s) = it is gone
GEOM_FILE = os.path.join(os.path.expanduser("~"), ".pad_ap_switches.json")
LED_R = 5.5

#: The coin-door service buttons: switch name, then label, caption, glyph,
#: fill, ring, caption colour, key codes, key text - the Stern panel's look.
SERVICE = (
    ("exit", "Service Back", "BACK", "", "#1f9d4e", "#0d5c2a", "#dff5e6",
     ("Backspace", "Escape"), "Bksp/Esc"),
    ("down", "Service Minus", "< -", "-", "#d43535", "#7a1717", "#ffffff",
     ("Minus", "NumpadSubtract"), "-"),
    ("up", "Service Plus", "+ >", "+", "#d43535", "#7a1717", "#ffffff",
     ("Equal", "NumpadAdd"), "="),
    ("enter", "Service Select", "SELECT", "", "#1c1c1c", "#777", "#d8d8d8",
     ("Enter", "NumpadEnter"), "Enter"),
)
#: Letters for playfield switches, in the Stern window's order; T, C, F, D
#: are the tilt, the coin door, Plunge and Drain.
LETTERS = "ASZXQWGEOPMRNHJKLIUYVB"


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


def _num(name):
    d = "".join(c for c in name if c.isdigit())
    return int(d) if d else 0


# --------------------------------------------------------------- the model
def key_rows(table, unplaced=True):
    """The key panel's rows: [{label, keys, codes, cabinet, ns, hold}] -
    the Stern window's cabinet keys, letters for playfield switches, then
    (unplaced) a row with no key for every other switch the picture does
    not place, so every switch can be pressed.  The schematic view lists
    every switch itself, and passes unplaced=False."""
    sws = table.get("switches") or []
    by = {s["name"]: s for s in sws}
    svc = {row[0] for row in SERVICE}
    rows, taken = [], set()

    def add(names, keys, codes, cabinet, hold):
        found = [by[n] for n in names if n in by and n not in taken]
        if not found:
            return
        taken.update(s["name"] for s in found)
        rows.append({"label": " + ".join(s["label"] or s["name"] for s in found),
                     "keys": keys, "codes": list(codes), "cabinet": cabinet,
                     "ns": [s["n"] for s in found], "hold": hold})
    add(["startButton"], "1", ["Digit1", "Numpad1"], True, False)
    add(["coin1"], "5", ["Digit5", "Numpad5"], True, False)
    add([n for n in ("ActionButton", "launchButton", "magnaGrab", "diverter") if n in by][:1],
        "Space", ["Space"], True, True)
    add(["tilt"], "T", ["KeyT"], True, False)
    add(sorted(n for n in by if n.startswith("flipper") and n.endswith("L")),
        "Left", ["ArrowLeft"], False, True)
    add(sorted(n for n in by if n.startswith("flipper") and n.endswith("R")),
        "Right", ["ArrowRight"], False, True)
    letters = list(LETTERS)
    for s in sorted(sws, key=lambda s: s["n"]):
        if not letters:
            break
        if s["group"] == "Playfield" and s["name"] not in taken:
            L = letters.pop(0)
            add([s["name"]], L, ["Key" + L], False, False)
    for s in sorted(sws, key=lambda s: s["n"]) if unplaced else ():
        if (s["name"] in taken or s["name"] in svc or s["name"] == "coinDoor"
                or s["group"] == "Trough" or "x" in s):
            continue
        add([s["name"]], "", [], s["group"] == "Cabinet", False)
    return rows


def trough_order(table):
    """The trough's positions from the eject end (as the rig models them)."""
    pos = [s for s in table.get("switches") or []
           if s["group"] == "Trough" and s["name"] != "shooter"
           and "jam" not in (s.get("label") or "").lower()]
    pos.sort(key=lambda s: _num(s["name"]))
    ej = [s for s in pos if "eject" in s["name"].lower()]
    return ej + [s for s in pos if s not in ej]


def light_value(rgb):
    """[r, g, b, alpha, radius] for the page (None = dark): the colour at
    full strength, its brightness as the alpha."""
    if not rgb or not any(rgb):
        return None
    m = max(rgb[:3])
    k = 255.0 / m
    return [int(min(255, c * k)) for c in rgb[:3]] + [round(max(0.35, m / 255.0), 2), LED_R]


class Rig:
    """The ctl.sh --stream pipe: one request, one JSON reply, in order."""

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
                        try:
                            return json.loads(reply)
                        except ValueError:
                            return None
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
    """What the Stern page asks of its host (pfweb's four calls), for an AP
    game."""

    def __init__(self, table, rig, art, title, slot="0", label="", audio_ctl=""):
        self.t = table
        self.rig = rig
        self.art = art if art and os.path.isfile(art) else None
        self.title = title
        self.slot = str(slot)
        self.label = label
        self.audio_ctl = audio_ctl
        self.host = None
        self.stopping = False
        self.misses = 0
        sws = table.get("switches") or []
        self.by_n = {s["n"]: s for s in sws}
        self.by_name = {s["name"]: s for s in sws}
        self.svc = [(self.by_name[row[0]], row[1:]) for row in SERVICE
                    if row[0] in self.by_name]
        if len(self.svc) != len(SERVICE):
            self.svc = []
        self.door = self.by_name.get("coinDoor")
        self.trough = trough_order(table)
        self.shooter = self.by_name.get("shooter")
        self.placed = [s for s in sws if "x" in s]
        self.lights_placed = table.get("lights") or []
        self.field = bool(self.art and table.get("size")
                          and (self.placed or self.lights_placed))
        self.rows = key_rows(table, unplaced=self.field)
        # live state
        self.active = set()
        self.lights = {}
        self.paused = False
        self.held_ids = set()          # switches this window holds (mouse)
        self.key_held = {}             # key code -> [switch numbers]
        self.row_hit = set()           # row indexes pressed right now
        self.note = []
        self._sent = {}

    # -- the snapshot ------------------------------------------------------------
    def _audio(self):
        if not self.audio_ctl:
            return None
        try:
            with open(self.audio_ctl, encoding="utf-8") as f:
                d = json.load(f)
            return {"gain": max(0.0, min(1.0, float(d.get("gain", 1.0)))),
                    "muted": bool(d.get("muted", False))}
        except (OSError, ValueError, TypeError, AttributeError):
            return {"gain": 1.0, "muted": False}

    def _run(self):
        return {"paused": self.paused, "audio": self._audio()}

    def _info(self):
        return [["Switches", str(len(self.by_n)),
                 "%d on the picture" % len(self.placed) if self.field else "no picture"],
                ["Lights", str(len(self.lights) or len(self.lights_placed)),
                 "%d on the picture" % len(self.lights_placed) if self.field else ""],
                ["Positions", self.t.get("art_from") or "none in this game", ""]]

    def _live(self):
        return [["Switches made", str(len(self.active)), ""],
                ["Lights lit", str(sum(1 for v in self.lights.values() if v and any(v))), ""]]

    def _balls(self):
        tr = sum(1 for s in self.trough if s["n"] in self.active)
        sh = 1 if self.shooter and self.shooter["n"] in self.active else 0
        total = self.t.get("balls")
        if total:
            play = max(0, total - tr - sh)
            return tr, sh, play, "balls %d   trough %d   shooter %d   in play %d" % (
                total, tr, sh, play)
        return tr, sh, 0, "trough %d   shooter %d" % (tr, sh)

    def _panel_dyn(self):
        _tr, sh, play, text = self._balls()
        rows = [[i in self.row_hit or any(n in self.held_ids for n in r["ns"]), "",
                 any(n in self.active for n in r["ns"])] for i, r in enumerate(self.rows)]
        return {"rows": rows,
                "svc": [s["n"] in self.active for s, _look in self.svc],
                "door": (self.door["n"] in self.active) if self.door else None,
                "ball": text, "drain": play > 0 or sh > 0,
                "dots": {"flags": [s["n"] in self.active for s in self.trough],
                         "text": "1 = eject end"},
                "note": list(self.note[-3:])}

    def _panel_spec(self):
        return {
            "rows": [{"keys": r["keys"], "label": r["label"], "cabinet": r["cabinet"],
                      "na": False, "click": i} for i, r in enumerate(self.rows)],
            "svc": [{"label": look[0], "sub": look[1], "glyph": look[2], "fill": look[3],
                     "ring": look[4], "subfg": look[5], "keys": look[7], "id": s["n"]}
                    for s, look in self.svc],
            "clear": None,
            "door": "C" if self.door else None,
            "trough_keys": "F = plunge   D = drain",
            "balls": ({"pos": [str(i + 1) for i in range(len(self.trough))]}
                      if self.trough else None),
            "disc": None}

    def _sw_dyn(self):
        return {str(n): 1 for n in self.active}

    def _fx(self):
        return {k: light_value(self.lights.get(k)) for k, _x, _y in self.lights_placed}

    def _grid(self):
        out = {}
        for k, rgb in self.lights.items():
            v = light_value(rgb)
            out[k] = v[:4] if v else None
        return out

    def _status(self):
        _tr, _sh, play, _t = self._balls()
        lit = sum(1 for v in self.lights.values() if v and any(v))
        bits = [self.title, "%d in play" % play, "%d lights lit" % lit]
        if self.paused:
            bits.append("PAUSED")
        return "  ·  ".join(bits)

    def _switch_tip(self, s):
        return "%s  (%s, %d%s)\nclick and hold to make it; right-click too" % (
            s["label"] or s["name"], s["name"], s["n"], ", an opto" if s.get("nc") else "")

    def _view(self):
        if self.field:
            w, h = self.t["size"]
            return {"base": [w, h], "art": True, "coils": [], "trough": None,
                    "fixtures": [[k, x, y] for k, x, y in self.lights_placed],
                    "switches": [[str(s["n"]), s["x"], s["y"], s["n"]] for s in self.placed],
                    "info": self._info()}
        names = sorted(self.lights) or sorted(k for k, _x, _y in self.lights_placed)
        return {"bar": "%s - this game ships no playfield picture: its lights, "
                       "and every switch" % self.title,
                "grid": {"blocks": [{"node": "lights", "cells": [
                    {"k": k, "tip": k} for k in names]}] if names else []},
                "entries": [{"id": s["n"], "name": s["label"] or s["name"],
                             "tip": self._switch_tip(s), "live": True}
                            for s in sorted(self.by_n.values(), key=lambda s: s["n"])],
                "trough": None, "info": self._info()}

    def state(self, page):
        rig = {}
        if self.slot not in ("", "0"):
            rig = {"slot": int(self.slot), "label": "" if self.label == "PAD" else self.label}
        return {"title": "%s - virtual playfield" % self.title, "rig": rig,
                "status": self._status(), "run": self._run(), "savestates": False,
                "kind": "field" if self.field else "schematic", "view": self._view(),
                "dyn": ({"fx": self._fx(), "coil": {}, "sw": self._sw_dyn()} if self.field
                        else {"grid": self._grid(), "sw": self._sw_dyn()}),
                "panel": {"spec": self._panel_spec(), "dyn": self._panel_dyn()},
                "live": self._live()}

    # -- the calls -----------------------------------------------------------------
    def _press(self, ns, on):
        for n in ns:
            self.rig.ask("sw %d %d" % (n, 1 if on else 0))

    def _say(self, text):
        self.note = (self.note + [text])[-6:]

    def api(self, m, args):
        if m == "hold":
            n = int(args[0])
            self.held_ids.add(n)
            self._press([n], True)
            return True
        if m == "unhold":
            ids, self.held_ids = list(self.held_ids), set()
            self._press(ids, False)
            return True
        if m == "rip":
            n, on = int(args[0]), bool(args[1])
            (self.held_ids.add if on else self.held_ids.discard)(n)
            self._press([n], on)
            return True
        if m == "row":
            i, down = int(args[0]), bool(args[1])
            if 0 <= i < len(self.rows):
                (self.row_hit.add if down else self.row_hit.discard)(i)
                self._press(self.rows[i]["ns"], down)
            return True
        if m == "svc":
            self._press([int(args[0])], bool(args[1]))
            return True
        if m == "door":
            if self.door:
                self._press([self.door["n"]], self.door["n"] not in self.active)
            return True
        if m == "ball":
            what = args[0]
            if what in ("plunge", "drain", "reset"):
                self.rig.ask(what)
                self._say({"plunge": "plunged", "drain": "a ball drained",
                           "reset": "every ball back in the trough"}[what])
            return True
        if m == "key":
            return self.key(args[0], bool(args[2]))
        if m == "blur":
            for code in list(self.key_held):
                self.key(code, False)
            return True
        if m == "pause":
            self.set_pause(not self.paused)
            return True
        if m == "volume":
            self._write_audio(gain=max(0.0, min(100.0, float(args[0]))) / 100.0)
            return True
        if m == "mute":
            self._write_audio(muted=bool(args[0]))
            return True
        if m == "tip":
            kind, k = args[0], args[1]
            if kind == "switch":
                s = self.by_n.get(int(k))
                return self._switch_tip(s) if s else ""
            if kind == "led":
                rgb = self.lights.get(k)
                return "%s  %s" % (k, "off" if not rgb or not any(rgb)
                                   else "rgb(%d, %d, %d)" % tuple(rgb[:3]))
            return ""
        if m == "geom":
            save_geom(args[1], args[2])
            return True
        return None                    # coil / save / load / clear_alerts: not here

    def key(self, code, down):
        if code in ("Pause", "F9"):
            if down:
                self.set_pause(not self.paused)
            return True
        if code in ("KeyC", "KeyF", "KeyD"):
            if down:
                if code == "KeyC":
                    self.api("door", [])
                else:
                    self.api("ball", ["plunge" if code == "KeyF" else "drain"])
            return True
        for s, look in self.svc:
            if code in look[6]:
                self._key_switches(code, [s["n"]], down)
                return True
        for i, r in enumerate(self.rows):
            if code in r["codes"]:
                (self.row_hit.add if down else self.row_hit.discard)(i)
                self._key_switches(code, r["ns"], down)
                return True
        return False

    def _key_switches(self, code, ns, down):
        if down:
            if code in self.key_held:
                return
            self.key_held[code] = ns
            self._press(ns, True)
        else:
            self._press(self.key_held.pop(code, ns), False)

    def set_pause(self, on):
        r = self.rig.ask("pause %d" % (1 if on else 0)) or {}
        self.paused = bool(r.get("paused", on))
        if self.host:
            self.host.publish("run", self._run())

    def _write_audio(self, gain=None, muted=None):
        if not self.audio_ctl:
            return
        cur = self._audio() or {"gain": 1.0, "muted": False}
        if gain is not None:
            cur["gain"] = gain
        if muted is not None:
            cur["muted"] = muted
        try:
            tmp = self.audio_ctl + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f)
            os.replace(tmp, self.audio_ctl)
        except OSError:
            pass
        if self.host:
            self.host.publish("run", self._run())

    def blob(self, key):
        return None

    def file(self, name):
        return self.art if name == "art" else None

    # -- the live loop ---------------------------------------------------------------
    def frame(self):
        """What changed since the last frame, for the page."""
        f = {}
        sw = self._sw_dyn()
        prev = self._sent.get("sw", {})
        diff = {k: 1 for k in sw if k not in prev}
        diff.update({k: 0 for k in prev if k not in sw})
        if diff:
            f["sw"] = diff
        self._sent["sw"] = sw
        key, cur = ("fx", self._fx()) if self.field else ("grid", self._grid())
        prev = self._sent.get(key, {})
        d = {k: v for k, v in cur.items() if k not in prev or prev[k] != v}
        if d:
            f[key] = d
        self._sent[key] = cur
        for name, val in (("panel", self._panel_dyn()), ("status", self._status()),
                          ("live", self._live())):
            if self._sent.get(name) != val:
                f[name] = val
                self._sent[name] = val
        run = self._run()
        if self._sent.get("run") != run:
            self._sent["run"] = run
            if self.host:
                self.host.publish("run", run)
        return f

    def poll(self):
        while not self.stopping:
            st = self.rig.ask("state")
            if not st or not st.get("up"):
                self.misses += 1
                if self.misses >= GONE_AFTER:
                    self.host.publish("close")
                    time.sleep(0.5)
                    self.host.quit()
                    return
            else:
                self.misses = 0
                self.active = {int(k) for k in (st.get("switches") or {})}
                self.lights = st.get("lights") or {}
                self.paused = bool(st.get("paused", self.paused))
                f = self.frame()
                if f and self.host:
                    self.host.publish("frame", f)
            time.sleep(POLL_S)


def watch_parent(app, host, stream=None):
    """--parent-pipe: the Emulate AP tab holds this process's stdin open and
    closes it on Stop.  EOF = close the window and quit - the window is a
    separate browser process (pfweb's AppBackend), which a plain kill of
    this one would leave on screen."""
    if stream is None:
        # fd 0 itself: under pythonw sys.stdin can be None even with a pipe
        try:
            os.fstat(0)
        except OSError:
            return                      # no parent pipe to watch - stay up
        read = lambda: os.read(0, 4096)                 # noqa: E731
    else:
        read = lambda: stream.read(4096)                # noqa: E731
    try:
        while read():
            pass
    except (OSError, ValueError):
        pass
    if app.stopping:
        return
    app.stopping = True
    host.publish("close")
    time.sleep(0.3)
    host.quit()


def load_geom():
    try:
        with open(GEOM_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_geom(x, y):
    try:
        with open(GEOM_FILE, "w", encoding="utf-8") as f:
            json.dump({"x": int(x), "y": int(y)}, f)
    except (OSError, TypeError, ValueError):
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="American Pinball virtual playfield")
    ap.add_argument("--table", required=True, help="the rig's switches.json")
    ap.add_argument("--distro", default="")
    ap.add_argument("--slot", default=os.environ.get("PAD_SLOT", "0"))
    ap.add_argument("--title", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--audio-ctl", default="", help="the app's audio_ctl.json (Volume / Mute)")
    ap.add_argument("--parent-pipe", action="store_true",
                    help="close the window when stdin closes (the app's Stop)")
    args = ap.parse_args(argv)
    with open(args.table, encoding="utf-8") as f:
        table = json.load(f)
    title = args.title or table.get("title") or "American Pinball"
    rig = Rig(args.distro, args.slot)
    app = App(table, rig, win_path(table.get("art") or "", args.distro), title,
              slot=args.slot, label=args.label, audio_ctl=args.audio_ctl)
    host = pfweb.WebHost(PAGE_DIR, app, title="%s - virtual playfield" % title)
    app.host = host
    host.start()
    threading.Thread(target=app.poll, daemon=True, name="ap-poll").start()
    if args.parent_pipe:
        threading.Thread(target=watch_parent, args=(app, host), daemon=True,
                         name="ap-parent").start()
    g = load_geom()
    main_spec = {"page": "main", "width": 1000, "height": 980,
                 "title": "%s - virtual playfield" % title,
                 "x": g.get("x"), "y": g.get("y"), "min_size": (720, 560)}

    def on_close():
        app.stopping = True
        pos = host.geometry("main")
        if pos:
            save_geom(pos[0], pos[1])
        rig.close()
        host.stop()
    host.run(main_spec, on_close)
    return 0


if __name__ == "__main__":
    sys.exit(main())
