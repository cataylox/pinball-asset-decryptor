#!/usr/bin/env python3
"""spkswitches.py <rig> [title] - write <rig>/switches.json, the table the
virtual playfield (spkpf.py -> tools/ap_emu/appf.py) works from, in the
format tools/ap_emu/apswitches.py writes for an American Pinball game - so
the window, its keys and its BALLS panel are the same for both makers.

The switches are the running game's (spktitles.py: $SPK_TITLE, else the
title run_game.sh wrote in <rig>/title, else Beetlejuice).  The Spooky games
ship no playfield picture with switch positions, so the window is the
schematic view: every switch as a row.  [title] overrides the window's
title.

THE KEYS follow the AP/Stern window (every Warden game wires its cabinet
inputs to the same numbers): 1 Start, 5 a coin, Space the Launch
button (the plunger), Down the Action button, T tilt, the arrows
the flippers (lower and upper together, as the game's own arrow keys do),
letters for playfield switches, Backspace/Esc, -, = and Enter the coin
door's BACK / - / + / SELECT, F Plunge, D Drain, Pause/F9 freeze.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spktitles  # noqa: E402

#: The same letters, in the same order, as apswitches.py (T, C, F, D are
#: tilt, the coin door, Plunge and Drain).
LETTERS = "ASZXQWGEOPMRNHJKLIUYVB"
#: apswitches.py's service names (appf.py looks the buttons up by them).
SERVICE = {94: ("exit", ("Backspace", "Escape")), 93: ("down", ("Minus", "NumpadSubtract")),
           92: ("up", ("Equal", "NumpadAdd")), 91: ("enter", ("Enter", "NumpadEnter"))}
ACTIONS = ((("KeyF",), "plunge"), (("KeyD",), "drain"), (("KeyC",), "door"),
           (("Pause", "F9"), "pause"))
CABINET = range(80, 100)


def title_key(rig=None):
    key = os.environ.get("SPK_TITLE")
    if not key and rig:
        try:
            with open(os.path.join(rig, "title")) as f:
                key = f.read().strip()
        except OSError:
            pass
    return key if key in spktitles.TITLES else "bj"


def name_of(n, t):
    if n in SERVICE:
        return SERVICE[n][0]
    if n == t["shooter"]:
        return "shooter"
    if n in t["trough"]:
        return "trough%d" % (t["trough"].index(n) + 1)
    if n == t["jam"]:
        return "troughJam"
    words = t["switches"][n].title().split()
    return words[0].lower() + "".join(words[1:])


def group_of(n, t):
    if n in CABINET:
        return "Cabinet"
    if n in t["trough"] or n == t["jam"] or n == t["shooter"] \
            or n in t["launch"].values():
        return "Trough"
    return "Playfield"


def table(title=None, key=None):
    key = key or title_key()
    t = spktitles.get(key)
    optos = spktitles.optos(key)
    # the flippers' end-of-stroke switches follow the flipper buttons on a
    # machine; they get no letter (the list still has them)
    eos = {n for n, name in t["switches"].items() if "EOS" in name.upper()}
    sws = [{"name": name_of(n, t), "n": n, "type": "NC" if n in optos else "NO",
            "label": t["switches"][n].title(), "group": group_of(n, t),
            "nc": n in optos}
           for n in sorted(t["switches"])]
    by = {s["n"]: s for s in sws}
    rows, taken = [], set()

    def add(ns, keys, codes, cabinet, hold, unplaced=False):
        found = [by[n] for n in ns if n in by and n not in taken]
        if not found:
            return
        taken.update(s["n"] for s in found)
        rows.append({"label": " + ".join(s["label"] for s in found), "keys": keys,
                     "codes": list(codes), "cabinet": cabinet,
                     "ns": [s["n"] for s in found], "hold": hold, "unplaced": unplaced})
    add([87], "1", ["Digit1", "Numpad1"], True, False)
    add([90], "5", ["Digit5", "Numpad5"], True, False)
    add([85], "Space", ["Space"], True, True)
    add([81], "Down", ["ArrowDown"], True, True)
    add([84], "T", ["KeyT"], True, False)
    add([86, 83], "Left", ["ArrowLeft"], False, True)
    add([80, 82], "Right", ["ArrowRight"], False, True)
    letters = list(LETTERS)
    for s in sws:
        if (letters and s["group"] == "Playfield" and s["n"] not in taken
                and s["n"] not in eos):
            L = letters.pop(0)
            add([s["n"]], L, ["Key" + L], False, False)
    for s in sws:
        if s["n"] in taken or s["n"] in SERVICE or s["group"] == "Trough":
            continue
        add([s["n"]], "", [], s["group"] == "Cabinet", False, unplaced=True)
    keymap = [{"codes": r["codes"], "ns": r["ns"], "action": None} for r in rows if r["codes"]]
    for n, (_name, codes) in SERVICE.items():
        keymap.append({"codes": list(codes), "ns": [n], "action": None})
    for codes, action in ACTIONS:
        keymap.append({"codes": list(codes), "ns": [], "action": action})
    return {"title": title or t["name"], "art": "", "size": None,
            "art_from": "", "lights": [], "shooter": t["shooter"],
            "coin_door": None, "balls": t["balls"], "switches": sws,
            "rows": rows, "keymap": keymap}


def main(argv):
    if not argv:
        sys.exit(__doc__)
    out = os.path.join(argv[0], "switches.json")
    with open(out + ".tmp", "w") as f:
        json.dump(table(argv[1] if len(argv) > 1 else None,
                        title_key(argv[0])), f, indent=1)
    os.rename(out + ".tmp", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
