"""machinedir.py <build> - print the folder under /game/ the build lives in on
the machine (houdini, legends, hw, ...), for run_game.sh to put it back there.

The games reach for absolute paths (/game/houdini/assets/dmd/fonts,
/game/local_config/, /game/.original), so the rig runs each one at its
machine path.  That path is in the build's own bytecode: each .pyc compiled
on the machine records /game/<dir>/<its path in the build> as its file name.
Titles compiled elsewhere (Oktoberfest) fall back to the table.

Python 2.7 (marshal reads 2.7 code objects only there).
"""
import collections
import marshal
import os
import sys

FALLBACK = {"okto": "okto", "tank": "tank", "hotwheels": "hw", "lov": "legends",
            "houdini": "houdini", "bbq": "bbq"}


def main(root):
    votes = collections.Counter()
    for d, _, files in os.walk(root):
        for f in files:
            if not f.endswith(".pyc"):
                continue
            p = os.path.join(d, f)
            try:
                with open(p, "rb") as fh:
                    data = fh.read()
                if data[:4] != "\x03\xf3\r\n":
                    continue
                name = marshal.loads(data[8:]).co_filename
            except Exception:
                continue
            rel = os.path.relpath(p, root)[:-1]          # x.pyc -> x.py
            if name.startswith("/game/") and name.endswith("/" + rel):
                votes[name[len("/game/"):-len(rel)].strip("/")] += 1
    if votes:
        return votes.most_common(1)[0][0]
    base = os.path.basename(os.path.normpath(root)).split("_")[0]
    return FALLBACK.get(base, base)


if __name__ == "__main__":
    print(main(sys.argv[1]))
