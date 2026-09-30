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
coil (54) clears the shooter lane.  `drain` puts a ball back in the
trough.

Switch input comes over the control socket <rig>/ctl.sock, one line per
request, one JSON line per reply - the requests tools/ap_emu's game answers,
so the virtual playfield (spkpf.py, on tools/ap_emu/appf.py and the Stern
window's page) drives this board exactly as it drives an AP game:
    state               {"up": true, "switches": {n: 1 for each one made},
                         "balls": {"trough", "shooter", "in_play"},
                         "lights": {}, "paused": bool, "connected": bool}
    sw <n> <0|1>        hold / release a switch
    tap <n> [ms]        press and release (150 ms)
    rip <n> <0|1>       flip a switch while held (a spinner spinning)
    plunge              the Launch button: the game fires the ball into play
    drain               a ball in play (or in the shooter lane) to the trough
    reset               every ball back in the trough
    pause <0|1>         freeze / thaw the game (SIGSTOP / SIGCONT)
ctl.sh / spkctl.py and sw.py are its clients.
Everything the board does is logged to <rig>/warden.log.
"""
import json
import os
import queue
import select
import signal
import socket
import sys
import threading
import time

TROUGH = [7, 6, 5, 4, 3, 1, 0]       # TROUGH 1..7 (Switches.TroughSwitches)
BALLS = int(os.environ.get("SPK_BALLS", "6"))
SHOOTER = 8
LAUNCH_BUTTON = 85
#: The shortest press the board passes on (see set_switch).
MIN_PRESS_S = 0.12
# Linux's numbers (the tests import this on Windows, which has neither)
SIGSTOP = getattr(signal, "SIGSTOP", 19)
SIGCONT = getattr(signal, "SIGCONT", 18)
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
        self.connected = False
        self.paused = False
        self.ripping = set()
        self.on_at = {}
        self.outq = queue.Queue()
        self._set_trough()

    def say(self, *a):
        self.log.write("%s %s\n" % (time.strftime("%H:%M:%S"), " ".join(str(x) for x in a)))

    def _set_trough(self):
        for i, sw in enumerate(TROUGH):
            self.state[sw] = 1 if i < self.balls else 0
        self.state[2] = 0            # TROUGH JAM

    def send(self, data):
        """Queue a message for the game.  Only the writer thread writes: the
        game reads its replies once a frame, and a write that waits for it
        must never hold up reading the game's own stream (a late read makes
        the game's writes time out, and ten of those reset its board link)."""
        self.outq.put(bytes(data))

    def writer(self):
        while True:
            data = self.outq.get()
            try:
                os.write(self.master, data)
            except OSError as e:
                self.say("write failed", e)

    def set_switch(self, sw, on, now=False):
        """A press is held at least MIN_PRESS_S unless *now*: the game
        believes a Start / menu / tilt edge only after asking the board for
        that switch again, so a click or key tap shorter than that (a
        browser's key press is 0 ms) would be dropped - a real button is
        closed for tens of milliseconds at the least."""
        wait = 0.0
        with self.lock:
            on = 1 if on else 0
            if self.state.get(sw, 0) == on:
                return
            if not on and not now:
                wait = MIN_PRESS_S - (time.monotonic() - self.on_at.get(sw, 0.0))
        if wait > 0:
            self.later(wait, self.set_switch, sw, 0, True)
            return
        with self.lock:
            if self.state.get(sw, 0) == on:
                return
            self.state[sw] = on
            if on:
                self.on_at[sw] = time.monotonic()
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
        false match inside LED data costs at most a harmless extra reply.

        bytes.find does the scanning, not a Python loop over every byte: the
        game streams LED frames flat out (a pty has no baud rate), gives each
        write only 20 ms, and after ten late ones resets its board link and
        stops reacting to switches (PAD-266)."""
        n = len(buf)
        i = buf.find(b">")
        while 0 <= i < n - 2:
            op, arg = buf[i + 1], buf[i + 2]
            i = buf.find(b">", i + 1)
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

    def plunge(self):
        """Beetlejuice has no manual plunger: the Launch button makes the
        game fire its auto-launch coil, which (host_bytes) moves the ball
        into play.  A ball that only LEAVES the lane, without that coil, is
        one the game never saw launched - it sits in the skill shot and
        ignores the playfield.  So press Launch; if the game does not fire
        the coil (a tilt, a mode holding the ball), let the ball go anyway."""
        self.set_switch(LAUNCH_BUTTON, 1)
        self.later(0.2, self.set_switch, LAUNCH_BUTTON, 0)
        self.later(1.5, self.set_switch, SHOOTER, 0)

    def drain(self):
        if self.balls >= len(TROUGH):
            return
        self.balls += 1
        self.say("drain:", self.balls, "in the trough")
        self.trough_changed()

    # -- control socket -----------------------------------------------
    def balls_state(self):
        shooter = 1 if self.state.get(SHOOTER) else 0
        return {"trough": self.balls, "shooter": shooter,
                "in_play": max(0, BALLS - self.balls - shooter)}

    def command(self, line):
        """One control request -> its one-line JSON reply."""
        p = line.split()
        if not p:
            return json.dumps({"err": "empty"})
        if p[0] == "state":
            with self.lock:
                sw = {str(k): 1 for k, v in sorted(self.state.items()) if v}
            return json.dumps({"up": True, "switches": sw,
                               "balls": self.balls_state(), "lights": {},
                               "paused": self.paused, "connected": self.connected})
        if p[0] == "drain":
            b = self.balls_state()
            if b["in_play"] <= 0 and not b["shooter"]:
                return json.dumps({"err": "no ball in play"})
            if b["in_play"] <= 0:
                self.set_switch(SHOOTER, 0)
            self.drain()
        elif p[0] == "plunge":
            if not self.state.get(SHOOTER):
                return json.dumps({"err": "no ball in the shooter lane"})
            self.plunge()
        elif p[0] == "reset":
            self.set_switch(SHOOTER, 0)
            self.balls = BALLS
            self.trough_changed()
        elif p[0] == "pause":
            self.set_pause(len(p) > 1 and p[1] == "1")
            return json.dumps({"paused": self.paused})
        elif p[0] in ("sw", "tap", "rip") and len(p) >= 2 and p[1].isdigit():
            n = int(p[1])
            on = len(p) < 3 or p[2] not in ("0", "off")
            if p[0] == "sw":
                self.set_switch(n, on)
            elif p[0] == "rip":
                self.rip(n, on)
            else:
                ms = int(p[2]) if len(p) > 2 and p[2].isdigit() else 150
                self.set_switch(n, 1)
                self.later(ms / 1000.0, self.set_switch, n, 0)
        else:
            return json.dumps({"err": "unknown request: " + line.strip()})
        return json.dumps({"ok": True})

    def rip(self, n, on):
        """Right-held on the playfield: the switch flips every 60 ms until
        released, as a spinning spinner does."""
        if not on:
            self.ripping.discard(n)
            return
        if n in self.ripping:
            return
        self.ripping.add(n)

        def spin():
            state = 0
            while n in self.ripping:
                state ^= 1
                self.set_switch(n, state, now=True)
                time.sleep(0.06)
            self.set_switch(n, 0, now=True)
        threading.Thread(target=spin, daemon=True).start()

    def set_pause(self, on):
        """Freeze the game itself: its pid is the rig's game.pid."""
        try:
            with open(os.path.join(self.rig, "game.pid")) as f:
                pid = int(f.read().strip())
            os.kill(pid, SIGSTOP if on else SIGCONT)
            self.paused = on
            self.say("paused" if on else "resumed")
        except (OSError, ValueError) as e:
            self.say("pause failed", e)

    def client(self, conn):
        buf = b""
        with conn:
            while True:
                try:
                    data = conn.recv(4096)
                except OSError:
                    return
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        reply = self.command(line.decode("utf-8", "replace"))
                    except Exception as e:      # never let a typo stop the board
                        reply = "err %s" % e
                    try:
                        conn.sendall((reply + "\n").encode())
                    except OSError:
                        return

    def ctl_loop(self, path):
        try:
            os.unlink(path)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(path)
        os.chmod(path, 0o666)       # the app's switch window may run as root
        srv.listen(8)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self.client, args=(conn,), daemon=True).start()

    def serve(self):
        pend = b""
        seen = False
        while True:
            r, _, _ = select.select([self.master], [], [], 1.0)
            if not r:
                continue
            try:
                data = os.read(self.master, 1 << 16)
            except OSError:
                # EIO: nobody holds the slave but us - the game closed it
                # (or has not opened it yet).  Keep serving: it reopens.
                time.sleep(0.2)
                continue
            if data and not seen:
                seen = self.connected = True
                self.say("game connected")
            pend = self.host_bytes(pend + data)


def main():
    rig = sys.argv[1]
    b = Board(rig)
    with open(os.path.join(rig, "warden.tty.tmp"), "w") as f:
        f.write(b.slave_path + "\n")
    os.rename(os.path.join(rig, "warden.tty.tmp"), os.path.join(rig, "warden.tty"))
    b.say("board up on", b.slave_path, "balls", b.balls)
    threading.Thread(target=b.writer, daemon=True).start()
    threading.Thread(target=b.ctl_loop, args=(os.path.join(rig, "ctl.sock"),),
                     daemon=True).start()
    b.serve()


if __name__ == "__main__":
    main()
