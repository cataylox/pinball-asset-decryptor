#!/usr/bin/env python3
r"""spkpf.py - the Spooky switch window: every switch of the running game by
name, held with the mouse, plus Plunge and Drain.

    pythonw tools\spooky_emu\spkpf.py [--distro PAD-Runtime] [--slot 0]
                                      [--title bj|scooby|tcm|ed|looney]

The Emulate Spooky tab opens it once the game is in attract mode.  It is
tools/bof_emu/bofpf.py's window - the same page, keys and pipe - pointed at
this rig's board (ctl.sh --stream): the board speaks the same control
protocol as the BoF boards.  Which game it is comes from the board itself
(its state names the title, spktitles.py has the switch table); the Spooky
tables carry no playfield positions, so the window is the labelled list
only.

Keys, while this window is focused: Z / left Shift and / / right Shift the
flippers, 1 Start, 5 a coin, Space Launch, A Action, P Plunge, D Drain.
Every Warden game wires these cabinet inputs to the same numbers.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(TOOLS, "bof_emu"))
sys.path.insert(0, os.path.join(TOOLS, "spike2_emu"))
import bofpf  # noqa: E402  (the BoF switch window this one is)
import pfweb  # noqa: E402
import spktitles  # noqa: E402

CABINET = range(80, 100)
KEYS = {"start": 87, "coin": 90, "flipper_left": 86, "flipper_right": 80,
        "launch": 85, "action": 81}


GROUPS = ("Cabinet", "Trough", "Playfield")


def group(n, key=None):
    """bofpf groups by BoF's numbering; a Spooky game's is its own."""
    t = spktitles.get(key)
    if n in CABINET:
        return "Cabinet"
    if n in t["trough"] or n == t["jam"] or n == t["shooter"] \
            or n in t["launch"].values():
        return "Trough"
    return "Playfield"


def profile(key=None):
    """bofpf's profile shape, from the title's switch table."""
    t = spktitles.get(key)
    optos = spktitles.optos(key)
    return {
        "title": t["name"],
        "switches": [{"n": n, "label": name.title(), "opto": n in optos,
                      "tags": ["cabinet"] if n in CABINET else []}
                     for n, name in sorted(t["switches"].items())],
        "keys": dict(KEYS),
        "trough_switches": list(t["trough"]),
        "balls": t["balls"],
    }


class Rig(bofpf.Rig):
    """bofpf's pipe, into THIS rig's ctl.sh."""

    def __init__(self, distro, slot):
        super().__init__(distro, slot)
        ctl = os.path.join(HERE, "ctl.sh")
        self.cmd = ([c if not c.endswith("ctl.sh") else
                     (bofpf.wsl_path(ctl) if sys.platform == "win32" else ctl)
                     for c in self.cmd])

    def title_key(self):
        """The running game's spktitles key, from the board; None when the
        board does not answer."""
        try:
            key = json.loads(self.ask("state") or "{}").get("key")
        except ValueError:
            return None
        return key if key in spktitles.TITLES else None


def serve(distro, slot, key=None):
    """The window's page, served and polling: (app, rig, host).  main()
    shows it; a capture script shows it to a headless browser instead."""
    rig = Rig(distro, slot)
    key = key or rig.title_key() or "bj"
    app = bofpf.App(profile(key), rig, "")
    for row in app.model["switches"]:
        row["group"] = group(row["n"], key)
    app.model["switches"].sort(key=lambda r: (GROUPS.index(r["group"]), r["n"]))
    name = spktitles.get(key)["name"]
    host = pfweb.WebHost(os.path.join(TOOLS, "bof_emu", "bofpage"), app,
                         title="%s - switches" % name)
    app.host = host
    app.title_key = key
    host.start()
    bofpf.threading.Thread(target=app.poll, daemon=True, name="spk-poll").start()
    return app, rig, host


def main(argv=None):
    ap = argparse.ArgumentParser(description="Spooky switch window")
    ap.add_argument("--distro", default="")
    ap.add_argument("--slot", default=os.environ.get("PAD_SLOT", "0"))
    ap.add_argument("--title", choices=sorted(spktitles.TITLES), default=None)
    args = ap.parse_args(argv)
    app, rig, host = serve(args.distro, args.slot, args.title)
    name = spktitles.get(app.title_key)["name"]
    main_spec = {"page": "main", "width": 560, "height": 860,
                 "title": "%s - switches" % name, "min_size": (340, 480)}

    def on_close():
        app.stopping = True
        rig.close()
        host.stop()
    host.run(main_spec, on_close)
    return 0


if __name__ == "__main__":
    sys.exit(main())
