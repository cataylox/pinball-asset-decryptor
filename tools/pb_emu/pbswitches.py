#!/usr/bin/env python3
"""pbswitches.py <rig> [title] - write <rig>/switches.json, the table the
virtual playfield (pbpf.py -> tools/ap_emu/appf.py) works from, in the format
tools/ap_emu/apswitches.py writes for an American Pinball game (and
tools/spooky_emu/spkswitches.py for a Spooky one) - so the window, its keys
and its BALLS panel are the same for every maker.

The switches are the running game's own names (pbtitles.py, read from
pinprog's names_of_switches).  Predator ships no playfield picture with
switch positions, so the window is appf's schematic view: every switch as a
row.  [title] overrides the window's title.

THE KEYS follow the AP/Stern window: 1 Start, 5 a coin, Space the Launch
button, T tilt, the arrows the flippers (lower and upper together, as the
machine's buttons are wired), letters for playfield switches,
Backspace/Esc, -, = and Enter the coin door's ESCAPE / DOWN / UP / ENTER,
F Plunge, D Drain, Pause/F9 freeze.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pbtitles  # noqa: E402

#: The same letters, in the same order, as apswitches.py (T, C, F, D are
#: tilt, the coin door, Plunge and Drain).
LETTERS = "ASZXQWGEOPMRNHJKLIUYVB"
#: appf.py's service names (it looks the buttons up by them) -> the key codes
SERVICE_CODES = {"exit": ("Backspace", "Escape"),
                 "down": ("Minus", "NumpadSubtract"),
                 "up": ("Equal", "NumpadAdd"),
                 "enter": ("Enter", "NumpadEnter")}
ACTIONS = ((("KeyF",), "plunge"), (("KeyD",), "drain"),
           (("Pause", "F9"), "pause"))


def title_key(rig=None):
    key = os.environ.get("PB_TITLE")
    if not key and rig:
        try:
            with open(os.path.join(rig, "title")) as f:
                key = f.read().strip()
        except OSError:
            pass
    return key if key in pbtitles.TITLES else "predator"


def _cab(t):
    return {k: int(v) for k, v in t.get("cabinet", {}).items()}


def name_of(n, t, svc):
    if n in svc:
        return svc[n]
    if n == t["shooter_switch"]:
        return "shooter"
    if n in t["trough_switches"]:
        return "trough%d" % (t["trough_switches"].index(n) + 1)
    if n == t.get("jam_switch"):
        return "troughJam"
    words = t["switches"][str(n)].title().split()
    return words[0].lower() + "".join(words[1:])


def group_of(n, t):
    if "cabinet_switches" in t:         # a profile that lists them (pbio)
        if n in t["cabinet_switches"]:
            return "Cabinet"
    elif n < t.get("first_playfield_switch", 24) and n not in t["trough_switches"]:
        return "Cabinet"
    if (n in t["trough_switches"] or n == t.get("jam_switch")
            or n == t["shooter_switch"]):
        return "Trough"
    return "Playfield"


def table(title=None, key=None, t=None):
    """The window's table for Predator (*key*), or for the profile *t* in
    pbtitles' shape - tools/pbio_emu/pbioswitches.py's Alien and ABBA."""
    if t is None:
        t = pbtitles.TITLES[key or title_key()]
    optos = set(t.get("optos", []))
    cab = _cab(t)
    svc = {cab[k]: k for k in SERVICE_CODES if k in cab}
    # the flippers' end-of-stroke switches follow the flipper buttons on a
    # machine; they get no letter (the list still has them)
    eos = {int(n) for n, name in t["switches"].items() if "EOS" in name.split()}
    ns = sorted(int(n) for n in t["switches"])
    sws = [{"name": name_of(n, t, svc), "n": n, "type": "NC" if n in optos else "NO",
            "label": t["switches"][str(n)].title(), "group": group_of(n, t),
            "nc": n in optos}
           for n in ns]
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

    def c(*names):
        return [cab[n] for n in names if n in cab]
    add(c("start"), "1", ["Digit1", "Numpad1"], True, False)
    add(c("coin"), "5", ["Digit5", "Numpad5"], True, False)
    add(c("launch"), "Space", ["Space"], True, True)
    add(c("tilt"), "T", ["KeyT"], True, False)
    add(c("lflip", "ulflip"), "Left", ["ArrowLeft"], False, True)
    add(c("rflip", "urflip"), "Right", ["ArrowRight"], False, True)
    letters = list(LETTERS)
    for s in sws:
        if (letters and s["group"] == "Playfield" and s["n"] not in taken
                and s["n"] not in eos):
            L = letters.pop(0)
            add([s["n"]], L, ["Key" + L], False, False)
    for s in sws:
        if s["n"] in taken or s["n"] in svc or s["group"] == "Trough":
            continue
        add([s["n"]], "", [], s["group"] == "Cabinet", False, unplaced=True)
    keymap = [{"codes": r["codes"], "ns": r["ns"], "action": None} for r in rows if r["codes"]]
    for n, name in svc.items():
        keymap.append({"codes": list(SERVICE_CODES[name]), "ns": [n], "action": None})
    for codes, action in ACTIONS:
        keymap.append({"codes": list(codes), "ns": [], "action": action})
    return {"title": title or t["title"], "art": "", "size": None,
            "art_from": "", "lights": [], "shooter": t["shooter_switch"],
            "coin_door": None, "balls": len(t["trough_switches"]),
            "switches": sws, "rows": rows, "keymap": keymap}


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
