#!/usr/bin/env python3
"""disc.py [seconds] - spin james_bond_60th_le's ODDJOB DISC.

    disc.py            spin it for 3 s
    disc.py 10         spin it for 10 s
    disc.py 0          stop a spin left running (a killed disc.py)

THE MECHANISM. Bond's Oddjob disc is a large rotating platform read by an
absolute ANGLE SENSOR on a node board, not by a switch anyone can press - which
is how it was reported (David, 2026-08-28: "I don't see the optos on the
playfield or the switch matrix for me to interact with").

HOW THE GAME READS IT (PAD-259, read out of james_bond_60th_le 1.11; the long
comment is at nb_disc in hwshim.c). The board raises its `Angle Sensor
Threshold` input whenever the angle has moved; each rising edge makes the game
send node-bus cmd 61, and the reply carries the angle. The ten `Angle Sensor
0..9` rows are NOT read - item 86 drove them as an angle word and nothing moved.

So spinning the disc is RIPPING the Threshold input: the shim then toggles it
on every scan of its node, and turns the disc PAD_DISC_STEP counts (default
24 of 1024 a turn) on every read that follows an edge. This sets the rip and
clears it again; a right-hold on the same switch in the playfield window does
exactly the same.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo  # noqa: E402
import padsw  # noqa: E402
import trough  # noqa: E402

#: The switch row the board raises when the angle moved. By NAME, from the
#: title's own switch list, so no id is baked in (james_bond_60th_le: 109).
THRESHOLD_NAME = "angle sensor threshold"

DEFAULT_S = 3.0


def threshold_id():
    """The Threshold switch id of the title the rig runs, or None."""
    path = gameinfo.table("switch_list.txt")
    for row in trough.load_list(path) if path else []:
        if row["name"].strip().lower() == THRESHOLD_NAME:
            return row["id"]
    return None


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_S
    sw = threshold_id()
    if sw is None:
        print("disc.py: this title has no '%s' switch - no spinning disc"
              % THRESHOLD_NAME, file=sys.stderr)
        return 1
    m = padsw.open_block()
    if m is None:
        return 1
    try:
        if secs <= 0:
            padsw.set_spin(m, sw, 0)
            print("disc stopped (id %d)" % sw)
            return 0
        padsw.set_spin(m, sw, 1)
        try:
            time.sleep(secs)
        finally:
            padsw.set_spin(m, sw, 0)
        print("disc spun for %g s (rip on id %d)" % (secs, sw))
    finally:
        m.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
