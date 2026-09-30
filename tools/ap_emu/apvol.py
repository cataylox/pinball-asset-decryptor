#!/usr/bin/env python3
"""apvol.py - hold this slot's American Pinball sound at the app's Volume /
Mute, live.

    apvol.py --ctl /mnt/c/.../audio_ctl.json --rig /var/tmp/pad_ap/rig0 \\
             --pactl /var/tmp/pad_ap/av/bin/pactl [--once]

The same job tools/jjp_emu/jjpvol.py does for JJP (and whose level maths it
borrows): an AP game speaks PulseAudio straight to WSLg - SDL_mixer in the
game, or GStreamer in apiav - with nothing of ours in the audio path, but
PulseAudio gives every stream its own volume and mute.  So this polls the
control file every Emulate tab writes and sets both on this slot's streams:
those whose `application.process.id` is the game's or apiav's (the rig's
processes carry AP_LOG=<rig>/rig.log; WSLg's server is shared with every
Linux program on the machine, so nothing else is touched).  It ends when
the game does.  Run as root (it reads the game's environment).
"""
import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "jjp_emu"))
from jjpvol import read_ctl, target_volume  # noqa: E402  (the level maths)

_HEAD = re.compile(r"^Sink Input #(\d+)")
_VOL = re.compile(r"^\s*Volume:\s*[^:\s]+:\s*(\d+)\s*/")
_MUTE = re.compile(r"^\s*Mute:\s*(yes|no)\b")
_PID = re.compile(r'^\s*application\.process\.id\s*=\s*"(\d+)"')


def parse_sink_inputs(text):
    """``pactl list sink-inputs`` -> ``[{index, volume, muted, pid}]``."""
    out, cur = [], None
    for line in (text or "").splitlines():
        m = _HEAD.match(line)
        if m:
            cur = {"index": int(m.group(1)), "volume": None, "muted": None, "pid": None}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = _VOL.match(line)
        if m and cur["volume"] is None:
            cur["volume"] = int(m.group(1))
            continue
        m = _MUTE.match(line)
        if m:
            cur["muted"] = m.group(1) == "yes"
            continue
        m = _PID.match(line)
        if m:
            cur["pid"] = int(m.group(1))
    return out


def plan(inputs, pids, volume, mute, slack=256):
    """pactl argument lists bringing this slot's streams to (volume, mute) -
    nothing for one already there, nothing ever for anybody else's."""
    cmds = []
    for s in inputs:
        if s.get("pid") not in pids:
            continue
        if s.get("volume") is None or abs(s["volume"] - volume) > slack:
            cmds.append(["set-sink-input-volume", str(s["index"]), str(volume)])
        if s.get("muted") is None or s["muted"] != mute:
            cmds.append(["set-sink-input-mute", str(s["index"]), "1" if mute else "0"])
    return cmds


def slot_pids(rig):
    """The game's and apiav's pids: every process whose environment names
    this rig's log."""
    want = ("AP_LOG=%s/rig.log" % rig.rstrip("/")).encode()
    pids = set()
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/environ" % d, "rb") as f:
                if want in f.read().split(b"\0"):
                    pids.add(int(d))
        except OSError:
            pass
    return pids


def game_alive(rig):
    try:
        with open(os.path.join(rig, "game.pid")) as f:
            os.kill(int(f.read().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def say(msg):
    sys.stdout.write("%s apvol: %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description="hold an AP rig slot's streams at the app's Volume / Mute")
    ap.add_argument("--ctl", required=True, help="the app's audio_ctl.json, as a WSL path")
    ap.add_argument("--rig", required=True, help="the slot's folder ($AP_RIG)")
    ap.add_argument("--pactl", required=True)
    ap.add_argument("--pulse", default="unix:/mnt/wslg/PulseServer")
    ap.add_argument("--client-conf", default="", help="PULSE_CLIENTCONFIG (no shm)")
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    env = dict(os.environ, PULSE_SERVER=args.pulse)
    if args.client_conf:
        env["PULSE_CLIENTCONFIG"] = args.client_conf
    want, seen_mtime, said = (1.0, False), object(), None
    # a first pass may come before the game is up
    for _ in range(600):
        if game_alive(args.rig):
            break
        time.sleep(0.2)
    while True:
        if not game_alive(args.rig):
            say("the game is gone - done")
            return 0
        try:
            mtime = os.stat(args.ctl).st_mtime_ns
        except OSError:
            mtime = None
        if mtime != seen_mtime:
            seen_mtime = mtime
            got = read_ctl(args.ctl)
            if got is not None:
                want = got
        volume, mute = target_volume(*want)
        if (volume, mute) != said:
            said = (volume, mute)
            say("level %d%%%s" % (round(100 * want[0]), ", MUTED" if mute else ""))
        try:
            r = subprocess.run([args.pactl, "list", "sink-inputs"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
            for cmd in plan(parse_sink_inputs(r.stdout.decode("utf-8", "replace")),
                            slot_pids(args.rig), volume, mute):
                subprocess.run([args.pactl] + cmd, env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10)
                say("pactl " + " ".join(cmd))
        except (OSError, subprocess.SubprocessError) as exc:
            say("pactl failed: %s" % exc)
        if args.once:
            return 0
        time.sleep(max(0.1, args.interval))


if __name__ == "__main__":
    sys.exit(main())
