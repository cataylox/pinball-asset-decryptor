#!/usr/bin/env python3
"""apswitches.py <rig> <build> [title] - write <rig>/switches.json, the
table the switch window (appf.py) and apctl.py work from.

The running game wrote <rig>/switches at boot (py/aprun.py: name, P-ROC
number, NO/NC, label per line).  The PLAYFIELD comes from the game too:
every AP title ships its developers' OSC switch-matrix layout
(`<title>.layout`: `bg_image` - a playfield picture beside it - and
`button_locations`, a list of {switch name: {x, y}} in that picture's
pixels), which their desktop switch GUI drew.  The layout that places the
most of this game's switches wins (Houdini ships two).

Each switch gets a group (Cabinet, Trough, Playfield), and the cabinet's
buttons a key the window answers while it is focused.  Switches the machine
yaml calls unused are left out.

Runs on the rig's Python 3 ($AP_PY3: it has PyYAML; PAD-Runtime's has not).
"""
import glob
import json
import os
import re
import sys

import yaml

#: (name pattern, key, hold) - the window's keyboard.  Flippers and the
#: cabinet's extra buttons hold while the key is down; the rest tap.
KEYS = (
    (r"^flipper\w*L$", "LShift", True),
    (r"^flipper\w*R$", "RShift", True),
    (r"^startButton$", "1", False),
    (r"^coin1$", "5", False),
    (r"^(ActionButton|magnaGrab|diverter|launchButton)$", "Space", True),
    (r"^exit$", "7", False),
    (r"^down$", "8", False),
    (r"^up$", "9", False),
    (r"^enter$", "0", False),
    (r"^tilt$", "T", False),
)

CABINET = re.compile(r"^(flipper|startButton|ActionButton|launchButton|magnaGrab|"
                     r"diverter|enter$|exit$|up$|down$|tilt|slamTilt|coin|dollar)")


def unused(name, label):
    return (name.startswith(("unused", "TBD"))
            or re.match(r"^(not used|unused)\b", label.strip(), re.I) is not None
            or (re.match(r"^SD\d+$", name) is not None and not label.strip()))


def group_of(name, label):
    if name.startswith("trough") or name == "shooter":
        return "Trough"
    if CABINET.match(name) or "button" in label.lower():
        return "Cabinet"
    return "Playfield"


def read_switches(path):
    out = []
    with open(path) as f:
        for line in f:
            parts = line.rstrip("\n").split(" ", 3)
            if len(parts) >= 3:
                out.append({"name": parts[0], "n": int(parts[1]), "type": parts[2],
                            "label": parts[3] if len(parts) > 3 else ""})
    return out


def read_layout(path):
    """(picture path, {name: (x, y)}) of one .layout, or None."""
    try:
        with open(path) as f:
            doc = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return None
    pic = os.path.join(os.path.dirname(path), str(doc.get("bg_image") or ""))
    spots = {}
    for item in doc.get("button_locations") or []:
        for name, xy in (item or {}).items():
            try:
                spots[str(name)] = (int(xy["x"]), int(xy["y"]))
            except (KeyError, TypeError, ValueError):
                pass
    return (pic if os.path.isfile(pic) else ""), spots


def best_layout(build, names):
    best = ("", {}, -1)
    for path in sorted(glob.glob(os.path.join(build, "*.layout"))
                       + glob.glob(os.path.join(build, "*", "*.layout"))):
        got = read_layout(path)
        if not got or not got[0]:
            continue
        score = len(names & set(got[1]))
        if score > best[2]:
            best = (got[0], got[1], score)
    return best[0], best[1]


def table(rig, build, title=""):
    sws = [s for s in read_switches(os.path.join(rig, "switches"))
           if not unused(s["name"], s["label"])]
    art, spots = best_layout(build, {s["name"] for s in sws})
    for s in sws:
        s["group"] = group_of(s["name"], s["label"])
        s["nc"] = s["type"] == "NC"
        if s["name"] in spots:
            s["x"], s["y"] = spots[s["name"]]
        for pat, key, hold in KEYS:
            if re.match(pat, s["name"]):
                s["key"], s["hold"] = key, hold
                break
    by = {s["name"]: s["n"] for s in sws}
    return {
        "title": title or os.path.basename(build.rstrip("/")),
        "art": art,
        # the bar's buttons: Plunge (the shooter lane lets go), Coin door
        "shooter": by.get("shooter"),
        "coin_door": by.get("coinDoor"),
        "switches": sws,
    }


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    rig, build = argv[0], os.path.realpath(argv[1])
    t = table(rig, build, argv[2] if len(argv) > 2 else "")
    out = os.path.join(rig, "switches.json")
    with open(out + ".tmp", "w") as f:
        json.dump(t, f, indent=1)
    os.rename(out + ".tmp", out)
    print("%s: %d switches, %d on the playfield picture" % (
        out, len(t["switches"]), sum(1 for s in t["switches"] if "x" in s)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
