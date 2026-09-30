#!/usr/bin/env python3
"""pbvol.py - hold this slot's Predator sound at the app's Volume / Mute,
live: tools/spooky_emu/spkvol.py (the same libpulse streams by pid, the same
level maths), finding the game by THIS rig's marker, PB_MARK.

    pbvol.py --ctl /mnt/c/.../audio_ctl.json --rig /var/tmp/pad_pb/rig0

pinprog plays through SDL2_mixer on WSLg's PulseAudio, which every Linux
program on the machine shares; only this slot's streams are touched.  It ends
when the game does.  Run as root (it reads the game's environment).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "spooky_emu"))
import spkvol  # noqa: E402


def slot_pids(rig):
    """The game's pids: every process whose environment carries this rig's
    PB_MARK (pbpath.sh's pb_slot_pids, in Python)."""
    want = ("PB_MARK=%s" % rig.rstrip("/")).encode()
    pids = set()
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open("/proc/%s/environ" % d, "rb") as f:
                    if want in f.read().split(b"\0"):
                        pids.add(int(d))
            except OSError:
                pass
    return pids


spkvol.slot_pids = slot_pids

if __name__ == "__main__":
    sys.exit(spkvol.main())
