#!/usr/bin/env python3
"""spkwarden.py - the rig's Warden: Spooky's playfield controller board, on
a pty, for Beetlejuice (Unity).

    spkwarden.py <rig dir>

Makes a pty, writes its slave path to <rig>/warden.tty (run_game.sh hands it
to the game as SPK_WARDEN; spkshim.so maps /dev/WARDEN onto it), then serves
the board until the game closes the port for good or it is killed.

The wire protocol (Warden.cs, decompiled):
  host -> board   0x3E ('>') <opcode> <args...>   ~60 opcodes: coils, LEDs,
                  switch config, steppers...  The board here parses none of
                  them fully - it scans the stream for the few it must
                  answer or act on (a '>' followed by one of those opcodes),
                  and swallows the rest.
  board -> host   0x3C ('<') 0x01 <sw>            switch went active
                  0x3C 0x00 <sw>                  switch went inactive
                  0x3C 0x98 <sw> <0|1>            reply to get_switch_state
                  0x3C 0xA8 <coil> x x x <255>    reply to get_coil_config
                                                  (the game's watchdog asks
                                                  for coil 6; 255 = still
                                                  configured, no re-send)
                  0x3C 0x96|0x97 <text> 0x00      firmware / hardware info
The board reports LOGICAL states: the host tells it which switches are
inverted (opto troughs) and the firmware applies that.

The machine at rest: the trough full (Game.expectedBallCount = 6: TROUGH
1..6 active, TROUGH 7 and the jam opto clear), every other switch inactive.

Physics, just enough to play: the trough eject coil (51) takes a ball out
and makes the shooter lane (8) active half a second later; the auto-launch
coil (54) clears the shooter lane.  `sw.py drain` puts a ball back in the
trough.

Switch input comes from sw.py over the FIFO <rig>/input, one line each:
    <sw> on | off | pulse [ms]      (sw = number)
    drain
    dump                            (writes <rig>/switches.txt)
Everything the board does is logged to <rig>/warden.log.
"""
import os
import select
import sys
import threading
import time

TROUGH = [7, 6, 5, 4, 3, 1, 0]       # TROUGH 1..7 (Switches.TroughSwitches)
BALLS = int(os.environ.get("SPK_BALLS", "6"))
SHOOTER = 8
EJECT_COIL = 51
LAUNCH_COIL = 54
# Opcodes whose first argument is a coil number (fire / hold a coil).
COIL_OPS = {129, 132, 133, 148, 149, 166, 186, 187, 191}
OP_SWITCH_STATE = 152
OP_COIL_CONFIG = 168
OP_FIRMWARE = 150
OP_HARDWARE = 151


class Board:
    def __init__(self, rig, pty=True):
        self.rig = rig
        self.lock = threading.Lock()
        self.state = {}
        self.balls = BALLS
        self.log = open(os.path.join(rig, "warden.log"), "a", buffering=1)
        self.master = self.slave = self.slave_path = None
        if pty:
            import tty              # POSIX only; the tests run without
            self.master, slave = os.openpty()
            tty.setraw(slave)
            self.slave_path = os.ttyname(slave)
            self.slave = slave      # keep one handle open: no EIO on reopen
        self._set_trough()

    def say(self, *a):
        self.log.write("%s %s\n" % (time.strftime("%H:%M:%S"), " ".join(str(x) for x in a)))

    def _set_trough(self):
        for i, sw in enumerate(TROUGH):
            self.state[sw] = 1 if i < self.balls else 0
        self.state[2] = 0            # TROUGH JAM

    def send(self, data):
        try:
            os.write(self.master, bytes(data))
        except OSError as e:
            self.say("write failed", e)

    def set_switch(self, sw, on):
        with self.lock:
            on = 1 if on else 0
            if self.state.get(sw, 0) == on:
                return
            self.state[sw] = on
            self.send([0x3C, on, sw])
        self.say("switch", sw, "on" if on else "off")

    def later(self, secs, fn, *a):
        t = threading.Timer(secs, fn, a)
        t.daemon = True
        t.start()

    def trough_changed(self):
        for i, sw in enumerate(TROUGH):
            self.set_switch(sw, i < self.balls)

    # -- host -> board --------------------------------------------------
    def host_bytes(self, buf):
        """Scan for '>' <op> ... that need an answer or move a ball.  A
        false match inside LED data costs at most a harmless extra reply."""
        i = 0
        n = len(buf)
        while i < n - 2:
            if buf[i] != 0x3E:
                i += 1
                continue
            op, arg = buf[i + 1], buf[i + 2]
            if op == OP_SWITCH_STATE:
                with self.lock:
                    self.send([0x3C, OP_SWITCH_STATE, arg, self.state.get(arg, 0)])
            elif op == OP_COIL_CONFIG:
                self.send([0x3C, OP_COIL_CONFIG, arg, 0, 0, 0, 255])
            elif op == OP_FIRMWARE:
                self.send([0x3C, OP_FIRMWARE] + list(b"PAD rig Warden") + [0])
            elif op == OP_HARDWARE:
                self.send([0x3C, OP_HARDWARE] + list(b"WARDEN (PAD rig)") + [0])
            elif op in COIL_OPS and arg == EJECT_COIL:
                self.eject()
            elif op in COIL_OPS and arg == LAUNCH_COIL:
                self.say("launch coil")
                self.later(0.1, self.set_switch, SHOOTER, 0)
            i += 1
        # The last two bytes may start a message split across reads.
        tail = buf[max(0, n - 2):]
        return tail if 0x3E in tail else b""

    def eject(self):
        if self.balls <= 0 or self.state.get(SHOOTER):
            self.say("eject: nothing to eject" if self.balls <= 0 else "eject: shooter lane full")
            return
        self.balls -= 1
        self.say("eject: ball to the shooter lane,", self.balls, "left")
        self.trough_changed()
        self.later(0.5, self.set_switch, SHOOTER, 1)

    def drain(self):
        if self.balls >= len(TROUGH):
            return
        self.balls += 1
        self.say("drain:", self.balls, "in the trough")
        self.trough_changed()

    # -- sw.py -> board -------------------------------------------------
    def command(self, line):
        p = line.split()
        if not p:
            return
        if p[0] == "drain":
            self.drain()
        elif p[0] == "dump":
            with self.lock:
                txt = "".join("%d %d\n" % kv for kv in sorted(self.state.items()))
            with open(os.path.join(self.rig, "switches.txt"), "w") as f:
                f.write(txt)
        elif len(p) >= 2 and p[0].isdigit():
            sw = int(p[0])
            if p[1] == "on":
                self.set_switch(sw, 1)
            elif p[1] == "off":
                self.set_switch(sw, 0)
            elif p[1] == "pulse":
                ms = int(p[2]) if len(p) > 2 else 200
                self.set_switch(sw, 1)
                self.later(ms / 1000.0, self.set_switch, sw, 0)
        else:
            self.say("bad command", line)

    def fifo_loop(self, path):
        while True:
            with open(path) as f:           # blocks until a writer opens it
                for line in f:
                    try:
                        self.command(line.strip())
                    except Exception as e:  # never let a typo stop the board
                        self.say("command failed", line.strip(), e)

    def serve(self):
        pend = b""
        seen = False
        while True:
            r, _, _ = select.select([self.master], [], [], 1.0)
            if not r:
                continue
            try:
                data = os.read(self.master, 4096)
            except OSError:
                # EIO: nobody holds the slave but us - the game closed it
                # (or has not opened it yet).  Keep serving: it reopens.
                time.sleep(0.2)
                continue
            if data and not seen:
                seen = True
                self.say("game connected")
            pend = self.host_bytes(pend + data)


def main():
    rig = sys.argv[1]
    b = Board(rig)
    with open(os.path.join(rig, "warden.tty.tmp"), "w") as f:
        f.write(b.slave_path + "\n")
    os.rename(os.path.join(rig, "warden.tty.tmp"), os.path.join(rig, "warden.tty"))
    b.say("board up on", b.slave_path, "balls", b.balls)
    fifo = os.path.join(rig, "input")
    if not os.path.exists(fifo):
        os.mkfifo(fifo)
    threading.Thread(target=b.fifo_loop, args=(fifo,), daemon=True).start()
    b.serve()


if __name__ == "__main__":
    main()
