#!/usr/bin/env python3
"""pbiofiles.py - which Pinball Brothers I/O-board title a file is, and the
files to stack for the version a person picked (PAD-315).

    pbiofiles.py title <file>     the title key (alien, abba, queen) or ""
    pbiofiles.py chain <file>     the files prepare.sh stacks, one a line

A person picks ONE file - the version they want - as on the Predator rig
(tools/pb_emu/pbupdates.py); the rest is found beside it:

* a restore ISO (clonezilla-live-alien40.iso) is the whole machine: alone.
* an update (pbap412.upd) is a FULL update or a DELTA over one.  Its chain
  is the newest full update of the same title in the same folder at or below
  its version, then every delta above that up to it.  With no full update
  there, the title's restore ISO beside it is the base instead (its media);
  with neither, the delta alone - prepare.sh refuses that with the reason.

How PB names them (D:/Pinball/images/Pinball Brothers): Alien and ABBA
share the prefix "pbap"; the first digit is the major version, and Alien is
4.x, ABBA 1.x (pbap41 = 4.1, pbap411 = 4.1.1, pbap412 = 4.1.2; pbap141 =
1.4.1, pbap145 = 1.4.5).  Queen is "pbq" (pbq0210G = 2.10G).  Each digit is
one part of the version, so pbap41 < pbap411 < pbap412.  An update is FULL
when it is big (FULL_MIN): a full one carries the game's media (2+ GB), a
delta only what changed (a few MB).
"""
import os
import re
import sys

#: A full update carries the media: gigabytes.  A delta: megabytes.
FULL_MIN = 200 << 20

#: title key -> (display name, update-name pattern, restore-ISO word)
TITLES = {
    "alien": ("Alien", re.compile(r"^pbap(4\d*)\.upd$", re.I), "alien"),
    "abba": ("ABBA", re.compile(r"^pbap(1\d*)\.upd$", re.I), "abba"),
    "queen": ("Queen", re.compile(r"^pbq(\w+)\.upd$", re.I), "queen"),
}
ISO = re.compile(r"^clonezilla-live-(?P<name>.+)\.iso$", re.I)


def title(path):
    """The title key a file is for, by its name, else ""."""
    name = os.path.basename(path or "")
    m = ISO.match(name)
    if m:
        low = m.group("name").lower()
        return next((k for k, (_n, _p, word) in TITLES.items()
                     if word in low), "")
    return next((k for k, (_n, pat, _w) in TITLES.items()
                 if pat.match(name)), "")


def version(name):
    """pbap412.upd -> (4, 1, 2); pbq0210G.upd -> (0, 2, 1, 0, 'g'); else
    None.  Each digit is one part (see the docstring)."""
    for _k, (_n, pat, _w) in TITLES.items():
        m = pat.match(os.path.basename(name))
        if m:
            v = m.group(1).lower()
            digits = re.match(r"\d*", v).group(0)
            return tuple(int(c) for c in digits) + ((v[len(digits):],)
                                                    if v[len(digits):] else ())
    return None


def is_full(path):
    try:
        return os.path.getsize(path) >= FULL_MIN
    except OSError:
        return False


def chain(path):
    folder, name = os.path.split(os.path.abspath(path))
    key = title(name)
    want = version(name)
    if not key or want is None:         # an ISO, or not a name we know
        return [path]
    pat = TITLES[key][1]
    found = []
    for other in os.listdir(folder):
        if not pat.match(other):
            continue
        v = version(other)
        p = os.path.join(folder, other)
        if v is not None and v <= want and os.path.isfile(p):
            found.append((v, p))
    found.sort()
    full = [i for i, (_v, p) in enumerate(found) if is_full(p)]
    if full:
        return [p for _v, p in found[full[-1]:]]
    word = TITLES[key][2]
    isos = sorted(f for f in os.listdir(folder)
                  if ISO.match(f) and word in f.lower())
    base = [os.path.join(folder, isos[-1])] if isos else []
    return base + [p for _v, p in found] or [path]


def main(argv):
    if len(argv) == 2 and argv[0] == "title":
        print(title(argv[1]))
    elif len(argv) == 2 and argv[0] == "chain":
        for p in chain(argv[1]):
            print(p)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
