#!/usr/bin/env python3
"""pbfast.py - emulated FAST Neuron, I/O nodes and expansion boards for
Pinball Brothers' Predator.

pinprog (the game's rules program, FreeWPC-derived C, platform/pb/fast.c)
opens /dev/ttyACM0 and /dev/ttyACM1 - the Neuron's two USB CDC ports - and
decides which is which by the ID reply.  This daemon makes a pty for each,
links them into <dir>/dev (pbshim.so maps the game's opens there) and
answers the way fast.c reads, which is the only reader that matters:

  NET (ttyACM0)  ID: CH: DL: NN: SA: get replies; WD: SL: TL: do NOT - fast.c
                 copies any unsolicited line into whichever reply it is
                 waiting on, so a stray "WD:P" would answer an SA: or NN:.
                 Switch events: "-L:xx" = active, "/L:xx" = inactive (hex).
  EXP (ttyACM1)  "EA:<addr>" selects a board (no reply); ID@<addr>: / ID:,
                 BR: EM: ER: and the three-field MF: are waited for; RS:
                 (one LED) and the rest are fire-and-forget.

SA: is "SA:<cc>,<hex bytes>": fast.c reads cc-1 bytes, bit n of byte b is
switch b*8+n, 1 = closed.  An opto (the game's mach_opto_mask) is closed when
NOT blocked, so SA: inverts its logical state; events do not (the board
applies SL: mode 02 before it reports one).

Nothing here is guessed from FAST's documentation: each reply is the shape
fast.c's parser reads (disassembly with its own DWARF line info; see
docs/plans/pb_emulator.md).

Control: a unix socket at <dir>/ctl.sock, one command per line:
  sw <n> <0|1>      set a switch (logical: 1 = active)
  tap <n> [ms]      press, then release after ms (default 150)
  plunge            the ball in the shooter lane leaves it (into play)
  drain             one ball in play drains into the trough
  rip <n> <0|1>     flip a switch every RIP_S while on (a spinner spinning)
  reset             every ball back in the trough (nothing in play or the lane)
  pause <0|1>       freeze / thaw the game (SIGSTOP / SIGCONT of this rig's
                    pinprog and vidprog, found by their PB_MARK); JSON reply
  state             JSON: switches, balls, driver pulses, board status - and
                    the keys the virtual playfield (tools/ap_emu/appf.py via
                    pbpf.py) reads: up, paused, lights ("<board>:<index>" ->
                    [r, g, b], the lit ones)
  leds              JSON: every LED the game has set, "<board>:<index>" -> rrggbb
  quit
"""
import argparse
import heapq
import json
import os
import select
import signal
import socket
import time

NET, EXP = "net", "exp"
SWITCH_BYTES = 15               # SA: reply covers switches 0..119
RIP_S = 0.04                    # a ripped switch flips this often
# The shortest press `sw` lets through: pinprog's debounce drops a switch
# that is back within a scan or two ("SW 5 COIN 2 unstable"), and a click or
# a key tap in the switch window can be 1-2 ms from press to release.
MIN_PRESS_S = 0.1


class Port:
    def __init__(self, name, role):
        import tty      # Linux only; the tests load this module on Windows
        self.name, self.role = name, role
        self.master, slave = os.openpty()
        tty.setraw(slave)
        # Keep our own slave fd open so the master never sees EIO while the
        # game closes and reopens the port (it reconnects after errors).
        self.slave = slave
        self.pts = os.ttyname(slave)
        os.chmod(self.pts, 0o666)
        os.set_blocking(self.master, False)
        self.rx = b""
        self.tx = b""


class Emulator:
    def __init__(self, root, profile, log):
        self.root = root
        self.profile = profile
        self.logf = log
        self.t0 = time.monotonic()
        self.ports = {}
        self.switches = {}          # logical state, 1 = active
        # Optos read the other way round on the wire (SA: and events);
        # the game's own mask, then SL: mode 02 as it configures them.
        self.opto = set(int(n) for n in profile.get("optos", []))
        self.drivers = {}           # DL: config lines by driver hex
        self.pulses = []            # recent TL: actions
        self.leds = {}              # (board, index) -> (r, g, b)
        self.exp_sel = None         # EA: address
        self.status = {"net_id": False, "configured": False, "nodes": 0,
                       "exp": [], "sa": 0, "watchdog": 0}
        self.timers = []
        self.seq = 0
        self.ripping = set()        # switches flipping (rip)
        self.pressed = {}           # sw n -> (press count, when) for MIN_PRESS_S
        self.paused = False
        self.trace = os.environ.get("PBFAST_TRACE") == "1"   # every line in
        for n in profile.get("active_at_boot", []):
            self.switches[int(n)] = 1
        self.trough = [int(n) for n in profile.get("trough_switches", [])]
        self.shooter = profile.get("shooter_switch")
        self.in_trough = len(self.trough)
        self.in_play = 0
        for i, n in enumerate(self.trough):
            self.switches[n] = 1 if i < self.in_trough else 0

    # ---------------------------------------------------------------- setup
    def build(self):
        dev = os.path.join(self.root, "dev")
        os.makedirs(dev, exist_ok=True)
        for i, role in enumerate((NET, EXP)):
            p = Port("ttyACM%d" % i, role)
            self.ports[role] = p
            link = os.path.join(dev, p.name)
            if os.path.lexists(link):
                os.unlink(link)
            os.symlink(p.pts, link)
        self.log("ports: " + ", ".join("%s(%s)=%s" % (p.name, p.role, p.pts)
                                       for p in self.ports.values()))

    # ---------------------------------------------------------------- utils
    def log(self, msg):
        self.logf.write("%9.3f %s\n" % (time.monotonic() - self.t0, msg))
        self.logf.flush()

    def send(self, role, text):
        self.ports[role].tx += (text + "\r").encode("latin-1")

    def after(self, secs, fn, *args):
        self.seq += 1
        heapq.heappush(self.timers, (time.monotonic() + secs, self.seq, fn, args))

    # ------------------------------------------------------------- switches
    def set_switch(self, n, active, source="ctl"):
        active = 1 if active else 0
        if self.switches.get(n, 0) == active:
            return
        self.switches[n] = active
        self.log("SW %d -> %s (%s)" % (n, "active" if active else "inactive",
                                       source))
        # Events carry the LOGICAL state for every switch: the board applies
        # an opto's inversion itself (its SL: mode 02).
        self.send(NET, "%s:%02X" % ("-L" if active else "/L", n))

    def sa_reply(self):
        out = []
        for b in range(SWITCH_BYTES):
            v = 0
            for bit in range(8):
                n = b * 8 + bit
                if self.switches.get(n, 0) ^ (1 if n in self.opto else 0):
                    v |= 1 << bit
            out.append("%02X" % v)
        return "SA:%02X,%s" % (SWITCH_BYTES + 1, "".join(out))

    # ----------------------------------------------------------- ball model
    # Counting, not physics: the trough holds balls from its first switch
    # (TROUGH 1) up, the shooter lane holds at most one, everything else is
    # "in play" until the user drains it.
    def layout_trough(self):
        for i, n in enumerate(self.trough):
            self.set_switch(n, i < self.in_trough, "ball")

    def trough_eject(self):
        if self.in_trough == 0 or self.shooter is None:
            return
        if self.switches.get(self.shooter):
            return          # lane occupied: the eject bounces back
        self.in_trough -= 1
        self.layout_trough()
        self.after(0.3, self.set_switch, self.shooter, 1, "ball")

    def plunge(self):
        if self.shooter is None or not self.switches.get(self.shooter):
            return False
        self.set_switch(self.shooter, 0, "ball")
        self.in_play += 1
        return True

    def drain(self):
        if self.in_play == 0 or self.in_trough >= len(self.trough):
            return False
        self.in_play -= 1
        self.in_trough += 1
        self.layout_trough()
        return True

    def reset_balls(self):
        self.in_play = 0
        self.in_trough = len(self.trough)
        if self.shooter is not None:
            self.set_switch(self.shooter, 0, "ball")
        self.layout_trough()
        return True

    def press(self, n, on):
        """A press from outside (the switch window, sw.py): as set_switch,
        but a release that comes sooner than MIN_PRESS_S after its press
        waits out the rest, so the game's debounce sees it."""
        now = time.monotonic()
        count, since = self.pressed.get(n, (0, 0.0))
        if on:
            self.pressed[n] = (count + 1, now)
            self.set_switch(n, 1)
            return
        held = now - since
        if held < MIN_PRESS_S:
            self.after(MIN_PRESS_S - held, self._late_release, n, count)
        else:
            self.set_switch(n, 0)

    def _late_release(self, n, count):
        # pressed again meanwhile: that press's own release lets it go
        if self.pressed.get(n, (0, 0.0))[0] == count:
            self.set_switch(n, 0)

    def rip(self, n, on):
        if not on:
            self.ripping.discard(n)
            return
        if n not in self.ripping:
            self.ripping.add(n)
            self.after(RIP_S, self._rip_tick, n)

    def _rip_tick(self, n):
        if n not in self.ripping:
            self.set_switch(n, 0, "rip")
            return
        self.set_switch(n, not self.switches.get(n, 0), "rip")
        self.after(RIP_S, self._rip_tick, n)

    # ---------------------------------------------------------------- pause
    def game_pids(self):
        """This rig's pinprog and vidprog: every process whose environment
        carries PB_MARK=<this rig> and whose name is one of the programs
        (never this board, nor the rig's Xvfb)."""
        want = ("PB_MARK=%s" % self.root.rstrip("/")).encode()
        progs = set(self.profile.get("programs", ["pinprog", "vidprog"]))
        pids = []
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open("/proc/%s/comm" % d) as f:
                    if f.read().strip() not in progs:
                        continue
                with open("/proc/%s/environ" % d, "rb") as f:
                    if want in f.read().split(b"\0"):
                        pids.append(int(d))
            except OSError:
                pass
        return pids

    def set_pause(self, on):
        sig = signal.SIGSTOP if on else signal.SIGCONT
        for p in self.game_pids():
            try:
                os.kill(p, sig)
            except OSError:
                pass
        self.paused = bool(on)
        self.log("PAUSE %s" % ("on" if on else "off"))
        return self.paused

    def on_pulse(self, drv):
        if drv == self.profile.get("trough_eject_driver"):
            self.after(0.1, self.trough_eject)
        elif drv in self.profile.get("launch_drivers", []):
            self.after(0.1, self.plunge)
        # A drop-target bank reset stands its targets back up.
        for sw in self.profile.get("drop_resets", {}).get(str(drv), []):
            self.after(0.05, self.set_switch, sw, 0, "reset")

    # ------------------------------------------------------------------ NET
    def on_net_line(self, line):
        cmd, _, arg = line.partition(":")
        if cmd == "WD":
            self.status["watchdog"] += 1
            return
        if cmd == "TL":
            parts = arg.split(",")
            self.pulses.append((round(time.monotonic() - self.t0, 3), arg))
            del self.pulses[:-200]
            try:
                drv, mode = int(parts[0], 16), parts[1] if len(parts) > 1 else ""
            except ValueError:
                return
            if mode in ("01", "1"):
                self.on_pulse(drv)
            return
        if cmd == "SL":
            parts = arg.split(",")
            try:
                n = int(parts[0], 16)
            except ValueError:
                return
            if len(parts) > 1 and parts[1].strip() == "02":
                self.opto.add(n)
            else:
                self.opto.discard(n)
            return
        if cmd == "DL":
            self.drivers[arg.split(",")[0]] = arg
            self.send(NET, "DL:P")
            return
        self.log("NET <- %s" % line)
        if cmd == "ID":
            self.status["net_id"] = True
            self.send(NET, "ID:NET FP-CPU-2000 %s" % self.profile.get("neuron_fw", "02.26"))
        elif cmd == "CH":
            self.status["configured"] = True
            self.send(NET, "CH:P")
        elif cmd == "NN":
            try:
                node = int(arg, 16)
            except ValueError:
                node = -1
            nodes = self.profile.get("nodes", [])
            if 0 <= node < len(nodes):
                name, drv, sw = nodes[node]
                # strtok(".,"): node, name, fw major, minor, drivers, switches
                self.send(NET, "NN:%02X,%s,01.00,%02X,%02X,00,00,00,00,00,00"
                          % (node, name, drv, sw))
                self.status["nodes"] = max(self.status["nodes"], node + 1)
            else:
                self.send(NET, "NN:F")
        elif cmd == "SA":
            self.status["sa"] += 1
            self.send(NET, self.sa_reply())
        elif cmd in ("CN", "NI"):
            self.send(NET, "%s:P" % cmd)
        # anything else: not waited for as far as fast.c goes - no reply

    # ------------------------------------------------------------------ EXP
    def on_exp_line(self, line):
        cmd, _, arg = line.partition(":")
        board, addr = cmd, None
        if "@" in cmd:
            board, _, addr = cmd.partition("@")
        if board == "EA":
            self.exp_sel = arg.strip()[:2].upper()
            return
        addr = (addr or self.exp_sel or "").upper()
        if board == "RS":
            # RS:<index hex 2><rrggbb> on the selected board (one LED)
            try:
                idx = int(arg[0:2], 16)
                self.leds[(addr, idx)] = (int(arg[2:4], 16), int(arg[4:6], 16),
                                          int(arg[6:8], 16))
            except ValueError:
                pass
            return
        if board == "ID":
            name = self.profile.get("exp_boards", {}).get(addr)
            self.log("EXP <- %s%s" % (line, "" if name else " (absent)"))
            if name:
                if addr not in self.status["exp"]:
                    self.status["exp"].append(addr)
                self.send(EXP, "ID:EXP %s 00.10" % name)
            return
        self.log("EXP <- %s" % line)
        if board in ("BR", "EM", "ER"):
            self.send(EXP, "%s:P" % board)
        elif board == "MF" and len(arg.split(",")) == 3:
            self.send(EXP, "MF:P")

    # ---------------------------------------------------------------- lines
    def pump_lines(self, p, handler):
        while b"\r" in p.rx:
            line, _, p.rx = p.rx.partition(b"\r")
            line = line.strip(b" \t\n\x00").decode("latin-1")
            if line:
                if self.trace and not line.startswith(("WD:", "RS:")):
                    self.log("%s << %s" % (p.role.upper(), line))
                handler(line)

    # -------------------------------------------------------------- control
    def state(self):
        return {
            "up": True,
            "paused": self.paused,
            "title": self.profile.get("title", ""),
            "switches": {str(k): v for k, v in sorted(self.switches.items()) if v},
            "lights": {"%s:%d" % k: list(v) for k, v in sorted(self.leds.items())
                       if any(v)},
            "optos": sorted(self.opto),
            "balls": {"trough": self.in_trough, "in_play": self.in_play,
                      "shooter": bool(self.shooter is not None
                                      and self.switches.get(self.shooter))},
            "drivers_configured": len(self.drivers),
            "pulses": self.pulses[-20:],
            "leds_lit": sum(1 for v in self.leds.values() if any(v)),
            "leds_known": len(self.leds),
            "status": self.status,
        }

    def on_ctl(self, conn, line):
        words = line.split()
        if not words:
            return
        try:
            if words[0] == "sw":
                self.press(int(words[1], 0), int(words[2]))
                conn.sendall(b"ok\n")
            elif words[0] == "tap":
                n = int(words[1], 0)
                ms = int(words[2]) if len(words) > 2 else 150
                self.set_switch(n, 1)
                self.after(ms / 1000.0, self.set_switch, n, 0, "ctl")
                conn.sendall(b"ok\n")
            elif words[0] == "plunge":
                conn.sendall(b"ok\n" if self.plunge() else b"err no ball in the shooter lane\n")
            elif words[0] == "drain":
                conn.sendall(b"ok\n" if self.drain() else b"err no ball in play\n")
            elif words[0] == "rip":
                self.rip(int(words[1], 0), int(words[2]))
                conn.sendall(b"ok\n")
            elif words[0] == "reset":
                self.reset_balls()
                conn.sendall(b"ok\n")
            elif words[0] == "pause":
                conn.sendall((json.dumps({"paused": self.set_pause(int(words[1]))})
                              + "\n").encode())
            elif words[0] == "state":
                conn.sendall((json.dumps(self.state()) + "\n").encode())
            elif words[0] == "leds":
                conn.sendall((json.dumps({"%s:%d" % k: "%02x%02x%02x" % v
                                          for k, v in self.leds.items()})
                              + "\n").encode())
            elif words[0] == "quit":
                conn.sendall(b"bye\n")
                raise SystemExit(0)
            else:
                conn.sendall(b"err unknown command\n")
        except (ValueError, IndexError) as e:
            conn.sendall(("err %s\n" % e).encode())

    # ----------------------------------------------------------------- loop
    def run(self):
        ctl_path = os.path.join(self.root, "ctl.sock")
        if os.path.exists(ctl_path):
            os.unlink(ctl_path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(ctl_path)
        os.chmod(ctl_path, 0o666)
        srv.listen(8)
        srv.setblocking(False)
        clients = {}
        by_fd = {p.master: p for p in self.ports.values()}
        handlers = {NET: self.on_net_line, EXP: self.on_exp_line}
        with open(os.path.join(self.root, "pbfast.pid"), "w") as f:
            f.write(str(os.getpid()))
        self.log("ready")
        while True:
            now = time.monotonic()
            while self.timers and self.timers[0][0] <= now:
                _, _, fn, args = heapq.heappop(self.timers)
                try:
                    fn(*args)
                except Exception as e:      # noqa: BLE001
                    self.log("ERROR in timer %s: %r" % (fn.__name__, e))
            timeout = 0.05
            if self.timers:
                timeout = max(0.0, min(timeout, self.timers[0][0] - now))
            rlist = [srv] + list(by_fd) + list(clients)
            wlist = [p.master for p in self.ports.values() if p.tx]
            r, w, _ = select.select(rlist, wlist, [], timeout)
            for fd in w:
                p = by_fd[fd]
                try:
                    n = os.write(fd, p.tx)
                    p.tx = p.tx[n:]
                except BlockingIOError:
                    pass
                except OSError:
                    p.tx = b""
            for fd in r:
                if fd is srv:
                    c, _ = srv.accept()
                    clients[c] = b""
                    continue
                if fd in clients:
                    try:
                        data = fd.recv(4096)
                    except OSError:
                        data = b""
                    if not data:
                        clients.pop(fd)
                        fd.close()
                        continue
                    clients[fd] += data
                    while b"\n" in clients[fd]:
                        line, _, clients[fd] = clients[fd].partition(b"\n")
                        try:
                            self.on_ctl(fd, line.decode().strip())
                        except OSError:
                            pass
                    continue
                p = by_fd[fd]
                try:
                    data = os.read(fd, 65536)
                except (BlockingIOError, OSError):
                    continue
                p.rx += data
                # A reply bug must never take the ports down: the game treats
                # a silent port as unplugged hardware.
                try:
                    self.pump_lines(p, handlers[p.role])
                except Exception as e:      # noqa: BLE001 - logged, loop lives
                    self.log("ERROR handling %s: %r" % (p.role, e))
                    p.rx = b""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", required=True, help="rig dir (dev/, ctl.sock)")
    ap.add_argument("--title", default="predator", help="pbtitles.py key")
    args = ap.parse_args()
    import pbtitles
    profile = pbtitles.TITLES[args.title]
    os.makedirs(args.dir, exist_ok=True)
    log = open(os.path.join(args.dir, "pbfast.log"), "a")
    emu = Emulator(args.dir, profile, log)
    emu.build()
    try:
        emu.run()
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
