#!/usr/bin/env python3
"""pfball.py - where Pulp Fiction's balls are, from the coils the game fires.

Counting, not physics (the way pbfast.py and jjpball.py do it).  Watches the
game's output packet in io.bin (pfshim.c copies every one there) and moves
balls by flipping switches through sw.py's IO:

  trough      Trough 1..4 are optos (sw.py OPTOS); balls sit from Trough 1,
              the eject end.  The trough coil takes one out, and ~0.4 s
              later it sits in the shooter lane (Shooter).
  shooter     the auto-plunger (a ball save, the game's re-serve) or
              `sw.py launch` (the player's plunger) sends the lane's ball
              past Shooter Upper into play.
  drains      `sw.py drain` puts a ball back at the top of the trough.

The game drives its coils with PWM, so a coil counts as fired when its bit
shows up after at least QUIET seconds without it.
Runs until killed; logs one line per ball move to stdout.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sw  # noqa: E402


def coil(n):
    """The game's coil n in its 41-byte packet: (byte, bit), byte 1-based.
    Coils 0-7 are byte 20, 8-15 byte 21, 16-23 byte 22 (the trough, coil 11,
    was seen at byte 21 bit 3)."""
    return (20 + n // 8, n % 8)


TROUGH_COIL = coil(11)         # gameTroughReleaseProc fires coil 11
SHOOTER_COIL = coil(10)        # gameShootBallProc: the auto-plunger, coil 10
QUIET = 0.15                   # a coil is "fired" after this long unseen
LANE_DELAY = 0.4               # trough eject -> ball resting in the lane


def bit(io, c):
    byte, b = c
    return bool(io.m[sw.OFF_OUT + byte - 1] & (1 << b))


def trough_count(io):
    return sum(1 for n in sw.TROUGH if io.closed(n))


def set_trough(io, count):
    for i, n in enumerate(sw.TROUGH):
        io.set(n, i < count)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Balls:
    """The ball model; step() once per millisecond or so."""

    def __init__(self, io, say=log):
        self.io = io
        self.say = say
        self.last_seen = {}
        self.pending = []                           # (when, action)

    def step(self, now):
        io = self.io
        for c in (TROUGH_COIL, SHOOTER_COIL):
            if not bit(io, c):
                continue
            fired = now - self.last_seen.get(c, -1e9) > QUIET
            self.last_seen[c] = now
            if not fired:
                continue
            if c == TROUGH_COIL:
                n = trough_count(io)
                if n and not io.closed(sw.SHOOTER):
                    set_trough(io, n - 1)
                    self.pending.append((now + LANE_DELAY, "lane"))
                    self.say("trough eject: %d left" % (n - 1))
            elif io.closed(sw.SHOOTER):
                io.set(sw.SHOOTER, False)
                self.pending.append((now + 0.05, "upper"))
                self.say("auto-plunge")
        for item in [p for p in self.pending if p[0] <= now]:
            self.pending.remove(item)
            if item[1] == "lane":
                io.set(sw.SHOOTER, True)
                self.say("ball in the shooter lane")
            elif item[1] == "upper":
                io.set(sw.SHOOTER_UPPER, True)
                self.pending.append((now + 0.06, "upper_off"))
            elif item[1] == "upper_off":
                io.set(sw.SHOOTER_UPPER, False)
                self.say("ball in play")


def main():
    balls = Balls(sw.IO())
    while True:
        balls.step(time.monotonic())
        time.sleep(0.001)


if __name__ == "__main__":
    main()
