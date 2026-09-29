#!/usr/bin/env python3
"""gen_profile.py - build a title profile for bofhw.py from the title's
decompiled scripts plus a small hand-written overrides file.

    gen_profile.py <decompiled dir> <overrides.json> <out.json>

<decompiled dir> is GDRE's .gd output with the res:// tree kept
(autoloads/switches.gd, autoloads/coils.gd, autoloads/game.gd).  The
overrides carry what is protocol, not table: port list, firmware versions,
node boards, BICS dialect.  Everything the switch panel needs (number, name,
label, opto flag, tags, test-screen position) and the ball model's anchors
(trough, shooter lane, eject/launch drivers, coin door) come from the tables,
so a new title needs only its overrides written.

Dev-time only: the app never runs GDRE; it ships the generated JSON.
"""
import json
import re
import sys

CONST_RE = re.compile(r"^const\s+([A-Z0-9_]+)\s*(?::?=)\s*(\d+)", re.M)
SW_ITEM_RE = re.compile(r"items\[([A-Z0-9_]+)\]\s*=\s*\{(.*?)\"tags\"\s*=\s*\[(.*?)\]\s*\}",
                        re.S)
COIL_ITEM_RE = re.compile(r"items\[([A-Z0-9_]+)\]\s*=\s*\{(.*?)\n\s*\"tags\"\s*:\s*\[(.*?)\]\s*\}",
                          re.S)


def field(body, key, sep):
    m = re.search(r'"%s"\s*%s\s*("([^"]*)"|[^,\n]+)' % (key, re.escape(sep)), body)
    if not m:
        return None
    return m.group(2) if m.group(2) is not None else m.group(1).strip()


def parse(path, item_re, sep):
    with open(path, encoding="utf-8", errors="replace") as f:
        src = f.read()
    # The scripts open with a doc string whose worked example is itself an
    # items[...] = {...} block; drop string-literal lines so it can't match.
    src = re.sub(r'^\s*"\\n.*"\s*$', "", src, flags=re.M)
    consts = {k: int(v) for k, v in CONST_RE.findall(src)}
    items = []
    for name, body, tags in item_re.findall(src):
        if name not in consts:
            continue
        item = {"n": consts[name], "const": name,
                "tags": re.findall(r'"([^"]+)"', tags)}
        label = field(body, "display_name", sep)
        if label:
            item["label"] = label
        for key, out in (("reversed", "opto"),):
            v = field(body, key, sep)
            if v is not None:
                item[out] = v == "true"
        for key, out in (("x_position", "x"), ("y_position", "y")):
            v = field(body, key, sep)
            if v is not None and re.fullmatch(r"-?\d+", v):
                item[out] = int(v)
        items.append(item)
    items.sort(key=lambda i: i["n"])
    return consts, items


def main():
    src_dir, overrides_path, out_path = sys.argv[1:4]
    sw_consts, switches = parse(src_dir + "/autoloads/switches.gd", SW_ITEM_RE, "=")
    coil_consts, coils = parse(src_dir + "/autoloads/coils.gd", COIL_ITEM_RE, ":")
    with open(src_dir + "/autoloads/game.gd", encoding="utf-8") as f:
        m = re.search(r"num_balls_total\s*=\s*(\d+)", f.read())
    balls = int(m.group(1)) if m else None
    with open(overrides_path) as f:
        prof = json.load(f)

    def sw(name):
        return sw_consts.get(name)

    trough = sorted(n for k, n in sw_consts.items()
                    if re.fullmatch(r"TROUGH\d+", k))
    prof.setdefault("balls", balls or len(trough))
    anchors = {
        "trough_switches": trough,
        "shooter_switch": sw("SHOOTER_LANE"),
        "coin_door_switch": sw("INTERLOCK"),
        "trough_eject_driver": coil_consts.get("TROUGH_EJECT"),
        "launch_driver": coil_consts.get("AUTOPLUNGER"),
    }
    for k, v in anchors.items():
        prof.setdefault(k, v)
    # Closed coin door (INTERLOCK active = high power on) and a full trough:
    # exactly the title's ball count - a trough that reads one ball too many
    # is "not full" to the game, and Start is refused (Labyrinth has 5 balls
    # in 6 positions).
    prof.setdefault("active_at_boot",
                    [n for n in [anchors["coin_door_switch"]] if n is not None]
                    + trough[:prof["balls"]])
    keys = {}
    for key, const in (("start", "START"), ("coin", "COIN_1"),
                       ("enter", "ENTER"), ("exit", "EXIT"), ("up", "UP"),
                       ("down", "DOWN"), ("flipper_left", "FLIPPER_BUTTON_LL"),
                       ("flipper_right", "FLIPPER_BUTTON_LR"),
                       ("flipper_upper_left", "FLIPPER_BUTTON_UL"),
                       ("flipper_upper_right", "FLIPPER_BUTTON_UR"),
                       ("action", "ACTION_BUTTON"), ("launch", "LAUNCH"),
                       ("tilt", "TILT"), ("coin_door", "INTERLOCK")):
        if sw(const) is not None:
            keys[key] = sw(const)
    prof.setdefault("keys", keys)
    prof["switches"] = switches
    prof["coils"] = [{k: c[k] for k in ("n", "const", "label") if k in c}
                     for c in coils]
    with open(out_path, "w", newline="\n") as f:
        json.dump(prof, f, indent=1)
        f.write("\n")
    print("%s: %d switches, %d coils, %s balls, trough %s, shooter %s, eject %s" % (
        out_path, len(switches), len(coils), prof["balls"], trough, anchors["shooter_switch"],
        anchors["trough_eject_driver"]))


if __name__ == "__main__":
    main()
