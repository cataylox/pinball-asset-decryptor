"""probe.py - one fixed session through the pinproc API, printed as lines.

run.sh runs it on the stub and on the real pypinproc + libpinproc +
fakeftdi, on Python 2.7 and 3.x, each against a freshly started board with
selftest/machine.yaml; every run must print the same lines.  Nothing here
may print a timestamp or anything else that differs run to run.
"""
from __future__ import print_function

import json
import os
import socket
import sys
import time

import pinproc

CTL = os.path.join(os.path.dirname(os.environ["PROC_EMU_FPGA"]), "ctl.sock")


def ctl(line):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(CTL)
    s.sendall((line + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        buf += s.recv(65536)
    s.close()
    return buf.decode().strip()


def events_until(p, count, timeout=2.0):
    got, end = [], time.time() + timeout
    while time.time() < end and len(got) < count:
        got += [(e["type"], e["value"]) for e in p.get_events()
                if e["type"] != pinproc.EventTypeDMDFrameDisplayed]
        time.sleep(0.01)
    return got


def out(*a):
    print(*a)
    sys.stdout.flush()


sys.stderr.write("probe: %s pinproc on Python %d.%d\n" % (
    "stub" if hasattr(pinproc, "SocketLink") else "real", sys.version_info[0], sys.version_info[1]))

# ---- module level: identical in both, no board involved
for mt in ("wpc", "wpc95", "wpcAlphanumeric", "sternSAM", "sternWhitestar", "pdb", "custom"):
    out("normalize", mt, pinproc.normalize_machine_type(mt))
for mt in ("wpc", "wpc95", "sternSAM", "sternWhitestar", "pdb"):
    nums = [pinproc.decode(mt, s) for s in (
        "S11", "S88", "SD1", "SF4", "SD12", "C01", "C28", "C33", "C40", "C45", "L11", "L88",
        "L01", "L64", "G05", "FLRM", "FLRH", "FULM", "FURH", "flrm", "42", "S01", "S16",
        "S17", "S64", "SD0")]
    out("decode", mt, nums)
blank = {"driverNum": 7, "outputDriveTime": 0, "polarity": True, "state": False,
         "waitForFirstTimeSlot": False, "timeslots": 0, "patterOnTime": 0,
         "patterOffTime": 0, "patterEnable": False, "futureEnable": False}
for name, d in (("pulse", pinproc.driver_state_pulse(blank, 300)),
                ("disable", pinproc.driver_state_disable(blank)),
                ("schedule", pinproc.driver_state_schedule(blank, 0xff00ff00, 2, True)),
                ("patter", pinproc.driver_state_patter(blank, 2, 18, 30, True)),
                ("patter-now1", pinproc.driver_state_patter(blank, 2, 18, 30, 1)),
                ("pulsed_patter", pinproc.driver_state_pulsed_patter(blank, 5, 5, 400, False)),
                ("future", pinproc.driver_state_future_pulse(blank, 20, 12345))):
    out("state", name, json.dumps(d, sort_keys=True))
# (libpinproc leaves the fields a command does not use uninitialised: print
# only the ones each command sets)
def aux(d, keys):
    return json.dumps(dict((k, d[k]) for k in keys), sort_keys=True)


out("aux", aux(pinproc.aux_command_output_custom(0x1ff, 3, 9, True, 100),
               ("active", "command", "data", "extraData", "enables", "muxEnables", "delayTime")))
out("aux", aux(pinproc.aux_command_delay(300), ("active", "command", "delayTime", "data")))
out("aux", aux(pinproc.aux_command_jump(7), ("active", "command", "jumpAddr", "data")))
out("consts", pinproc.SwitchCount, pinproc.SwitchNeverDebounceFirst, pinproc.DriverCount,
    pinproc.EventTypeDMDFrameDisplayed, pinproc.MachineTypePDB)

# ---- the board
p = pinproc.PinPROC(pinproc.normalize_machine_type("pdb"))
p.reset(1)
states = p.switch_get_states()
out("switch_states", len(states), sorted(set(states)))
out("closed", [i for i, s in enumerate(states) if s == pinproc.EventTypeSwitchClosedDebounced])

flip = {"driverNum": 1, "outputDriveTime": 0, "polarity": True, "state": False,
        "waitForFirstTimeSlot": False, "timeslots": 0, "patterOnTime": 0,
        "patterOffTime": 0, "patterEnable": False, "futureEnable": False}
p.driver_update_state(flip)
out("get_state", json.dumps(p.driver_get_state(1), sort_keys=True))
notify = {"notifyHost": True, "reloadActive": False}
quiet = {"notifyHost": False, "reloadActive": False}
for sw in (8, 72):
    p.switch_update_rule(sw, "closed_debounced", notify)
    p.switch_update_rule(sw, "open_debounced", notify)
# a Stern-style flipper: button closes -> pulse then hold; opens -> off
p.switch_update_rule(0, "closed_nondebounced", quiet,
                     [pinproc.driver_state_pulse(flip, 30),
                      pinproc.driver_state_patter(dict(flip, driverNum=2), 2, 18, 0, True)])
p.switch_update_rule(0, "open_nondebounced", quiet,
                     [pinproc.driver_state_disable(flip),
                      pinproc.driver_state_disable(dict(flip, driverNum=2))])
p.switch_update_rule(0, "closed_debounced", notify)
p.flush()

out("ctl", ctl("sw startButton 1").split()[0])
out("ctl", ctl("sw startButton 0").split()[0])
out("events", events_until(p, 2))
out("ctl", ctl("sw trough1 0").split()[0])            # a ball leaves the trough
out("events", events_until(p, 1))
out("ctl", ctl("sw flipperLwL 1").split()[0])
out("events", events_until(p, 1))
out("ctl", ctl("sw flipperLwL 0").split()[0])
time.sleep(0.05)
log = json.loads(ctl("log 20"))
out("rule_drivers", json.dumps([[e["driver"], e["action"]] for e in log
                                if e["by"].startswith("rule")]))

for n in (5, 6, 7):     # as pdb.py does: a PDB driver's slot is blank until written
    p.driver_update_state(dict(flip, driverNum=n))
p.driver_pulse(5, 40)
p.driver_schedule(6, 0xf0f0f0f0, 0, True)
p.driver_patter(7, 10, 20, 0, True)
p.led_color(0, 3, 200)
p.led_fade(1, 4, 99, 0x123)
p.flush()
time.sleep(0.05)
log = json.loads(ctl("log 20"))
out("host_drivers", json.dumps([[e["driver"], e["action"]] for e in log
                                if e["by"] == "host" and e["driver"] in (5, 6, 7)]))
out("leds", json.dumps(json.loads(ctl("leds")), sort_keys=True))
p.watchdog_tickle()
p.flush()
time.sleep(0.02)
st = json.loads(ctl("state"))
out("board", st["board"], "host_events", st["host_events"], "watchdog_seen",
    st["watchdog_ms"] is not None)
p.write_data(3, 0xC00, 0x01020105)
time.sleep(0.02)
out("leds", json.dumps(json.loads(ctl("leds")), sort_keys=True))
out("done")
