"""pinproc.py - the `pinproc` module an American Pinball game imports, for a
game running on its own FakePinPROC (tools/ap_emu).

Every SkeletonGame title imports pinproc even when config.yaml selects
procgame.fakepinproc.FakePinPROC: for its constants, decode(), the
driver_state_*() / aux_command_*() helpers the switch rules are built from,
and normalize_machine_type().  The machine has pypinproc's pinproc.so
(built against libpinproc); this is the module-level part of it in pure
Python, ported from pypinproc.cpp / libpinproc's PRDecode (the same port
tools/proc_emu carries, where a whole P-ROC is modelled).  No board: PinPROC()
raises IOError, as pypinproc does with none plugged in.

Runs on Python 2.7 and 3.x.
"""

# ------------------------------------------------------------------ constants
EventTypeSwitchClosedDebounced = 1
EventTypeSwitchOpenDebounced = 2
EventTypeSwitchClosedNondebounced = 3
EventTypeSwitchOpenNondebounced = 4
EventTypeDMDFrameDisplayed = 5
EventTypeBurstSwitchOpen = 6
EventTypeBurstSwitchClosed = 7
EventTypeAccelerometerX = 8
EventTypeAccelerometerY = 9
EventTypeAccelerometerZ = 10
EventTypeAccelerometerIRQ = 11

MachineTypeInvalid = 0
MachineTypeCustom = 1
MachineTypeWPCAlphanumeric = 2
MachineTypeWPC = 3
MachineTypeWPC95 = 4
MachineTypeSternWhitestar = 5
MachineTypeSternSAM = 6
MachineTypePDB = 7

SwitchCount = 255            # sic: pypinproc exports kPRSwitchPhysicalLast
SwitchNeverDebounceFirst = 192
SwitchNeverDebounceLast = 255
DriverCount = 256


DRIVER_KEYS = ("driverNum", "outputDriveTime", "polarity", "state",
               "waitForFirstTimeSlot", "timeslots", "patterOnTime",
               "patterOffTime", "patterEnable", "futureEnable")
AUX_KEYS = ("active", "delayTime", "jumpAddr", "command", "data",
            "extraData", "enables", "muxEnables")
AUX_CMD_JUMP, AUX_CMD_DELAY, AUX_CMD_OUTPUT = 0, 1, 2

try:
    _int_types = (int, long)            # Python 2
    _str_types = (str, unicode)
except NameError:                       # Python 3
    _int_types = (int,)
    _str_types = (str,)

_g_machine_type = MachineTypeInvalid    # pypinproc's g_machineType
_g_switch_config_sent = False           # pypinproc's static firstTime


def _u8(v):
    return int(v) & 0xff


def _u16(v):
    return int(v) & 0xffff


def _u32(v):
    return int(v) & 0xffffffff


def _i32(v):
    v = int(v) & 0xffffffff
    return v - 0x100000000 if v & 0x80000000 else v


# ------------------------------------------------------------ module helpers
def normalize_machine_type(machine_type):
    """Converts a string to an integer style machine type.  Integers pass through."""
    if isinstance(machine_type, bool) or not isinstance(machine_type, _int_types + _str_types):
        return MachineTypeInvalid
    if isinstance(machine_type, _int_types):
        return int(machine_type)
    try:
        return int(machine_type, 0)
    except ValueError:
        pass
    return {"wpc": MachineTypeWPC, "wpcAlphanumeric": MachineTypeWPCAlphanumeric,
            "wpc95": MachineTypeWPC95, "sternSAM": MachineTypeSternSAM,
            "sternWhitestar": MachineTypeSternWhitestar, "pdb": MachineTypePDB,
            "custom": MachineTypeCustom}.get(machine_type, MachineTypeInvalid)


def _atoi(s):
    s = s.lstrip(" \t\n\r\f\v")
    n, sign, i = 0, 1, 0
    if s[:1] in ("+", "-"):
        sign, i = (-1 if s[0] == "-" else 1), 1
    while i < len(s) and s[i].isdigit():
        n, i = n * 10 + int(s[i]), i + 1
    return sign * n


def _pr_decode(machine_type, s):
    """libpinproc PRDecode(), including its C char arithmetic."""
    if s is None:
        return 0
    c = [ord(ch) for ch in s] + [0, 0, 0, 0]
    d0 = ord("0")
    if len(s) == 3:
        x = (c[1] - d0) * 10 + (c[2] - d0)
    elif len(s) == 4:
        x = (c[2] - d0) * 10 + (c[3] - d0)
    else:
        return _atoi(s)
    x &= 0xffff
    up = [chr(v).upper() if 0 < v < 128 else "" for v in c]

    def cdiv(a, b):             # C integer division truncates toward zero
        q = abs(a) // abs(b)
        return q if (a >= 0) == (b >= 0) else -q

    def cmod(a, b):
        return a - b * cdiv(a, b)

    if machine_type in (MachineTypeWPC, MachineTypeWPC95, MachineTypeWPCAlphanumeric):
        if up[0] == "F":
            if up[1] == "L":
                if up[2] == "R":
                    return 32 if up[3] == "M" else 33
                return 34 if up[3] == "M" else 35
            if up[2] == "R":
                return 36 if up[3] == "M" else 37
            return 38 if up[3] == "M" else 39
        if up[0] == "L":
            return 80 + 8 * (cdiv(x, 10) - 1) + (cmod(x, 10) - 1)
        if up[0] == "C":
            if x <= 28:
                return x + 39
            if x <= 36:
                return x + 3
            if x <= 44:
                return x + 31 if machine_type == MachineTypeWPC95 else x + 107
            return x + 108
        if up[0] == "G":
            return x + 71
        if up[0] == "S":
            if up[1] == "D":
                return 8 + ((c[2] - d0) - 1)
            if up[1] == "F":
                return (c[2] - d0) - 1
            return 32 + 16 * (cdiv(x, 10) - 1) + (cmod(x, 10) - 1)
    elif machine_type == MachineTypeSternSAM:
        if up[0] == "L":
            return 80 + 16 * (7 - cmod(x - 1, 8)) + cdiv(x - 1, 8)
        if up[0] == "C":
            return x + 31
        if up[0] == "S":
            if up[1] == "D":
                return (c[2] - d0) + 7 if len(s) == 3 else x + 7
            if cmod(x - 1, 16) < 8:
                return 32 + 8 * cdiv(x - 1, 8) + (7 - cmod(x - 1, 8))
            return 32 + (x - 1)
    elif machine_type == MachineTypeSternWhitestar:
        if up[0] == "L":
            return 80 + 16 * (7 - cmod(x - 1, 8)) + cdiv(x - 1, 8)
        if up[0] == "C":
            return x + 31
        if up[0] == "S":
            if up[1] == "D":
                return (c[2] - d0) + 7 if len(s) == 3 else x + 7
            return 32 + 16 * cdiv(x - 1, 8) + (7 - cmod(x - 1, 8))
    return _atoi(s)


def decode(machine_type, number):
    """Decode a switch, coil, or lamp number."""
    global _g_machine_type
    mt = normalize_machine_type(machine_type)
    _g_machine_type = mt
    if not isinstance(number, _str_types):
        raise TypeError("decode() number must be a string")
    return _pr_decode(mt, number) & 0xffff      # PRDecode returns uint16_t


def _driver_from_dict(d):
    """PyDictToDriverState(): every field takes its C type's width."""
    try:
        return {"driverNum": _u16(d["driverNum"]),
                "outputDriveTime": _u8(d["outputDriveTime"]),
                "polarity": _i32(d["polarity"]), "state": _i32(d["state"]),
                "waitForFirstTimeSlot": _i32(d["waitForFirstTimeSlot"]),
                "timeslots": _u32(d["timeslots"]),
                "patterOnTime": _u8(d["patterOnTime"]),
                "patterOffTime": _u8(d["patterOffTime"]),
                "patterEnable": _i32(d["patterEnable"]),
                "futureEnable": _i32(d["futureEnable"])}
    except KeyError as e:
        raise TypeError("driver state is missing %s" % e)


def _to_py(d):
    """DICT_SET_STRING_INT: every field comes back as a C int (signed)."""
    return dict((k, _i32(v)) for k, v in d.items())


def _driver_blank(num=0, polarity=0):
    d = dict((k, 0) for k in DRIVER_KEYS)
    d["driverNum"], d["polarity"] = num, polarity
    return d


def _state_disable(d):
    d.update(state=0, timeslots=0, waitForFirstTimeSlot=0, outputDriveTime=0,
             patterOnTime=0, patterOffTime=0, patterEnable=0, futureEnable=0)
    return d


def _state_pulse(d, ms):
    d.update(state=1, timeslots=0, waitForFirstTimeSlot=0, outputDriveTime=_u8(ms),
             patterOnTime=0, patterOffTime=0, patterEnable=0, futureEnable=0)
    return d


def _state_future_pulse(d, ms, future_time):
    d.update(state=1, timeslots=_u32(future_time), waitForFirstTimeSlot=0,
             outputDriveTime=_u8(ms), patterOnTime=0, patterOffTime=0,
             patterEnable=0, futureEnable=1)
    return d


def _state_schedule(d, schedule, seconds, now):
    schedule = _u32(schedule)
    d.update(state=int(schedule != 0), timeslots=schedule,
             waitForFirstTimeSlot=int(not now), outputDriveTime=_u8(seconds),
             patterOnTime=0, patterOffTime=0, patterEnable=0, futureEnable=0)
    return d


def _state_patter(d, on, off, original_on_time, now):
    d.update(state=1, timeslots=0, waitForFirstTimeSlot=int(not now),
             outputDriveTime=_u8(original_on_time), patterOnTime=_u8(on),
             patterOffTime=_u8(off), patterEnable=1, futureEnable=0)
    return d


def _state_pulsed_patter(d, on, off, patter_time, now):
    d.update(state=0, timeslots=0, waitForFirstTimeSlot=int(not now),
             outputDriveTime=_u8(patter_time), patterOnTime=_u8(on),
             patterOffTime=_u8(off), patterEnable=1, futureEnable=0)
    return d


def driver_state_disable(state):
    """Return a copy of the given driver state to disable the driver"""
    return _to_py(_state_disable(_driver_from_dict(state)))


def driver_state_pulse(state, milliseconds):
    """Return a copy of the given driver state to pulse the driver"""
    return _to_py(_state_pulse(_driver_from_dict(state), milliseconds))


def driver_state_future_pulse(state, milliseconds, future_time):
    """Return a copy of the given driver state to pulse the driver in the future"""
    return _to_py(_state_future_pulse(_driver_from_dict(state), milliseconds, future_time))


def driver_state_schedule(state, schedule, seconds, now):
    """Return a copy of the given driver state to schedule the driver"""
    return _to_py(_state_schedule(_driver_from_dict(state), schedule, _i32(seconds), int(now) != 0))


def driver_state_patter(state, milliseconds_on, milliseconds_off, original_on_time, now):
    """Return a copy of the given driver state to patter the driver"""
    return _to_py(_state_patter(_driver_from_dict(state), milliseconds_on, milliseconds_off,
                                original_on_time, now is True))


def driver_state_pulsed_patter(state, milliseconds_on, milliseconds_off,
                               milliseconds_overal_patter_time, now):
    """Return a copy of the given driver state to pulsed-patter the driver"""
    return _to_py(_state_pulsed_patter(_driver_from_dict(state), milliseconds_on,
                                       milliseconds_off, milliseconds_overal_patter_time,
                                       now is True))


def _aux(active, command, data=0, extra_data=0, enables=0, mux_enables=0,
         delay_time=0, jump_addr=0):
    return {"active": active, "delayTime": _u16(delay_time), "jumpAddr": _u8(jump_addr),
            "command": command, "data": _u8(data), "extraData": _u8(extra_data),
            "enables": _u8(enables), "muxEnables": int(mux_enables)}


def aux_command_output_custom(data, extra_data, enables, mux_enables, delay_time):
    """Return a copy of the given aux output command"""
    return _aux(1, AUX_CMD_OUTPUT, data, extra_data, enables, mux_enables, delay_time)


def aux_command_output_primary(data, extra_data, delay_time):
    """Return a copy of the given primary aux output command"""
    if _g_machine_type == MachineTypeWPCAlphanumeric:
        return _aux(1, AUX_CMD_OUTPUT, data, extra_data, 8, 0, delay_time)
    if _g_machine_type in (MachineTypeSternWhitestar, MachineTypeSternSAM):
        return _aux(1, AUX_CMD_OUTPUT, data, 0, 6, 1, delay_time)
    raise SystemError("error return without exception set")


def aux_command_output_secondary(data, extra_data, delay_time):
    """Return a copy of the given secondary aux output command"""
    if _g_machine_type in (MachineTypeSternWhitestar, MachineTypeSternSAM):
        return _aux(1, AUX_CMD_OUTPUT, data, 0, 11, 1, delay_time)
    raise SystemError("error return without exception set")


def aux_command_delay(delay_time):
    """Return a copy of the given aux delay command"""
    return _aux(1, AUX_CMD_DELAY, delay_time=delay_time)


def aux_command_jump(jump_address):
    """Return a copy of the given aux jump command"""
    return _aux(1, AUX_CMD_JUMP, jump_addr=jump_address)


def aux_command_disable():
    """Return a copy of the given aux command disabled"""
    # PRDriverAuxPrepareDisable leaves command/delay/jump uninitialised on the
    # C stack; zero is what a fresh frame usually holds.
    return _aux(0, 0)



class PinPROC(object):
    """No P-ROC here: the rig always runs the game on FakePinPROC."""

    def __init__(self, machine_type):
        raise IOError("pinproc: no P-ROC board (tools/ap_emu runs FakePinPROC)")


def _rect_intersection(r0, r1):
    x0, y0, w0, h0 = r0
    x1, y1, w1, h1 = r1
    if x0 + w0 <= x1 or x0 >= x1 + w1 or y0 + h0 <= y1 or y0 >= y1 + h1:
        return (0, 0, 0, 0)
    x, y = max(x0, x1), max(y0, y1)
    return (x, y, min(x0 + w0, x1 + w1) - x, min(y0 + h0, y1 + h1) - y)


class DMDBuffer(object):
    """pinproc.DMDBuffer: a width x height surface of 1-byte dots."""

    def __init__(self, width, height):
        self._w, self._h = int(width), int(height)
        self._buf = bytearray(self._w * self._h)

    def clear(self):
        self._buf[:] = bytearray(len(self._buf))

    def set_data(self, data):
        if len(data) != len(self._buf):
            raise ValueError("Buffer length is incorrect")
        self._buf[:] = bytearray(data)

    def get_data(self):
        return bytes(self._buf)

    def get_data_mult(self):
        out = bytearray(len(self._buf))
        for i, v in enumerate(self._buf):
            c = ((v + 1) * 16 - 1) & 0xff
            out[i] = c if c > 15 else 0
        return bytes(out)

    def get_dot(self, x, y):
        if x >= self._w or y >= self._h:
            raise ValueError("X or Y are out of range")
        return self._buf[y * self._w + x]

    def set_dot(self, x, y, value):
        if x >= self._w or y >= self._h:
            raise ValueError("X or Y are out of range")
        self._buf[y * self._w + x] = value & 0xff

    def fill_rect(self, x, y, width, height, value):
        rx, ry, rw, rh = _rect_intersection((0, 0, self._w, self._h), (x, y, width, height))
        for row in range(ry, ry + rh):
            start = row * self._w + rx
            self._buf[start:start + rw] = bytearray([value & 0xff]) * rw
