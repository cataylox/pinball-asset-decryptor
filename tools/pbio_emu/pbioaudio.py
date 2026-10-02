#!/usr/bin/env python3
"""pbioaudio.py - the I/O-board rig's sound: what the game plays, out of the
PC's speakers at the app's Volume / Mute (PAD-322).

    pbioaudio.py --fifo $PBIO_RIG/audio.fifo --rig $PBIO_RIG [--ctl audio_ctl.json]

pinprog plays through SDL 1.2 + SDL_mixer, and that SDL speaks ALSA only -
the machine's own libraries, in its chroot, with no PulseAudio client.  So
run_game.sh gives the chroot an ALSA default that converts everything to
48 kHz 16-bit stereo and writes it, raw, into a FIFO (ALSA's own ``file``
plugin over its ``null`` device: ``asound_conf``), and this reads the FIFO
on the host and plays it through WSLg's PulseAudio (libpulse-simple, by
ctypes: PAD-Runtime has no pactl/pacat).

The FIFO is the game's clock: SDL writes as fast as the FIFO takes it, and
this takes it as fast as the speakers play it (a blocking pa_simple_write).
The pipe is shrunk to one page so the game's sound is not late.

Volume / Mute: the app's control file (``--ctl``, jjpvol.read_ctl), read
twice a second, applied by scaling the samples (linear gain, as the Stern
relays do; Mute writes silence) - so a muted start is silent from its first
sample, and nothing else on the machine is touched.  Without ``--ctl`` the
level is 100 %.

Never stalls the game: if PulseAudio is absent or fails, the FIFO is still
drained at the real-time rate (the sound is dropped) and PulseAudio is
retried every few seconds.  The FIFO is held open read+write, so the game
never sees a broken pipe while this runs; it ends when the game does.

Log lines (stdout, run_game.sh: $PBIO_RIG/pbioaudio.log): ``level N%[,
MUTED]`` on every change, ``pulse: ...`` on connect / failure, and every 10 s
``in peak P rms R  out ...`` - the proof sound is flowing, even muted.
"""
import argparse
import array
import ctypes
import errno
import math
import os
import select
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "jjp_emu"))
from jjpvol import read_ctl  # noqa: E402

RATE, CHANNELS, WIDTH = 48000, 2, 2
FRAME = CHANNELS * WIDTH
BYTES_PER_S = RATE * FRAME
CHUNK = 960 * FRAME                 # 20 ms
F_SETPIPE_SZ = 1031
PA_STREAM_PLAYBACK, PA_SAMPLE_S16LE = 1, 3


def asound_conf(fifo):
    """The chroot's /etc/asound.conf: the default device converts to the
    relay's format and writes it into *fifo* (a path inside the chroot)."""
    return ("# PAD-322: the game's sound to the PC (tools/pbio_emu/pbioaudio.py)\n"
            "pcm.!default {\n"
            "    type plug\n"
            "    slave { pcm \"padfifo\" format S16_LE rate %d channels %d }\n"
            "}\n"
            "pcm.padfifo {\n"
            "    type file\n"
            "    slave.pcm \"null\"\n"
            "    file \"%s\"\n"
            "    format \"raw\"\n"
            "}\n"
            "ctl.!default { type hw card 0 }\n" % (RATE, CHANNELS, fifo))


def scale(data, gain, muted):
    """16-bit little-endian samples at *gain* (0..1); silence when muted."""
    if muted or gain <= 0.0:
        return bytes(len(data))
    if gain >= 0.999:
        return data
    a = array.array("h")
    a.frombytes(data[:len(data) - len(data) % 2])
    if sys.byteorder != "little":
        a.byteswap()
    g = int(gain * 32768)
    a = array.array("h", [(s * g) >> 15 for s in a])
    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()


def levels(data):
    """(peak, rms) of 16-bit samples, 0..32768."""
    a = array.array("h")
    a.frombytes(data[:len(data) - len(data) % 2])
    if sys.byteorder != "little":
        a.byteswap()
    if not a:
        return 0, 0
    return max(abs(min(a)), max(a)), int(math.sqrt(sum(s * s for s in a[::16]) / len(a[::16])))


class SampleSpec(ctypes.Structure):
    _fields_ = [("format", ctypes.c_int), ("rate", ctypes.c_uint32),
                ("channels", ctypes.c_uint8)]


class BufferAttr(ctypes.Structure):
    _fields_ = [("maxlength", ctypes.c_uint32), ("tlength", ctypes.c_uint32),
                ("prebuf", ctypes.c_uint32), ("minreq", ctypes.c_uint32),
                ("fragsize", ctypes.c_uint32)]


class Pulse:
    """One playback stream through libpulse-simple."""

    def __init__(self, server, name):
        lib = self.lib = ctypes.CDLL("libpulse-simple.so.0")
        lib.pa_simple_new.restype = ctypes.c_void_p
        lib.pa_simple_new.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
                                      ctypes.c_char_p, ctypes.c_char_p,
                                      ctypes.POINTER(SampleSpec), ctypes.c_void_p,
                                      ctypes.POINTER(BufferAttr),
                                      ctypes.POINTER(ctypes.c_int)]
        lib.pa_simple_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_int)]
        lib.pa_simple_free.argtypes = [ctypes.c_void_p]
        spec = SampleSpec(PA_SAMPLE_S16LE, RATE, CHANNELS)
        # ~60 ms in the server: low enough for a flipper's click, high
        # enough that WSLg's RDP audio does not starve
        tl = BYTES_PER_S * 60 // 1000
        attr = BufferAttr(0xFFFFFFFF, tl, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
        err = ctypes.c_int(0)
        self.s = lib.pa_simple_new(server.encode() if server else None, name.encode(),
                                   PA_STREAM_PLAYBACK, None, b"game", ctypes.byref(spec),
                                   None, ctypes.byref(attr), ctypes.byref(err))
        if not self.s:
            raise OSError("pa_simple_new failed (%d)" % err.value)

    def write(self, data):
        err = ctypes.c_int(0)
        if self.lib.pa_simple_write(self.s, data, len(data), ctypes.byref(err)) < 0:
            raise OSError("pa_simple_write failed (%d)" % err.value)

    def close(self):
        if self.s:
            self.lib.pa_simple_free(self.s)
            self.s = None


def say(msg):
    print("%s %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def game_alive(rig):
    try:
        with open(os.path.join(rig, "game.pid")) as f:
            pid = f.read().strip()
    except OSError:
        return None                       # not started yet
    return bool(pid) and os.path.isdir("/proc/%s" % pid)


def open_fifo(path):
    if not os.path.exists(path):
        os.mkfifo(path, 0o666)
    if not stat.S_ISFIFO(os.stat(path).st_mode):
        raise OSError("%s is not a FIFO" % path)
    os.chmod(path, 0o666)
    fd = os.open(path, os.O_RDWR)         # never a broken pipe for the game
    import fcntl                          # Linux only (the tests import this on Windows)
    try:
        fcntl.fcntl(fd, F_SETPIPE_SZ, 4096)
    except OSError:
        pass
    return fd


def main(argv=None):
    ap = argparse.ArgumentParser(description="the PB I/O-board rig's sound")
    ap.add_argument("--fifo", required=True)
    ap.add_argument("--rig", required=True, help="the slot's folder ($PBIO_RIG)")
    ap.add_argument("--ctl", default="", help="the app's audio_ctl.json, as a WSL path")
    ap.add_argument("--pulse", default="unix:/mnt/wslg/PulseServer")
    ap.add_argument("--name", default="Pinball Brothers")
    ap.add_argument("--conf", default="", help="write the chroot's asound.conf here and exit")
    args = ap.parse_args(argv)
    if args.conf:
        with open(args.conf, "w") as f:
            f.write(asound_conf(args.fifo))
        return 0

    fd = open_fifo(args.fifo)
    say("fifo %s (%d Hz, %d ch, s16le)" % (args.fifo, RATE, CHANNELS))
    want, seen_mtime, said = (1.0, False), object(), None
    pulse, retry_at = None, 0.0
    t_check = 0.0
    stat_t, peak, rms_max, nbytes, written = time.monotonic(), 0, 0, 0, 0
    started = time.monotonic()
    clock = time.monotonic()               # the drain-only pace
    buf = b""
    while True:
        now = time.monotonic()
        if now >= t_check:
            t_check = now + 0.5
            alive = game_alive(args.rig)
            if alive is False or (alive is None and now - started > 180):
                say("the game is gone - done")
                break
            if args.ctl:
                try:
                    mtime = os.stat(args.ctl).st_mtime_ns
                except OSError:
                    mtime = None
                if mtime != seen_mtime:
                    seen_mtime = mtime
                    got = read_ctl(args.ctl)
                    if got is not None:
                        want = got
            if want != said:
                said = want
                say("level %d%%%s" % (round(100 * want[0]), ", MUTED" if want[1] else ""))
        try:
            if not select.select([fd], [], [], 0.5)[0]:
                continue
            data = os.read(fd, 65536)
        except OSError as e:
            if e.errno == errno.EINTR:
                continue
            raise
        buf += data
        if len(buf) < CHUNK and pulse is not None:
            continue
        n = len(buf) - len(buf) % FRAME
        if not n:
            continue
        data, buf = buf[:n], buf[n:]
        p, r = levels(data)
        peak, rms_max, nbytes = max(peak, p), max(rms_max, r), nbytes + n
        out = scale(data, *want)
        if pulse is None and now >= retry_at:
            try:
                pulse = Pulse(args.pulse, args.name)
                say("pulse: playing on %s" % args.pulse)
            except OSError as e:
                say("pulse: %s - the sound is dropped, retrying" % e)
                retry_at = now + 5
        if pulse is not None:
            try:
                pulse.write(out)
                written += n
            except OSError as e:
                say("pulse: %s - the sound is dropped, retrying" % e)
                pulse.close()
                pulse, retry_at = None, now + 5
        if pulse is None:
            # drain at the speakers' pace, so the game's clock holds
            clock = max(clock, now - 0.1) + n / float(BYTES_PER_S)
            if clock > now:
                time.sleep(clock - now)
        if now - stat_t >= 10:
            say("in peak %d rms %d  %.0f%% of real time  out %s" % (
                peak, rms_max, 100.0 * nbytes / BYTES_PER_S / (now - stat_t),
                "pulse" if written else "dropped"))
            stat_t, peak, rms_max, nbytes, written = now, 0, 0, 0, 0
    if pulse is not None:
        pulse.close()
    os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
