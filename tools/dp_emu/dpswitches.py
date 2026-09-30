#!/usr/bin/env python3
"""Give EVERY switch of a Dutch Pinball game a key, and describe them.

    dpswitches.py <version folder> <out switches.json>

The game's FakePinPROC reads switches only through config/keyboard.yaml,
and the shipped file maps a handful (Start, coins, flippers, the service
buttons, tilt).  A playfield switch - a target, the scoop, a trough opto -
has no key, so no way in.  But the map is `keysym: switch` and the game
takes any number pygame hands it, and dpinput.so can push any number.  So
the rig's copy of keyboard.yaml gets one more line per switch,
`<KEY_BASE + i>: <name>`, past every real SDL keysym (the highest is 322),
and every switch in machine.yaml can be pressed.

The switch table (name, title, wiring label, NC or not, and the switch's
spot on assets/display/machine.png - machine.yaml's machine_x/machine_y,
the game's own "machine view" drawing) goes to switches.json for sw.py,
dpctl.py and the switch window.

Rewrites keyboard.yaml IN PLACE after unlinking it: the rig's version
folder is a hard-linked copy of the cache, and writing through the link
would change the cache.  Run it on the rig's copy only.

No PyYAML (PAD-Runtime has none): machine.yaml's PRSwitches block is a
fixed two-level `name:` / `field: value` indentation, read as such.
"""
import json
import os
import sys

KEY_BASE = 1000


def _value(v):
    v = v.split("#")[0].strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    try:
        return int(v, 0)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def read_switches(machine_yaml):
    """[{name, title, label, number, nc, x, y}] in file order."""
    out, cur, inside, name_indent = [], None, False, None
    with open(machine_yaml, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            body = line.split("#")[0] if line.lstrip().startswith("#") else line
            if not body.strip():
                continue
            indent = len(body) - len(body.lstrip())
            text = body.strip()
            if indent == 0:
                inside = text.rstrip(":") == "PRSwitches"
                cur = None
                name_indent = None
                continue
            if not inside:
                continue
            if name_indent is None:
                name_indent = indent
            if indent == name_indent and text.endswith(":"):
                cur = {"name": text[:-1].strip()}
                out.append(cur)
            elif cur is not None and indent > name_indent and ":" in text:
                k, v = text.split(":", 1)
                cur[k.strip()] = _value(v)
    return [{
        "name": s["name"],
        "title": str(s.get("title") or s["name"]),
        "label": str(s.get("label") or ""),
        "number": str(s.get("number") or ""),
        "nc": str(s.get("type") or "").upper() == "NC",
        "x": s.get("machine_x") if isinstance(s.get("machine_x"), (int, float)) else None,
        "y": s.get("machine_y") if isinstance(s.get("machine_y"), (int, float)) else None,
    } for s in out]


def shipped_keys(keyboard_yaml):
    """{switch name: keysym} of the build's own keyboard map (the keys a
    player would know: 1 Start, n / m flippers ...)."""
    from_sw = {}
    section = None
    with open(keyboard_yaml, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.split("#")[0].rstrip()
            if not line.strip():
                continue
            if not line[0].isspace():
                section = line.rstrip(":").strip()
                continue
            if section != "keyboard_switch_map" or ":" not in line:
                continue
            key, names = (p.strip() for p in line.split(":", 1))
            sym = int(key) if key.isdigit() and len(key) > 1 else ord(key)
            for n in names.split(","):
                from_sw.setdefault(n.strip(), sym)
    return from_sw


def key_name(sym):
    if 32 < sym < 127:
        return chr(sym)
    return {273: "Up", 274: "Down", 275: "Right", 276: "Left"}.get(sym, "")


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    vdir, out = argv
    cfg = os.path.join(vdir, "config")
    switches = read_switches(os.path.join(cfg, "machine.yaml"))
    kb = os.path.join(cfg, "keyboard.yaml")
    shipped = shipped_keys(kb)
    with open(kb, encoding="utf-8-sig") as f:
        text = f.read()
    lines = []
    for i, s in enumerate(switches):
        s["n"] = i
        s["sym"] = KEY_BASE + i
        s["key"] = key_name(shipped[s["name"]]) if s["name"] in shipped else ""
        lines.append("  %d: %s" % (s["sym"], s["name"]))
    # Append to the keyboard_switch_map section: insert right after its
    # header, so it stays one mapping whatever sections follow it.
    marker = "keyboard_switch_map:"
    at = text.find(marker)
    if at < 0:
        sys.exit("dpswitches.py: %s has no keyboard_switch_map" % kb)
    at += len(marker)
    text = (text[:at] + "\n  # PAD emulator: every switch in machine.yaml "
            "(tools/dp_emu/dpswitches.py)\n" + "\n".join(lines) + "\n" + text[at:])
    os.remove(kb)                    # break the hard link to the cache
    with open(kb, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    art = ""
    for cand in (os.path.join(vdir, "assets", "display", "machine.png"),
                 os.path.join(vdir, "..", "assets", "display", "machine.png")):
        if os.path.isfile(cand):
            art = os.path.realpath(cand)
            break
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"switches": switches, "art": art}, f, indent=1)
    print("%d switches, %d on the machine view" %
          (len(switches), sum(1 for s in switches if s["x"] is not None)))


if __name__ == "__main__":
    main(sys.argv[1:])
