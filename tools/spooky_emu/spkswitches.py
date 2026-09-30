#!/usr/bin/env python3
"""spkswitches.py <rig> [title] - write <rig>/switches.json, the table the
virtual playfield (spkpf.py -> tools/ap_emu/appf.py) works from, in the
format tools/ap_emu/apswitches.py writes for an American Pinball game - so
the window, its keys and its BALLS panel are the same for both makers.

Beetlejuice's switches are sw.py's table (the game's Switches.cs).  The game
ships no playfield picture with switch positions, so the window is its
schematic view: every switch as a row.

THE KEYS follow the AP/Stern window: 1 Start, 5 a coin, Space the Launch
button (Beetlejuice's plunger), Down the Action button, T tilt, the arrows
the flippers (lower and upper together, as the game's own arrow keys do),
letters for playfield switches, Backspace/Esc, -, = and Enter the coin
door's BACK / - / + / SELECT, F Plunge, D Drain, Pause/F9 freeze.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sw  # noqa: E402
import spkwarden  # noqa: E402

#: The same letters, in the same order, as apswitches.py (T, C, F, D are
#: tilt, the coin door, Plunge and Drain).
LETTERS = "ASZXQWGEOPMRNHJKLIUYVB"
#: apswitches.py's service names (appf.py looks the buttons up by them).
SERVICE = {94: ("exit", ("Backspace", "Escape")), 93: ("down", ("Minus", "NumpadSubtract")),
           92: ("up", ("Equal", "NumpadAdd")), 91: ("enter", ("Enter", "NumpadEnter"))}
ACTIONS = ((("KeyF",), "plunge"), (("KeyD",), "drain"), (("KeyC",), "door"),
           (("Pause", "F9"), "pause"))
FLIPPER_EOS = {13, 21, 35}
OPTOS = {0, 1, 2, 3, 4, 5, 6, 7, 40, 41, 42, 43, 44, 45, 60, 61, 62, 63}
CABINET = range(80, 100)


def name_of(n):
    if n in SERVICE:
        return SERVICE[n][0]
    if n == spkwarden.SHOOTER:
        return "shooter"
    if n in spkwarden.TROUGH:
        return "trough%d" % (spkwarden.TROUGH.index(n) + 1)
    if n == 2:
        return "troughJam"
    words = sw.SWITCHES[n].title().split()
    return words[0].lower() + "".join(words[1:])


def group_of(n):
    if n in CABINET:
        return "Cabinet"
    if n <= spkwarden.SHOOTER:
        return "Trough"
    return "Playfield"


def table(title="Beetlejuice"):
    sws = [{"name": name_of(n), "n": n, "type": "NC" if n in OPTOS else "NO",
            "label": sw.SWITCHES[n].title(), "group": group_of(n), "nc": n in OPTOS}
           for n in sorted(sw.SWITCHES)]
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
        # the flippers' end-of-stroke switches follow the flipper buttons
        # on a machine; they get no letter (the list still has them)
        if (letters and s["group"] == "Playfield" and s["n"] not in taken
                and s["n"] not in FLIPPER_EOS):
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
    return {"title": title, "art": "", "size": None, "art_from": "",
            "lights": [], "shooter": spkwarden.SHOOTER, "coin_door": None,
            "balls": spkwarden.BALLS, "switches": sws, "rows": rows, "keymap": keymap}


def main(argv):
    if not argv:
        sys.exit(__doc__)
    out = os.path.join(argv[0], "switches.json")
    with open(out + ".tmp", "w") as f:
        json.dump(table(*argv[1:2]), f, indent=1)
    os.rename(out + ".tmp", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
