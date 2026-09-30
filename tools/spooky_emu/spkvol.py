#!/usr/bin/env python3
"""spkvol.py - hold this slot's Beetlejuice sound at the app's Volume / Mute,
live - what tools/ap_emu/apvol.py does for an AP game, with the same level
maths (jjpvol.target_volume) and the same choice of streams (apvol.plan: the
game's own, found by pid; WSLg's PulseAudio is shared with every Linux
program on the machine, so nothing else is touched).

    spkvol.py --ctl /mnt/c/.../audio_ctl.json --rig /var/tmp/pad_spooky/rig0

apvol drives `pactl`, which AP's downloaded environment carries and
PAD-Runtime does not; the game's own libpulse (PAD-Runtime's, Unity plays
through it) does the same job here through ctypes.  It ends when the game
does.  Run as root (it reads the game's environment).
"""
import argparse
import ctypes
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ap_emu"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "jjp_emu"))
from apvol import plan, game_alive, say  # noqa: E402
from jjpvol import read_ctl, target_volume  # noqa: E402

PA_CHANNELS_MAX = 32
PA_CONTEXT_READY, PA_CONTEXT_FAILED, PA_CONTEXT_TERMINATED = 4, 5, 6
PA_OPERATION_RUNNING = 0


class SampleSpec(ctypes.Structure):
    _fields_ = [("format", ctypes.c_int), ("rate", ctypes.c_uint32),
                ("channels", ctypes.c_uint8)]


class ChannelMap(ctypes.Structure):
    _fields_ = [("channels", ctypes.c_uint8), ("map", ctypes.c_int * PA_CHANNELS_MAX)]


class CVolume(ctypes.Structure):
    _fields_ = [("channels", ctypes.c_uint8), ("values", ctypes.c_uint32 * PA_CHANNELS_MAX)]


class SinkInputInfo(ctypes.Structure):
    """pa_sink_input_info (pulse/introspect.h; stable since PulseAudio 1.0)."""
    _fields_ = [("index", ctypes.c_uint32), ("name", ctypes.c_char_p),
                ("owner_module", ctypes.c_uint32), ("client", ctypes.c_uint32),
                ("sink", ctypes.c_uint32), ("sample_spec", SampleSpec),
                ("channel_map", ChannelMap), ("volume", CVolume),
                ("buffer_usec", ctypes.c_uint64), ("sink_usec", ctypes.c_uint64),
                ("resample_method", ctypes.c_char_p), ("driver", ctypes.c_char_p),
                ("mute", ctypes.c_int), ("proplist", ctypes.c_void_p),
                ("corked", ctypes.c_int), ("has_volume", ctypes.c_int),
                ("volume_writable", ctypes.c_int), ("format", ctypes.c_void_p)]


INFO_CB = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(SinkInputInfo),
                           ctypes.c_int, ctypes.c_void_p)


class Pulse:
    """Just enough of libpulse: list the sink inputs, set one's volume/mute."""

    def __init__(self, server):
        pa = self.pa = ctypes.CDLL("libpulse.so.0")
        for fn, res, args in (
                ("pa_mainloop_new", ctypes.c_void_p, []),
                ("pa_mainloop_get_api", ctypes.c_void_p, [ctypes.c_void_p]),
                ("pa_mainloop_iterate", ctypes.c_int, [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]),
                ("pa_mainloop_free", None, [ctypes.c_void_p]),
                ("pa_context_new", ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_char_p]),
                ("pa_context_connect", ctypes.c_int, [ctypes.c_void_p, ctypes.c_char_p,
                                                      ctypes.c_int, ctypes.c_void_p]),
                ("pa_context_get_state", ctypes.c_int, [ctypes.c_void_p]),
                ("pa_context_disconnect", None, [ctypes.c_void_p]),
                ("pa_context_unref", None, [ctypes.c_void_p]),
                ("pa_context_get_sink_input_info_list", ctypes.c_void_p,
                 [ctypes.c_void_p, INFO_CB, ctypes.c_void_p]),
                ("pa_context_set_sink_input_volume", ctypes.c_void_p,
                 [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(CVolume),
                  ctypes.c_void_p, ctypes.c_void_p]),
                ("pa_context_set_sink_input_mute", ctypes.c_void_p,
                 [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p,
                  ctypes.c_void_p]),
                ("pa_operation_get_state", ctypes.c_int, [ctypes.c_void_p]),
                ("pa_operation_unref", None, [ctypes.c_void_p]),
                ("pa_proplist_gets", ctypes.c_char_p, [ctypes.c_void_p, ctypes.c_char_p]),
                ("pa_cvolume_set", ctypes.c_void_p, [ctypes.POINTER(CVolume),
                                                     ctypes.c_uint, ctypes.c_uint32])):
            f = getattr(pa, fn)
            f.restype = res
            f.argtypes = args
        self.ml = pa.pa_mainloop_new()
        self.ctx = pa.pa_context_new(pa.pa_mainloop_get_api(self.ml), b"pad-spkvol")
        if pa.pa_context_connect(self.ctx, server.encode(), 0, None) < 0:
            raise OSError("cannot reach PulseAudio at %s" % server)
        while True:
            st = pa.pa_context_get_state(self.ctx)
            if st == PA_CONTEXT_READY:
                break
            if st in (PA_CONTEXT_FAILED, PA_CONTEXT_TERMINATED):
                raise OSError("PulseAudio refused the connection")
            pa.pa_mainloop_iterate(self.ml, 1, None)

    def _wait(self, op):
        if not op:
            return
        while self.pa.pa_operation_get_state(op) == PA_OPERATION_RUNNING:
            self.pa.pa_mainloop_iterate(self.ml, 1, None)
        self.pa.pa_operation_unref(op)

    def sink_inputs(self):
        """[{index, volume, muted, pid, channels}] - apvol's shape."""
        out = []

        def cb(_ctx, info, eol, _ud):
            if eol or not info:
                return
            i = info.contents
            pid = self.pa.pa_proplist_gets(i.proplist, b"application.process.id")
            out.append({"index": i.index, "volume": i.volume.values[0] if i.volume.channels else None,
                        "muted": bool(i.mute), "pid": int(pid) if pid and pid.isdigit() else None,
                        "channels": i.volume.channels or i.sample_spec.channels or 2})
        keep = INFO_CB(cb)
        self._wait(self.pa.pa_context_get_sink_input_info_list(self.ctx, keep, None))
        return out

    def set_volume(self, index, channels, volume):
        cv = CVolume()
        self.pa.pa_cvolume_set(ctypes.byref(cv), channels, volume)
        self._wait(self.pa.pa_context_set_sink_input_volume(self.ctx, index, ctypes.byref(cv),
                                                            None, None))

    def set_mute(self, index, mute):
        self._wait(self.pa.pa_context_set_sink_input_mute(self.ctx, index, 1 if mute else 0,
                                                          None, None))

    def close(self):
        self.pa.pa_context_disconnect(self.ctx)
        self.pa.pa_context_unref(self.ctx)
        self.pa.pa_mainloop_free(self.ml)


def slot_pids(rig):
    """The game's pids: every process whose environment carries this rig's
    SPK_MARK (spkpath.sh's spk_slot_pids, in Python)."""
    want = ("SPK_MARK=%s" % rig.rstrip("/")).encode()
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="hold a Spooky rig slot's sound at the app's Volume / Mute")
    ap.add_argument("--ctl", required=True, help="the app's audio_ctl.json, as a WSL path")
    ap.add_argument("--rig", required=True, help="the slot's folder ($SPK_RIG)")
    ap.add_argument("--pulse", default="unix:/mnt/wslg/PulseServer")
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    want, seen_mtime, said = (1.0, False), object(), None
    for _ in range(600):                      # a first pass may come before the game
        if game_alive(args.rig):
            break
        time.sleep(0.2)
    pulse = None
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
            if pulse is None:
                pulse = Pulse(args.pulse)
            inputs = pulse.sink_inputs()
            chans = {s["index"]: s["channels"] for s in inputs}
            for cmd in plan(inputs, slot_pids(args.rig), volume, mute):
                idx = int(cmd[1])
                if cmd[0] == "set-sink-input-volume":
                    pulse.set_volume(idx, chans.get(idx, 2), int(cmd[2]))
                else:
                    pulse.set_mute(idx, cmd[2] == "1")
                say(" ".join(cmd))
        except OSError as exc:
            say("pulse: %s" % exc)
            if pulse is not None:
                pulse.close()
            pulse = None
        if args.once:
            return 0
        time.sleep(max(0.1, args.interval))


if __name__ == "__main__":
    sys.exit(main())
