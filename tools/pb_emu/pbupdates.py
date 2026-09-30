#!/usr/bin/env python3
"""pbupdates.py <update.upd> - the updates to unpack, in order, for a game
at the version of <update.upd>: one path a line.

Pinball Brothers ships a FULL update and then DELTAS that carry only what
changed (Predator 1.0.1 = pbpp_predator_game_1_0.upd, then
pbpp_predator_game_1_0_1.upd over it).  A person picks ONE file - the
version they want - so the rest of the chain is found beside it: every
update of the same game in the same folder up to that version, oldest first.
A later full update in the chain is harmless (it overwrites everything).

A file not named <game>_game_<version>.upd is its own chain.
"""
import os
import re
import sys

NAME = re.compile(r"^(?P<pre>.+_game_)(?P<ver>\d+(?:_\d+)*)\.upd$", re.I)


def version(name):
    m = NAME.match(name)
    return tuple(int(x) for x in m.group("ver").split("_")) if m else None


def chain(path):
    folder, name = os.path.split(os.path.abspath(path))
    m = NAME.match(name)
    if not m:
        return [path]
    want, pre = version(name), m.group("pre").lower()
    found = []
    for other in os.listdir(folder):
        mo = NAME.match(other)
        if not mo or mo.group("pre").lower() != pre:
            continue
        v = version(other)
        if v <= want and os.path.isfile(os.path.join(folder, other)):
            found.append((v, os.path.join(folder, other)))
    found.sort()
    return [p for _v, p in found] or [path]


def main(argv):
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    for p in chain(argv[0]):
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
