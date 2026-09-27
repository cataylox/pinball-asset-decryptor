"""Which Spike 2 emulator rig this app drives, and who holds the others.

The rig side is ``tools/spike2_emu/padpath.sh`` ("RIG SLOTS") and
``riglock.sh``; the design is ``docs/plans/rig_slots.md``. In one paragraph:
a PC can run several emulator rigs at once, one per session. Rig 0 is the
ordinary one and what every installed copy of the app uses; rig N >= 1 is a
complete rig of its own, selected by ``PAD_SLOT=N`` in the environment of every
rig command. Who holds which rig is written to a BOARD on the Windows side
(``%USERPROFILE%\\.pad-rig``), one JSON line per file:

    slot-N.lock   {"slot","who","what","distro","user","taken"}
    slot-N.run    {"slot","game","label","distro","root","pid","started"},
                  touched every ~10 s while the run lives

This module is the app's half: the environment its rig commands carry, the
board as the Emulate tab shows it, and the rig an app launched from a triage
ticket claims for itself so that two ticket apps never share one.

NOTHING HERE CHANGES AN ORDINARY INSTALL. With no PAD_SLOT, PAD_LABEL or
PAD_TICKET in the environment, rig_env() is empty and the app drives rig 0
exactly as before; the board is only read, and an absent board reads as five
free rigs.
"""
import atexit
import json
import os
import sys
import time

#: Rigs a PC offers (padpath.sh's PAD_SLOTS_MAX).
SLOTS_MAX = 4
#: A run record whose heartbeat is older than this is a run that died hard
#: (riglock.sh's RUN_FRESH).
RUN_FRESH_S = 120

#: The five rig colours, the same ones the playfield window's band and chip
#: use (pfpage/pf.css --rig-N) and the triage dashboard draws.
COLOURS = ("#8b9196", "#4fb3d9", "#c08cf0", "#f0845d", "#6fcf8a")

_claimed = []           # [slot] this process took and must give back


def board_dir():
    """Where the board lives, as THIS side can open it."""
    v = os.environ.get("PAD_BOARD_WIN")         # tests, and a moved board
    if v:
        return v
    if sys.platform == "win32":
        return os.path.join(os.environ.get("USERPROFILE")
                            or os.path.expanduser("~"), ".pad-rig")
    return os.path.join(os.path.expanduser("~"), ".pad-rig")


def slot():
    """The rig this app drives: PAD_SLOT, or 0."""
    try:
        return max(0, min(SLOTS_MAX, int(os.environ.get("PAD_SLOT") or 0)))
    except ValueError:
        return 0


def label():
    """Who this app's runs are for: PAD_LABEL, else the triage ticket."""
    return (os.environ.get("PAD_LABEL") or os.environ.get("PAD_TICKET") or "").strip()


def rig_env():
    """``NAME=value`` entries every rig command carries. Empty on an ordinary
    install - rig 0, no label - so nothing about those commands changes."""
    out = []
    if slot():
        out.append("PAD_SLOT=%d" % slot())
    if label():
        out.append("PAD_LABEL=%s" % label())
    return out


def title_tag():
    """The app window's own tag, in the words the rig's windows use."""
    n, l = slot(), label()
    if n:
        return "rig %d%s" % (n, (": " + l) if l else "")
    return ""


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rec = json.loads(fh.readline() or "null")
        return rec if isinstance(rec, dict) else None, os.path.getmtime(path)
    except (OSError, ValueError):
        return None, 0


def board(now=None):
    """Every rig, as the Emulate tab and the triage dashboard show it:
    [{"slot", "colour", "holder", "doing", "held_s", "run": {...} | None}]."""
    now = now or time.time()
    d = board_dir()
    out = []
    for n in range(0, SLOTS_MAX + 1):
        lock, lm = _read(os.path.join(d, "slot-%d.lock" % n))
        run, rm = _read(os.path.join(d, "slot-%d.run" % n))
        row = {"slot": n, "colour": COLOURS[n], "holder": "", "doing": "",
               "held_s": None, "distro": "", "run": None, "mine": n == slot()}
        if lock:
            row.update(holder=str(lock.get("who") or ""),
                       doing=str(lock.get("what") or ""),
                       held_s=int(now - (lock.get("taken") or lm)),
                       distro=str(lock.get("distro") or ""))
        if run:
            row["run"] = {"game": str(run.get("game") or ""),
                          "label": str(run.get("label") or ""),
                          "up_s": int(now - (run.get("started") or rm)),
                          "stale": (now - rm) > RUN_FRESH_S,
                          "distro": str(run.get("distro") or "")}
        out.append(row)
    return out


def _take(n, who, what):
    d = board_dir()
    os.makedirs(d, exist_ok=True)
    rec = {"slot": n, "who": who, "what": what, "distro": "windows",
           "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
           "taken": int(time.time())}
    try:
        with open(os.path.join(d, "slot-%d.lock" % n), "x", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        return True
    except OSError:
        return False


def release_claimed():
    """Give back the rig claim_for_ticket() took - only ours, only once."""
    while _claimed:
        n = _claimed.pop()
        path = os.path.join(board_dir(), "slot-%d.lock" % n)
        rec, _ = _read(path)
        if rec and rec.get("who") == label():
            try:
                os.remove(path)
            except OSError:
                pass


def claim_for_ticket():
    """An app launched for a triage ticket takes a rig of its own.

    The triage app launches this app with PAD_TICKET=PAD-n and no PAD_SLOT, one
    per ticket, and all of them used to drive rig 0 - so a Stop in one ticket's
    window killed another ticket's run. Here the first free rig >= 1 is
    claimed on the board (atomic create, the same O_EXCL riglock.sh uses),
    PAD_SLOT is set for every rig command this process makes, and the claim
    is given back when the app exits. Returns the rig, or 0 when there is no
    ticket, a rig was already chosen, or every rig is held (rig 0 then, as
    before - and the board says who holds the rest).
    """
    if not os.environ.get("PAD_TICKET") or os.environ.get("PAD_SLOT"):
        return slot()
    for n in range(1, SLOTS_MAX + 1):
        if _take(n, label(), "app"):
            os.environ["PAD_SLOT"] = str(n)
            _claimed.append(n)
            atexit.register(release_claimed)
            return n
    return 0
