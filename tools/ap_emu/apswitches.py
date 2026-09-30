#!/usr/bin/env python3
"""apswitches.py <rig> <build> [title] - write <rig>/switches.json, the
table the virtual playfield (appf.py) and apctl.py work from.

The running game wrote <rig>/switches at boot (py/aprun.py: name, P-ROC
number, NO/NC, label per line) and <rig>/pfpos.json (positions the machine
yaml gives, and the ball count).  WHERE things are on the playfield comes
from the game too, from the best of two sources:

* AP's own playfield simulator (Galactic Tank Force 2026): the machine yaml
  gives LEDs, and the switches it tags `sim`, an x/y on
  assets/screen/service/playfield.png.
* The developers' OSC switch-matrix layout (`<title>.layout`): `bg_image`, a
  playfield picture beside it (shipped as .jpg or .png whatever the layout
  says), and `button_locations` / `lamp_locations` in its pixels.  Only some
  were ever filled in (PAD-292 measured them): Legends of Valhalla's and
  Houdini's houdini.layout are real; Hot Wheels', Oktoberfest's and Tank's
  are defaults piled at the edges or off the picture, and are refused - a
  layout needs most points on its picture and spread over it.  Legends of
  Valhalla's is ~14 px right and ~4 px high of its picture (its rollover
  slots, top to bottom); CALIBRATION moves it back.

The first usable layout seen for a title is kept in
$AP_ROOT/layouts/<machine dir>/ (Legends of Valhalla 26.08.22 ships none),
and a build without one uses that - or another cached build's.

Each switch gets a group (Cabinet, Trough, Playfield).  Switches the machine
yaml calls unused are left out.  Runs on the rig's Python 3 ($AP_PY3: it has
PyYAML; PAD-Runtime's has not).
"""
import glob
import json
import os
import re
import shutil
import struct
import sys

import yaml

AP_ROOT = os.environ.get("AP_ROOT", "/var/tmp/pad_ap")

#: (machine dir, layout file) -> (dx, dy) added to its points (PAD-292).
CALIBRATION = {
    ("legends", "lov.layout"): (-14, 4),
    ("legends", "lov2.layout"): (-14, 4),
}

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


def image_size(path):
    """(width, height) of a PNG or JPEG from its header, or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:2] != b"\xff\xd8":
                return None
            f.seek(2)
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                while b == b"\xff":
                    b = f.read(1)
                if not b:
                    return None
                marker = b[0]
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    continue
                seg = struct.unpack(">H", f.read(2))[0]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">xHH", f.read(5))
                    return w, h
                f.seek(seg - 2, 1)
    except (OSError, struct.error):
        return None


def picture_of(layout, doc):
    """The layout's picture: bg_image beside it, or the same name as .png /
    .jpg (the layouts say .jpg; most titles ship .png)."""
    pic = os.path.join(os.path.dirname(layout), str(doc.get("bg_image") or ""))
    stem = os.path.splitext(pic)[0]
    for cand in (pic, stem + ".png", stem + ".jpg"):
        if os.path.isfile(cand):
            return cand
    return ""


def read_layout(path):
    """{path, pic, size, switches: {name: (x, y)}, lamps: {name: (x, y)}}
    of one .layout, or None."""
    try:
        with open(path) as f:
            doc = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return None
    pic = picture_of(path, doc)
    size = image_size(pic) if pic else None

    def spots(key):
        out = {}
        for item in doc.get(key) or []:
            for name, xy in (item or {}).items():
                try:
                    out[str(name)] = (int(xy["x"]), int(xy["y"]))
                except (KeyError, TypeError, ValueError):
                    pass
        return out
    return {"path": path, "pic": pic, "size": size,
            "switches": spots("button_locations"), "lamps": spots("lamp_locations")}


def usable(lay):
    """A layout somebody actually laid out: a picture, most of its switch
    points on it, spread over most of its height."""
    if not lay or not lay["pic"] or not lay["size"] or not lay["switches"]:
        return False
    w, h = lay["size"]
    pts = list(lay["switches"].values())
    inside = [p for p in pts if 0 < p[0] < w and 0 < p[1] < h]
    if len(inside) < 0.6 * len(pts) or len(set(inside)) < 0.6 * len(inside):
        return False
    ys = sorted(p[1] for p in inside)
    return (ys[int(len(ys) * 0.9)] - ys[int(len(ys) * 0.1)]) >= 0.5 * h


def layouts_in(folder):
    return sorted(glob.glob(os.path.join(folder, "*.layout"))
                  + glob.glob(os.path.join(folder, "*", "*.layout")))


def best_layout(folder, names):
    """The usable layout in folder placing most of names, or None."""
    best, score = None, -1
    for path in layouts_in(folder):
        lay = read_layout(path)
        if not usable(lay):
            continue
        n = len(names & set(lay["switches"]))
        if n > score:
            best, score = lay, n
    return best


def machine_dir(build):
    try:
        with open(os.path.join(build, "machine_dir")) as f:
            return f.read().strip()
    except OSError:
        return ""


def keep_layout(mdir, lay, root=AP_ROOT):
    """Copy a title's layout and its picture to <root>/layouts/<mdir>/ (the
    picture under the name the layout gives it), once."""
    if not mdir:
        return
    dest = os.path.join(root, "layouts", mdir)
    if os.path.isfile(os.path.join(dest, os.path.basename(lay["path"]))):
        return
    try:
        os.makedirs(dest, exist_ok=True)
        rel = os.path.relpath(lay["pic"], os.path.dirname(lay["path"]))
        os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
        shutil.copy2(lay["pic"], os.path.join(dest, rel))
        shutil.copy2(lay["path"], os.path.join(dest, os.path.basename(lay["path"])))
    except OSError:
        pass


def find_layout(build, names, root=AP_ROOT):
    """(layout or None, where) - the build's own, else the title's kept one,
    else another cached build's of the same title."""
    mdir = machine_dir(build)
    lay = best_layout(build, names)
    if lay:
        keep_layout(mdir, lay, root)
        return lay, "the game's own layout"
    if not mdir:
        return None, ""
    lay = best_layout(os.path.join(root, "layouts", mdir), names)
    if lay:
        return lay, "the layout kept from an earlier %s build" % mdir
    others = [b for b in glob.glob(os.path.join(root, "cache", "*"))
              if os.path.realpath(b) != os.path.realpath(build)
              and machine_dir(b) == mdir]
    for other in sorted(others, key=os.path.getmtime, reverse=True):
        lay = best_layout(other, names)
        if lay:
            keep_layout(mdir, lay, root)
            return lay, "the layout of %s" % os.path.basename(other)
    return None, ""


def simulator_art(build):
    """AP's own playfield simulator picture (assets/screen/service/playfield.png)."""
    hits = sorted(glob.glob(os.path.join(build, "*", "assets", "screen", "service", "playfield.png"))
                  + glob.glob(os.path.join(build, "assets", "screen", "service", "playfield.png")))
    return hits[0] if hits else ""


def read_pos(rig):
    try:
        with open(os.path.join(rig, "pfpos.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def placements(rig, build, names, root=AP_ROOT):
    """(art, (w, h) or None, {switch: (x, y)}, {light: (x, y)}, where)."""
    pos = read_pos(rig)
    art = simulator_art(build)
    if art and pos.get("leds"):
        size = image_size(art)
        if size:
            return (art, size, {k: tuple(v) for k, v in pos.get("switches", {}).items()},
                    {k: tuple(v) for k, v in pos["leds"].items()},
                    "AP's playfield simulator")
    lay, where = find_layout(build, names, root)
    if not lay:
        return "", None, {}, {}, ""
    dx, dy = CALIBRATION.get((machine_dir(build), os.path.basename(lay["path"])), (0, 0))
    move = lambda d: {k: (x + dx, y + dy) for k, (x, y) in d.items()}   # noqa: E731
    return lay["pic"], lay["size"], move(lay["switches"]), move(lay["lamps"]), where


def table(rig, build, title="", root=AP_ROOT):
    sws = [s for s in read_switches(os.path.join(rig, "switches"))
           if not unused(s["name"], s["label"])]
    art, size, spots, lamps, where = placements(rig, build, {s["name"] for s in sws}, root)
    w, h = size or (0, 0)

    def on_art(xy):
        # a point the developers parked beside the picture is not placed
        return xy is not None and 2 <= xy[0] <= w - 2 and 2 <= xy[1] <= h - 2
    for s in sws:
        s["group"] = group_of(s["name"], s["label"])
        s["nc"] = s["type"] == "NC"
        # only playfield switches go on the picture: the developers' layouts
        # park the coins, the service buttons and the trough in a corner of
        # it, and the key panel has those (its rows, SERVICE, BALLS)
        xy = spots.get(s["name"])
        if s["group"] == "Playfield" and on_art(xy):
            s["x"], s["y"] = xy
    by = {s["name"]: s["n"] for s in sws}
    balls = read_pos(rig).get("balls")
    return {
        "title": title or os.path.basename(build.rstrip("/")),
        "art": art if size else "",
        "size": [w, h] if size else None,
        "art_from": where,
        # the lights the picture places (the rest are in lights.json only)
        "lights": sorted([[k, xy[0], xy[1]] for k, xy in lamps.items() if on_art(xy)]),
        "shooter": by.get("shooter"),
        "coin_door": by.get("coinDoor"),
        "balls": balls if isinstance(balls, int) else None,
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
    print("%s: %d switches, %d on the playfield picture, %d lights placed%s" % (
        out, len(t["switches"]), sum(1 for s in t["switches"] if "x" in s), len(t["lights"]),
        " (%s)" % t["art_from"] if t["art_from"] else
        " (no playfield layout for this game: the switch list and the light grid)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
