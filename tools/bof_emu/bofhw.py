#!/usr/bin/env python3
"""bofhw.py - emulated FAST Neuron + expansion bus + BICS board for a
Barrels of Fun game.

The game (a native x86-64 Godot export) talks to its hardware over three USB
CDC serial ports.  This daemon makes a pty for each, presents them as
/dev/ttyACM0..2 through bofhwshim.so (see that file for how) and answers the
protocols the game's own scripts speak:

  NET  (ttyACM0, FAST Neuron, 921600)  ID: CH: CN: SA: SL: DL: TL: WD:
                                        -> switch events -L:xx (active) /L:xx
  EXP  (ttyACM1, FAST expansion bus)    ID@<board>: then ER@/RF@/LM@ config and
                                        binary RD@/RL@ LED frames
  BICS (ttyACM2, BoF's own board)       Dune's worm wrangler: ID: HOME: MOVE:
                                        POSITION: SET: FIRE: ARM: ... \\r\\n

Nothing here is guessed from FAST documentation: every reply is shaped by the
parser in the title's fast_stem.gd / bics.gd (decompiled), which is the only
reader that matters.  See docs/plans/bof_emulator.md.

Control: a unix socket at <dir>/ctl.sock taking one command per line:
  sw <n> <0|1>      set a switch (logical: 1 = active)
  tap <n> [ms]      press, then release after ms (default 120)
  state             JSON: switches, driver actions, LED count, board status
  quit
"""
import argparse
import heapq
import json
import os
import select
import socket
import sys
import time
import tty

NET, EXP, BICS = "net", "exp", "bics"

# The USB identity each port shows through the fake sysfs.  The game matches
# FAST ports on desc containing "FAST Pinball" (desc = "<manufacturer>
# <product> <serial>") and the BICS board on hw_id containing "PID=2341:"
# (hw_id = "USB VID:PID=<idVendor>:<idProduct> SNR=<serial>").
PORTS = [
    # name,     role,  usb dev, iface, manufacturer,    product,       vid,    pid
    ("ttyACM0", NET,  "1-1",   "1.0", "FAST Pinball", "Neuron",       "2e8a", "1074"),
    ("ttyACM1", EXP,  "1-1",   "1.2", "FAST Pinball", "Neuron",       "2e8a", "1074"),
    ("ttyACM2", BICS, "1-2",   "1.0", "Arduino LLC",  "Arduino Due",  "2341", "003d"),
]
ALIASES = {"bof_worm": "ttyACM2"}

NUM_SWITCH_BYTES = 16        # SA: reply covers switches 0..127


class Port:
    def __init__(self, name, role):
        self.name, self.role = name, role
        self.master, slave = os.openpty()
        tty.setraw(slave)
        # Keep our own slave fd open so the master never sees EIO while the
        # game closes and reopens the port (it does, around "firmware updates").
        self.slave = slave
        self.pts = os.ttyname(slave)
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
        self.reversed = {}          # from SL: mode 2
        self.drivers = {}           # DL: config lines by driver hex
        self.driver_log = []        # recent TL: actions
        self.leds = {}              # (board, index) -> (r, g, b)
        self.exp_config = []
        self.status = {"net_id": False, "configured": False, "nodes": False,
                       "exp": set(), "bics_id": False, "watchdog": 0}
        self.timers = []
        self.bics = {
            "pos": {"WORM": "5.0", "MOUTH": "-5.0"},
            "offsets": {"WORM": ["5.0", "0.0", "3.50", "87.0"],
                        "MOUTH": ["-5.0", "0.0", "42.50", "125.0"]},
        }
        for n in profile.get("active_at_boot", []):
            self.switches[int(n)] = 1

    # ---------------------------------------------------------------- setup
    def build(self):
        dev = os.path.join(self.root, "dev")
        sysroot = os.path.join(self.root, "sys")
        os.makedirs(dev, exist_ok=True)
        for (name, role, usb, iface, manu, prod, vid, pid) in PORTS:
            p = Port(name, role)
            self.ports[role] = p
            link = os.path.join(dev, name)
            if os.path.lexists(link):
                os.unlink(link)
            os.symlink(p.pts, link)
            usbdir = os.path.join(sysroot, "devices", "pci0000:00", "usb1", usb)
            ifdir = os.path.join(usbdir, "%s:%s" % (usb, iface))
            os.makedirs(ifdir, exist_ok=True)
            for fname, val in (("manufacturer", manu), ("product", prod),
                               ("serial", "PAD%s" % usb.replace("-", "")),
                               ("idVendor", vid), ("idProduct", pid)):
                with open(os.path.join(usbdir, fname), "w") as f:
                    f.write(val + "\n")
            ttydir = os.path.join(sysroot, "class", "tty", name)
            os.makedirs(ttydir, exist_ok=True)
            dlink = os.path.join(ttydir, "device")
            if os.path.lexists(dlink):
                os.unlink(dlink)
            os.symlink(os.path.relpath(ifdir, ttydir), dlink)
        for alias, target in ALIASES.items():
            link = os.path.join(dev, alias)
            if os.path.lexists(link):
                os.unlink(link)
            os.symlink(os.path.join(dev, target), link)
        self.log("ports: " + ", ".join("%s=%s" % (p.name, p.pts)
                                       for p in self.ports.values()))

    # ---------------------------------------------------------------- utils
    def log(self, msg):
        self.logf.write("%9.3f %s\n" % (time.monotonic() - self.t0, msg))
        self.logf.flush()

    def send(self, role, data):
        if isinstance(data, str):
            data = data.encode("latin-1")
        p = self.ports[role]
        p.tx += data

    def after(self, secs, fn, *args):
        heapq.heappush(self.timers, (time.monotonic() + secs, id(fn), fn, args))

    # ------------------------------------------------------------- switches
    def set_switch(self, n, active, source="ctl"):
        active = 1 if active else 0
        if self.switches.get(n, 0) == active:
            return
        self.switches[n] = active
        self.log("SW %d -> %s (%s)" % (n, "active" if active else "inactive",
                                       source))
        bics_sw = self.profile.get("bics_switches", {})
        if str(n) in bics_sw:
            # BICS reports its own switches with the OPPOSITE prefixes.
            self.send(BICS, "%s:%s\r\n" % ("/L" if active else "-L",
                                           bics_sw[str(n)]))
        else:
            self.send(NET, "%s:%02X\r" % ("-L" if active else "/L", n))

    def switch_bytes_hex(self):
        out = []
        for b in range(NUM_SWITCH_BYTES):
            v = 0
            for bit in range(8):
                n = b * 8 + bit
                phys = self.switches.get(n, 0) ^ (1 if self.reversed.get(n) else 0)
                if phys:
                    v |= 1 << bit
            out.append("%02X" % v)
        return "".join(out)

    # ------------------------------------------------------------------ NET
    def on_net_line(self, line):
        if ":" not in line:
            return
        cmd, _, arg = line.partition(":")
        if cmd == "WD":
            self.status["watchdog"] += 1
            self.send(NET, "WD:P\r")
            return
        if cmd not in ("SL", "DL", "TL"):
            self.log("NET <- %s" % line)
        if cmd == "ID":
            self.status["net_id"] = True
            # Parsed as split(" "): [1] board, [3] firmware -> the double space.
            self.send(NET, "ID:NET FP-CPU-2000  %s\r" %
                      self.profile.get("neuron_fw", "02.26"))
        elif cmd == "CH":
            self.status["configured"] = True
            self.send(NET, "CH:P\r")
        elif cmd == "CN":
            # One NN line per node board; the game matches each against its
            # node_boards list by substring and reads split(" ")[5].
            for i, board in enumerate(self.profile.get(
                    "node_boards", ["0024-2", "3208-2", "1616-2", "3208-2"])):
                self.send(NET, "NN:%02X FP-I/O-%s 00 00 00 01.10\r" % (i, board))
            self.status["nodes"] = True
        elif cmd == "SA":
            self.send(NET, "SA:%02X,%s\r" % (NUM_SWITCH_BYTES * 8,
                                             self.switch_bytes_hex()))
        elif cmd == "SL":
            parts = arg.split(",")
            try:
                n = int(parts[0], 16)
                self.reversed[n] = parts[1].strip() == "2"
            except (ValueError, IndexError):
                pass
            self.send(NET, "SL:P\r")
        elif cmd == "DL":
            parts = arg.split(",")
            self.drivers[parts[0]] = arg
            self.send(NET, "DL:P\r")
        elif cmd == "TL":
            parts = arg.split(",")
            self.driver_log.append((round(time.monotonic() - self.t0, 3), arg))
            del self.driver_log[:-200]
            self.log("NET <- TL:%s" % arg)
            self.send(NET, "TL:P\r")
            self.on_driver(parts)
        else:
            self.send(NET, "%s:P\r" % cmd)

    def on_driver(self, parts):
        """Hook for the ball model: a driver action from the game."""
        try:
            drv = int(parts[0], 16)
        except ValueError:
            return
        mode = parts[1] if len(parts) > 1 else ""
        eject = self.profile.get("trough_eject_driver")
        if eject is not None and drv == eject and mode in ("01", "1", "0"):
            self.trough_eject()

    def trough_eject(self):
        trough = self.profile.get("trough_switches", [])
        shooter = self.profile.get("shooter_switch")
        full = [n for n in trough if self.switches.get(n)]
        if not full or shooter is None or self.switches.get(shooter):
            return
        # The ball leaves the eject position; the rest roll down.
        self.set_switch(full[0], 0, "ball")
        self.after(0.25, self.set_switch, shooter, 1, "ball")

    # ------------------------------------------------------------------ EXP
    def pump_exp(self, p):
        buf = p.rx
        while buf:
            if buf[:1] == b"\r":
                buf = buf[1:]
                continue
            if buf[:3] in (b"RD@", b"RL@"):
                colon = buf.find(b":")
                if colon < 0 or len(buf) < colon + 2:
                    break
                count = buf[colon + 1]
                width = 4 if buf[:2] == b"RD" else 5
                end = colon + 2 + count * width
                if len(buf) < end:
                    break
                board = buf[3:colon].decode("latin-1")
                body = buf[colon + 2:end]
                for i in range(count):
                    e = body[i * width:(i + 1) * width]
                    self.leds[(board, e[0])] = (e[1], e[2], e[3])
                buf = buf[end:]
                continue
            cr = buf.find(b"\r")
            if cr < 0:
                break
            self.on_exp_line(buf[:cr].decode("latin-1"))
            buf = buf[cr + 1:]
        p.rx = buf

    def on_exp_line(self, line):
        if line.startswith("ID@"):
            board = line[3:].rstrip(":")
            self.status["exp"].add(board)
            self.log("EXP <- %s" % line)
            fw = self.profile.get("exp_fw", {}).get(board, "00.44")
            self.send(EXP, "ID:EXP FP-EXP-%s  %s\r" % (board.upper(), fw))
        elif line.startswith(("ER@", "LM@", "RF@", "em@")):
            self.exp_config.append(line)
        elif line.startswith("RA@"):
            board, _, col = line[3:].partition(":")
            self.log("EXP <- %s" % line)
        elif line:
            self.log("EXP <- %s" % line)

    # ----------------------------------------------------------------- BICS
    def on_bics_line(self, line):
        if ":" not in line:
            return
        self.log("BICS <- %s" % line)
        cmd, _, arg = line.partition(":")
        b = self.bics
        reply = None
        if cmd == "ID":
            self.status["bics_id"] = True
            reply = "ID:WORM WRANGLER,PAD,EMULATED,v%s" % self.profile.get(
                "bics_fw", "1.0.0")
        elif cmd == "RESET?" or line.startswith("RESET?"):
            reply = "RESET:ACK"
        elif cmd == "HOME":
            if arg == "STEPPER ALL":
                b["pos"]["WORM"] = b["offsets"]["WORM"][0]
                b["pos"]["MOUTH"] = b["offsets"]["MOUTH"][0]
                reply = "HOME:STEPPER ALL,ACK"
            elif arg == "STEPPER?":
                reply = "HOME:STEPPER ACK"
            elif arg in ("EDGES", "EDGES?"):
                reply = "HOME:EDGES ACK"
            elif arg.startswith("FAST "):
                reply = "HOME:%s,ACK" % arg
            else:
                reply = "HOME:%s,ACK" % arg
        elif cmd == "MOVE":
            if arg.startswith("STEPPER "):
                bits = arg[8:].split(",")
                motor = bits[0]
                named = {"HOME": 0, "DOWN": 1, "FLUSH": 2, "UP": 3}
                targets = []
                if motor == "ALL" and len(bits) >= 3 and bits[1] not in named:
                    targets = [("WORM", bits[1]), ("MOUTH", bits[2])]
                elif len(bits) >= 2:
                    ms = ["WORM", "MOUTH"] if motor == "ALL" else [motor]
                    targets = [(m, bits[1]) for m in ms]
                for m, pos in targets:
                    if m not in b["pos"]:
                        continue
                    if pos.upper() in named:
                        b["pos"][m] = b["offsets"][m][named[pos.upper()]]
                    else:
                        b["pos"][m] = pos
                reply = "MOVE:%s,ACK" % arg
            else:
                reply = "MOVE:%s,ACK" % arg
        elif cmd == "POSITION":
            m = arg.split()[-1]
            if m in b["pos"]:
                reply = "POSITION:STEPPER %s,%s" % (m, b["pos"][m])
        elif cmd == "SET":
            if arg.startswith("OFFSETS? "):
                m = arg.split()[-1]
                reply = "SET:OFFSETS %s,%s" % (m, ",".join(b["offsets"][m]))
            elif arg.startswith("OFFSET "):
                m, _, which = arg[7:].partition(",")
                idx = {"HOME": 0, "DOWN": 1, "FLUSH": 2, "UP": 3}.get(which)
                if m in b["offsets"] and idx is not None:
                    b["offsets"][m][idx] = b["pos"][m]
                reply = "SET:%s,ACK" % arg
            else:
                reply = "SET:%s,ACK" % arg
        elif cmd in ("FIRE", "ARM", "STOP", "FLASH"):
            reply = "%s:%s,ACK" % (cmd, arg) if cmd != "FLASH" else None
        elif cmd == "SYS":
            reply = "SYS:OK"
        if reply:
            self.send(BICS, reply + "\r\n")

    # ---------------------------------------------------------------- lines
    def pump_lines(self, p, handler):
        while b"\r" in p.rx:
            line, _, p.rx = p.rx.partition(b"\r")
            # BICS lines can arrive with a stray leading byte (seen: a space
            # before HOME:), so trim whitespace and NULs on both ends.
            line = line.strip(b" \t\n\x00").decode("latin-1")
            if line:
                handler(line)

    # -------------------------------------------------------------- control
    def state(self):
        return {
            "switches": {str(k): v for k, v in sorted(self.switches.items()) if v},
            "reversed": sorted(k for k, v in self.reversed.items() if v),
            "drivers_configured": len(self.drivers),
            "driver_log": self.driver_log[-20:],
            "leds_lit": sum(1 for v in self.leds.values() if any(v)),
            "leds_known": len(self.leds),
            "exp_config": len(self.exp_config),
            "status": dict(self.status, exp=sorted(self.status["exp"])),
            "bics": self.bics,
        }

    def on_ctl(self, conn, line):
        words = line.split()
        if not words:
            return
        try:
            if words[0] == "sw":
                self.set_switch(int(words[1], 0), int(words[2]))
                conn.sendall(b"ok\n")
            elif words[0] == "tap":
                n = int(words[1], 0)
                ms = int(words[2]) if len(words) > 2 else 120
                self.set_switch(n, 1)
                self.after(ms / 1000.0, self.set_switch, n, 0, "ctl")
                conn.sendall(b"ok\n")
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
        with open(os.path.join(self.root, "bofhw.pid"), "w") as f:
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
                # a vanished port as unplugged hardware.
                try:
                    if p.role == NET:
                        self.pump_lines(p, self.on_net_line)
                    elif p.role == EXP:
                        self.pump_exp(p)
                    else:
                        self.pump_lines(p, self.on_bics_line)
                except Exception as e:      # noqa: BLE001 - logged, loop lives
                    self.log("ERROR handling %s: %r" % (p.role, e))
                    p.rx = b""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", required=True, help="rig dir (dev/, sys/, ctl.sock)")
    ap.add_argument("--profile", help="per-title JSON profile")
    args = ap.parse_args()
    profile = {}
    if args.profile:
        with open(args.profile) as f:
            profile = json.load(f)
    os.makedirs(args.dir, exist_ok=True)
    log = open(os.path.join(args.dir, "bofhw.log"), "a")
    emu = Emulator(args.dir, profile, log)
    emu.build()
    try:
        emu.run()
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
