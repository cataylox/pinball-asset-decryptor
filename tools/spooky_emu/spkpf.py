#!/usr/bin/env python3
r"""spkpf.py - the Beetlejuice switch window: every switch by name, held with
the mouse, plus Plunge and Drain.

    pythonw tools\spooky_emu\spkpf.py [--distro PAD-Runtime] [--slot 0]

The Emulate Spooky tab opens it once the game is in attract mode.  It is
tools/bof_emu/bofpf.py's window - the same page, keys and pipe - pointed at
this rig's board (ctl.sh --stream): the board speaks the same control
protocol as the BoF boards.  Beetlejuice's switch table (sw.py) carries no
playfield positions, so the window is the labelled list only.

Keys, while this window is focused: Z / left Shift and / / right Shift the
flippers, 1 Start, 5 a coin, Space Launch, A Action, P Plunge, D Drain.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(TOOLS, "bof_emu"))
sys.path.insert(0, os.path.join(TOOLS, "spike2_emu"))
import bofpf  # noqa: E402  (the BoF switch window this one is)
import pfweb  # noqa: E402
import spkwarden  # noqa: E402
import sw  # noqa: E402

CABINET = range(80, 100)
OPTOS = {0, 1, 2, 3, 4, 5, 6, 7, 40, 41, 42, 43, 44, 45, 60, 61, 62, 63}
KEYS = {"start": 87, "coin": 90, "flipper_left": 86, "flipper_right": 80,
        "launch": 85, "action": 81}


GROUPS = ("Cabinet", "Trough", "Playfield")


def group(n):
    """bofpf groups by BoF's numbering; Beetlejuice's is its own."""
    if n in CABINET:
        return "Cabinet"
    if n <= spkwarden.SHOOTER:
        return "Trough"
    return "Playfield"


def profile():
    """bofpf's profile shape, from sw.py's switch table."""
    return {
        "title": "Beetlejuice",
        "switches": [{"n": n, "label": name.title(), "opto": n in OPTOS,
                      "tags": ["cabinet"] if n in CABINET else []}
                     for n, name in sorted(sw.SWITCHES.items())],
        "keys": dict(KEYS),
        "trough_switches": list(spkwarden.TROUGH),
        "balls": spkwarden.BALLS,
    }


class Rig(bofpf.Rig):
    """bofpf's pipe, into THIS rig's ctl.sh."""

    def __init__(self, distro, slot):
        super().__init__(distro, slot)
        ctl = os.path.join(HERE, "ctl.sh")
        self.cmd = ([c if not c.endswith("ctl.sh") else
                     (bofpf.wsl_path(ctl) if sys.platform == "win32" else ctl)
                     for c in self.cmd])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Beetlejuice switch window")
    ap.add_argument("--distro", default="")
    ap.add_argument("--slot", default=os.environ.get("PAD_SLOT", "0"))
    args = ap.parse_args(argv)
    prof = profile()
    rig = Rig(args.distro, args.slot)
    app = bofpf.App(prof, rig, "")
    for row in app.model["switches"]:
        row["group"] = group(row["n"])
    app.model["switches"].sort(key=lambda r: (GROUPS.index(r["group"]), r["n"]))
    host = pfweb.WebHost(os.path.join(TOOLS, "bof_emu", "bofpage"), app,
                         title="Beetlejuice - switches")
    app.host = host
    host.start()
    bofpf.threading.Thread(target=app.poll, daemon=True, name="spk-poll").start()
    main_spec = {"page": "main", "width": 420, "height": 860,
                 "title": "Beetlejuice - switches", "min_size": (340, 480)}

    def on_close():
        app.stopping = True
        rig.close()
        host.stop()
    host.run(main_spec, on_close)
    return 0


if __name__ == "__main__":
    sys.exit(main())
