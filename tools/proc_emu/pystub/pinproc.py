"""pinproc.py - a pure-Python stand-in for pypinproc (the P-ROC / P3-ROC
extension every pyprocgame and SkeletonGame title imports).

It is a port of pypinproc (pypinproc.cpp, dmdutil.cpp, dmd.c) and of the part
of libpinproc under it (pinproc.cpp, PRDevice.cpp, PRHardware.cpp): the same
module constants, decode(), driver_state_*() and aux_command_*() helpers, the
PinPROC class and DMDBuffer.  Nothing is faked at this level.  PinPROC speaks
the real P-ROC word protocol, byte for byte what libpinproc would hand the
FTDI chip, to prochw.py (tools/proc_emu), which plays the FPGA.  So a game on
this module and a game on the real pypinproc + fakeftdi.so see one and the
same machine, and the ctl socket drives both.

Where libpinproc has quirks (uint8 truncation of pulse times, `now` compared
with `is True`, the static switch-config write on the first rule, decode()
setting the machine type aux_command_output_primary() uses), they are kept:
a title that works here must work on a real P-ROC.

Runs on Python 2.7 and 3.x.  The FPGA's socket is $PROC_EMU_FPGA, else
/var/tmp/pad_proc/rig$PAD_SLOT/fpga.sock.  No socket = no P-ROC: PinPROC()
raises IOError exactly as pypinproc does when no board is plugged in.
"""
import collections
import errno
import os
import select
import socket
import sys
import time

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

# libpinproc internals (pinproc.h) the FPGA model shares - prochw.py imports
# these rather than keep a second copy.
P_ROC_INIT_PATTERN_A = 0x801F1122
P_ROC_INIT_PATTERN_B = 0x345678AB
P_ROC_CHIP_ID = 0xfeedbeef
P3_ROC_CHIP_ID = 0xf33db33f
P_ROC_VER_REV_FIXED_SWITCH_STATE_READS = 0x10013

P_ROC_READ, P_ROC_WRITE = 0, 1
P_ROC_REQUESTED_DATA, P_ROC_UNREQUESTED_DATA = 0, 1
P_ROC_COMMAND_SHIFT = 31
P_ROC_HEADER_LENGTH_SHIFT = 20
P_ROC_HEADER_LENGTH_MASK = 0x7FF00000
P_ROC_MODULE_SELECT_SHIFT = 16
P_ROC_MODULE_SELECT_MASK = 0x000F0000
P_ROC_REG_ADDR_MASK = 0x0000FFFF

P_ROC_MANAGER_SELECT = 0
P_ROC_BUS_JTAG_SELECT = 1
P_ROC_BUS_SWITCH_CTRL_SELECT = 2
P_ROC_BUS_DRIVER_CTRL_SELECT = 3
P_ROC_BUS_STATE_CHANGE_PROC_SELECT = 4
P_ROC_BUS_DMD_SELECT = 5
P3_ROC_BUS_AUX_CTRL_SELECT = 5

P_ROC_REG_CHIP_ID_ADDR = 0
P_ROC_REG_WATCHDOG_ADDR = 2
P_ROC_REG_DIPSWITCH_ADDR = 3

P_ROC_SWITCH_CTRL_STATE_BASE_ADDR = 4
P_ROC_SWITCH_CTRL_OLD_DEBOUNCE_BASE_ADDR = 11
P_ROC_SWITCH_CTRL_DEBOUNCE_BASE_ADDR = 12
P3_ROC_SWITCH_CTRL_STATE_BASE_ADDR = 16
P3_ROC_SWITCH_CTRL_DEBOUNCE_BASE_ADDR = 32

P_ROC_EVENT_TYPE_SWITCH = 0
P_ROC_EVENT_TYPE_DMD = 1
P_ROC_EVENT_TYPE_BURST_SWITCH = 2
P_ROC_EVENT_TYPE_ACCELEROMETER = 3

P_ROC_DRIVER_CTRL_DECODE_SHIFT = 10
P_ROC_DRIVER_CTRL_REG_DECODE = 0
P_ROC_DRIVER_CONFIG_TABLE_DECODE = 1
P_ROC_DRIVER_AUX_MEM_DECODE = 2
P_ROC_DRIVER_PDB_ADDR = 0xC00
P_ROC_DRIVER_PDB_WRITE_COMMAND = 0x01
P_ROC_STATE_CHANGE_CONFIG_ADDR = 0x1000
P_ROC_DMD_DOT_TABLE_BASE_ADDR = 0x1000

LED_REG_INDEX, LED_REG_COLOR, LED_REG_FADE_COLOR = 0, 1, 2
LED_REG_FADE_RATE_LOW, LED_REG_FADE_RATE_HIGH = 3, 4

kPRResetFlagDefault = 0
kPRResetFlagUpdateDevice = 1

FTDI_BUFFER_SIZE = 8192
MAX_WRITE_WORDS = 1536
NUM_SWITCH_RULES = 256 << 2

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


# ------------------------------------------------------------- word encoding
def create_reg_request_word(select, addr, num_words):
    return _u32((P_ROC_READ << 31) | (num_words << 20) | (select << 16) | addr)


def create_burst_command(select, addr, num_words):
    return _u32((P_ROC_WRITE << 31) | (num_words << 20) | (select << 16) | addr)


def driver_words(d):
    """CreateDriverUpdateBurst() data words for a driver state."""
    w1 = ((d["outputDriveTime"] << 0) | (d["polarity"] << 8) | (d["state"] << 9)
          | (1 << 10) | (d["waitForFirstTimeSlot"] << 11) | (d["timeslots"] << 16))
    w2 = ((d["timeslots"] >> 16) | (d["patterOnTime"] << 16) | (d["patterOffTime"] << 23)
          | (d["patterEnable"] << 30) | (d["futureEnable"] << 31))
    return _u32(w1), _u32(w2)


def switch_rule_index(switch_num, event_type):
    debounce = 1 if event_type in (EventTypeSwitchOpenDebounced, EventTypeSwitchClosedDebounced) else 0
    state = 1 if event_type in (EventTypeSwitchOpenDebounced, EventTypeSwitchOpenNondebounced) else 0
    return (debounce << 9) | (state << 8) | _u8(switch_num)


def parse_switch_rule_index(index):
    num = index & 0xff
    is_open = (index >> 8) & 1
    debounce = (index >> 9) & 1
    if is_open:
        return num, EventTypeSwitchOpenDebounced if debounce else EventTypeSwitchOpenNondebounced
    return num, EventTypeSwitchClosedDebounced if debounce else EventTypeSwitchClosedNondebounced


def words_to_bytes(words):
    out = bytearray()
    for w in words:
        w = _u32(w)
        out += bytearray(((w >> 24) & 0xff, (w >> 16) & 0xff, (w >> 8) & 0xff, w & 0xff))
    return bytes(out)


# -------------------------------------------------------------- the FTDI link
class SocketLink(object):
    """The FTDI chip: bytes to and from prochw.py's fpga.sock."""

    def __init__(self, path=None):
        if path is None:
            path = os.environ.get("PROC_EMU_FPGA") or \
                "/var/tmp/pad_proc/rig%s/fpga.sock" % os.environ.get("PAD_SLOT", "0")
        self.path = path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)

    def write(self, data):
        self.sock.sendall(data)
        return len(data)

    def read(self, max_bytes, timeout=0.0):
        r, _, _ = select.select([self.sock], [], [], timeout)
        if not r:
            return b""
        try:
            data = self.sock.recv(max_bytes)
        except socket.error as e:
            if e.args and e.args[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                return b""
            raise
        if not data:
            raise IOError("P-ROC link closed")
        return data

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# Tests swap this for an in-process link to prochw.Fpga.
link_factory = SocketLink


class PinPROCError(IOError):
    pass


# ------------------------------------------------------------ the libpinproc
class _Device(object):
    """PRDevice.cpp, method for method."""

    def __init__(self, machine_type):
        self.machine_type = machine_type
        self.link = None
        self.rx = bytearray()
        self.requested = collections.deque()
        self.unrequested = collections.deque()
        self.prepared = []
        self.chip_id = 0
        self.version = 0
        self.revision = 0
        self.combined_version_revision = 0
        self.read_machine_type = MachineTypeInvalid
        # new PRDevice: these arrays start zeroed (a fresh mmap'd heap block)
        self.drivers = [_driver_blank() for _ in range(DriverCount)]
        self.groups = [self._group_blank(i) for i in range(26)]
        self.globals = self._globals_blank()
        self.switch_rules = [self._rule_blank(i) for i in range(NUM_SWITCH_RULES)]
        self.free_rules = collections.deque()
        self.dmd_config = None
        self.reset(kPRResetFlagDefault)

    @staticmethod
    def _group_blank(n):
        return {"groupNum": n, "slowTime": 0, "enableIndex": 0, "rowActivateIndex": 0,
                "rowEnableSelect": 0, "matrixed": 0, "polarity": 0, "active": 0,
                "disableStrobeAfter": 0}

    @staticmethod
    def _globals_blank():
        return {"enableOutputs": 0, "globalPolarity": 0, "useClear": 0,
                "strobeStartSelect": 0, "startStrobeTime": 0, "matrixRowEnableIndex0": 0,
                "matrixRowEnableIndex1": 0, "activeLowMatrixRows": 0,
                "tickleSternWatchdog": 0, "encodeEnables": 0, "watchdogExpired": 0,
                "watchdogEnable": 0, "watchdogResetTime": 0}

    @staticmethod
    def _rule_blank(index):
        num, et = parse_switch_rule_index(index)
        return {"switchNum": num, "eventType": et, "reloadActive": 0, "notifyHost": 0,
                "changeOutput": 0, "linkActive": 0, "linkIndex": 0,
                "driver": _driver_blank()}

    # ---- open / close
    @classmethod
    def create(cls, machine_type):
        dev = cls(machine_type)
        if not dev.open():
            dev.close()
            return None
        rmt = dev.read_machine_type
        wpc = (MachineTypeWPC, MachineTypeWPC95, MachineTypeWPCAlphanumeric)
        if machine_type not in (MachineTypeCustom, MachineTypePDB) and (
                (machine_type in wpc and rmt not in wpc) or
                (machine_type not in wpc and rmt == MachineTypeWPC)):
            dev.close()
            _set_error("Machine type error.")
            return None
        return dev

    def open(self):
        try:
            self.link = link_factory()
        except (socket.error, OSError, IOError) as e:
            _set_error("Unable to open ftdi device: -3: device not found (%s)" % e)
            return False
        self.dmd_update_config(dict(numRows=32, numColumns=128, numSubFrames=4,
                                    numFrameBuffers=3, autoIncBufferWrPtr=0,
                                    enableFrameEvents=0))
        self.switch_update_config(dict(clear=0, use_column_9=0, use_column_8=0,
                                       hostEventsEnable=0, directMatrixScanLoopTime=2,
                                       pulsesBeforeCheckingRX=10, inactivePulsesAfterBurst=12,
                                       pulsesPerBurst=6, pulseHalfPeriodTime=13))
        self.flush_read_buffer()
        ok = self.verify_chip_id()
        tries = 0
        while not ok and tries < 5:
            tries += 1
            if tries == 1:
                self.write_data([P_ROC_INIT_PATTERN_A])
                self.write_data([P_ROC_INIT_PATTERN_B])
            self.flush_read_buffer()
            time.sleep(0.1)
            ok = self.verify_chip_id()
        return ok

    def close(self):
        if self.link is not None:
            self.link.close()
            self.link = None

    # ---- raw I/O
    def write_data(self, words):
        if not words:
            return True
        data = words_to_bytes(words)
        try:
            n = self.link.write(data)
        except (socket.error, OSError, IOError) as e:
            _set_error("Error in WriteData: %s" % e)
            return False
        if n != len(data):
            _set_error("Error in WriteData: wrote %d of %d bytes" % (n, len(data)))
            return False
        return True

    def prepare_write_data(self, words):
        if len(words) > MAX_WRITE_WORDS:
            _set_error("%d words Exceeds write capabilities.  Restrict write requests "
                       "to %d words." % (len(words), MAX_WRITE_WORDS))
            return False
        if len(self.prepared) + len(words) > MAX_WRITE_WORDS:
            if not self.flush_write_data():
                return False
        self.prepared.extend(_u32(w) for w in words)
        return True

    def flush_write_data(self):
        words, self.prepared = self.prepared, []
        return self.write_data(words)

    def request_data(self, select, addr, num_words):
        return self.write_data([create_reg_request_word(select, addr, num_words)])

    def collect_read_data(self, timeout=0.0):
        room = FTDI_BUFFER_SIZE - len(self.rx)
        if room <= 0:
            return 0
        try:
            data = self.link.read(room, timeout)
        except (socket.error, OSError, IOError):
            return -1
        self.rx += bytearray(data)
        return len(data)

    def flush_read_buffer(self):
        self.collect_read_data()
        del self.rx[:]
        return 0

    def _pop_word(self):
        b = self.rx[:4]
        del self.rx[:4]
        return (b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]

    def sort_returning_data(self, timeout=0.0):
        if self.collect_read_data(timeout) < 0:
            _set_error("Error in CollectReadData: -1")
            return False
        while len(self.rx) // 4 >= 2:
            w = self._pop_word()
            if (w >> P_ROC_COMMAND_SHIFT) & 1 == P_ROC_REQUESTED_DATA:
                self.requested.append(w)
                n = (w & P_ROC_HEADER_LENGTH_MASK) >> P_ROC_HEADER_LENGTH_SHIFT
                if n * 4 <= len(self.rx):       # ReadData(): all or nothing
                    for _ in range(n):
                        self.requested.append(self._pop_word())
            else:
                self.unrequested.append(self._pop_word())
        return True

    def _wait_requested(self, count):
        tries = 0
        while len(self.requested) < count and tries < 10:
            tries += 1
            # PRSleep(10) then SortReturningData(); waiting on the socket
            # instead of sleeping returns the moment the reply lands.
            if not self.sort_returning_data(0.010):
                return False
        return True

    def read_data_raw(self, select, addr, num_words):
        self.request_data(select, addr, num_words)
        if not self._wait_requested(num_words + 1):
            return None
        if len(self.requested) != num_words + 1:
            _set_error("Response length did not match.")
            return None
        self.requested.popleft()
        return [self.requested.popleft() for _ in range(num_words)]

    def verify_chip_id(self):
        self.request_data(P_ROC_MANAGER_SELECT, P_ROC_REG_CHIP_ID_ADDR, 4)
        if not self._wait_requested(5):
            return False
        if len(self.requested) < 5:
            _set_error("Verify Chip ID took too long to receive data")
            return False
        if len(self.requested) != 5:
            _set_error("Error reading Chip IP and Version. Read %d words instead of 5."
                       % len(self.requested))
            self.requested.clear()
            return False
        buf = [self.requested.popleft() for _ in range(5)]
        ok = buf[1] in (P_ROC_CHIP_ID, P3_ROC_CHIP_ID)
        if not ok:
            _set_error("Chip ID does not match.")
        self.chip_id = buf[1]
        self.revision = buf[2] & 0xffff
        self.version = buf[2] >> 16
        self.combined_version_revision = self.version * 0x10000 + self.revision
        # IsStern(): manual stern detect bit 0 == 0
        self.read_machine_type = MachineTypeSternWhitestar if (buf[4] & 1) == 0 else MachineTypeWPC
        return ok

    # ---- reset / defaults
    def reset(self, flags):
        del self.rx[:]
        self.requested.clear()
        self.unrequested.clear()
        self.prepared = []
        if self.machine_type not in (MachineTypeCustom, MachineTypePDB):
            self.load_machine_type_defaults(self.machine_type, flags)
        self.free_rules.clear()
        self.switch_rules = [self._rule_blank(i) for i in range(NUM_SWITCH_RULES)]
        for i, rule in enumerate(self.switch_rules):
            rule["driver"]["polarity"] = self.globals["globalPolarity"]
            if rule["switchNum"] >= SwitchNeverDebounceFirst and rule["eventType"] in (
                    EventTypeSwitchClosedDebounced, EventTypeSwitchOpenDebounced):
                self.free_rules.append(i)
        if flags & kPRResetFlagUpdateDevice:
            empty = {"notifyHost": 0, "reloadActive": 0}
            for i in range(256):
                for et in (EventTypeSwitchOpenDebounced, EventTypeSwitchClosedDebounced,
                           EventTypeSwitchOpenNondebounced, EventTypeSwitchClosedNondebounced):
                    self.switch_update_rule(i, et, empty, [], False)
        return True

    def load_machine_type_defaults(self, machine_type, flags=0):
        wpc = machine_type in (MachineTypeWPC, MachineTypeWPC95, MachineTypeWPCAlphanumeric)
        stern = machine_type in (MachineTypeSternWhitestar, MachineTypeSternSAM)
        if not (wpc or stern):
            return True
        if wpc:
            enable_idx = [0, 0, 0, 0, 0, 2, 4, 3, 1, 5, 7, 7, 7, 7, 7, 7, 7, 7, 8, 0, 0, 0, 0, 0, 0, 0]
            polarity = [0] * 18 + [1] + [0] * 7
            slow = [0] * 10 + [400] * 8 + [0] * 8
            activate = [0] * 11 + [1, 2, 3, 4, 5, 6, 7] + [0] * 8
            row1, row0, tickle, gpol, active_low, loop = 6, 6, 0, 0, 1, 4
            nmatrix, encode, last_coil = 8, 0, 9
        else:
            enable_idx = [0, 0, 0, 0, 1, 0, 2, 3, 0, 0, 8, 9, 8, 9, 8, 9, 8, 9, 8, 9, 8, 9, 8, 9, 8, 9]
            polarity = [1] * 26
            slow = [0] * 10 + [400] * 16
            activate = [0] * 12 + [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7]
            row1, row0, tickle, gpol, active_low, loop = 6, 10, 1, 1, 0, 1
            nmatrix, encode, last_coil = 16, 1, 7
        update = flags & kPRResetFlagUpdateDevice
        self.globals = self._globals_blank()
        for i in range(DriverCount):
            # C reads mappedDriverGroupPolarity[i/8] past its 26 groups for
            # drivers 208-255 (whatever the stack holds); take the last group.
            self.drivers[i] = _driver_blank(i, polarity[min(i // 8, 25)])
            if update:
                self.driver_update_state(dict(self.drivers[i]))
        for i in range(26):
            g = self._group_blank(i)
            g["polarity"] = polarity[i]
            self.groups[i] = g
        groups = list(range(4, last_coil + 1)) + list(range(10, 10 + nmatrix))
        if machine_type == MachineTypeWPC:
            groups.append(18)
        for i in groups:
            g = dict(self.groups[i])
            matrixed = i >= 10 and i < 10 + nmatrix
            g.update(slowTime=slow[i] if matrixed else 0, enableIndex=enable_idx[i],
                     rowActivateIndex=activate[i] if matrixed else 0, rowEnableSelect=0,
                     matrixed=int(matrixed), polarity=polarity[i], active=1,
                     disableStrobeAfter=int(matrixed and slow[i] != 0))
            if update:
                self.driver_update_group_config(g)
            else:
                self.groups[i] = g
        glob = dict(enableOutputs=0, globalPolarity=gpol, useClear=0, strobeStartSelect=0,
                    startStrobeTime=loop, matrixRowEnableIndex1=row1,
                    matrixRowEnableIndex0=row0, activeLowMatrixRows=active_low,
                    tickleSternWatchdog=tickle, encodeEnables=encode, watchdogExpired=0,
                    watchdogEnable=1, watchdogResetTime=1000)
        for enable in (0, 1):
            glob["enableOutputs"] = enable
            if update:
                self.driver_update_global_config(dict(glob))
            else:
                self.globals = dict(glob)
        self.manager_update_config(machine_type == MachineTypeWPCAlphanumeric, False)
        return True

    # ---- manager / drivers
    def manager_update_config(self, reuse_dmd_data_for_aux, invert_dipswitch_1):
        return self.prepare_write_data([
            create_burst_command(P_ROC_MANAGER_SELECT, P_ROC_REG_DIPSWITCH_ADDR, 1),
            (int(reuse_dmd_data_for_aux) << 10) | (int(invert_dipswitch_1) << 9)])

    def _watchdog_words(self, g):
        return [create_burst_command(P_ROC_MANAGER_SELECT, P_ROC_REG_WATCHDOG_ADDR, 1),
                _u32((g["watchdogExpired"] << 30) | (g["watchdogEnable"] << 14)
                     | (_u16(g["watchdogResetTime"]) << 0))]

    def driver_update_global_config(self, g):
        self.globals = dict(g)
        w = _u32((g["enableOutputs"] << 31) | (g["globalPolarity"] << 30)
                 | (g["useClear"] << 28) | (g["strobeStartSelect"] << 27)
                 | (_u8(g["startStrobeTime"]) << 20)
                 | (_u8(g["matrixRowEnableIndex1"]) << 16)
                 | (_u8(g["matrixRowEnableIndex0"]) << 12)
                 | (g["activeLowMatrixRows"] << 11) | (g["encodeEnables"] << 10)
                 | (g["tickleSternWatchdog"] << 9))
        return self.prepare_write_data(
            [create_burst_command(P_ROC_BUS_DRIVER_CTRL_SELECT, 0, 1), w]
            + self._watchdog_words(g))

    def driver_update_group_config(self, g):
        n = _u8(g["groupNum"])
        self.groups[n % 26] = dict(g)
        w = _u32((_u16(g["slowTime"]) << 12) | (g["disableStrobeAfter"] << 11)
                 | (_u8(g["enableIndex"]) << 7) | (_u8(g["rowActivateIndex"]) << 4)
                 | (_u8(g["rowEnableSelect"]) << 3) | (g["matrixed"] << 2)
                 | (g["polarity"] << 1) | (g["active"] << 0))
        return self.prepare_write_data(
            [create_burst_command(P_ROC_BUS_DRIVER_CTRL_SELECT, n, 1), w])

    def driver_update_state(self, d):
        num = d["driverNum"] & 0xff
        if d["polarity"] != self.drivers[num]["polarity"] and \
                self.machine_type not in (MachineTypeCustom, MachineTypePDB):
            _set_error("Refusing to update driver #%d; polarity differs on non-custom machine."
                       % d["driverNum"])
            return False
        self.drivers[num] = dict(d)
        w1, w2 = driver_words(d)
        addr = (P_ROC_DRIVER_CONFIG_TABLE_DECODE << P_ROC_DRIVER_CTRL_DECODE_SHIFT) | (d["driverNum"] << 1)
        return self.prepare_write_data(
            [create_burst_command(P_ROC_BUS_DRIVER_CTRL_SELECT, addr, 2), w1, w2])

    def driver_get_state(self, num):
        return dict(self.drivers[num & 0xff])

    def driver_aux_send_commands(self, commands, starting_addr):
        n = _u8(len(commands))
        if self.chip_id == P_ROC_CHIP_ID:
            addr = (P_ROC_DRIVER_AUX_MEM_DECODE << P_ROC_DRIVER_CTRL_DECODE_SHIFT) | _u8(starting_addr)
            words = [create_burst_command(P_ROC_BUS_DRIVER_CTRL_SELECT, addr, n)]
        else:
            words = [create_burst_command(P3_ROC_BUS_AUX_CTRL_SELECT, 0, n)]
        for c in commands[:n]:
            words.append(_aux_word(c))
        return self.prepare_write_data(words)

    def driver_watchdog_tickle(self):
        return self.prepare_write_data(self._watchdog_words(self.globals))

    # ---- switches
    def switch_update_config(self, c):
        return self.prepare_write_data([
            create_burst_command(P_ROC_BUS_SWITCH_CTRL_SELECT, 0, 1),
            _u32((c["clear"] << 31) | (_u8(c["directMatrixScanLoopTime"]) << 24)
                 | (_u8(c["pulsesBeforeCheckingRX"]) << 18)
                 | (_u8(c["inactivePulsesAfterBurst"]) << 12)
                 | (_u8(c["pulsesPerBurst"]) << 6) | (_u8(c["pulseHalfPeriodTime"]) << 0)
                 | (c["use_column_8"] << 29) | (c["use_column_9"] << 30)),
            create_burst_command(P_ROC_BUS_STATE_CHANGE_PROC_SELECT,
                                 P_ROC_STATE_CHANGE_CONFIG_ADDR, 1),
            _u32(c["hostEventsEnable"])])

    def _rule_words(self, rule, drive_outputs_now):
        addr = (switch_rule_index(rule["switchNum"], rule["eventType"]) << 2) | \
            (int(drive_outputs_now) << 13)
        w1, w2 = driver_words(rule["driver"])
        w3 = _u32((rule["changeOutput"] << 9) | (rule["driver"]["driverNum"] << 0)
                  | (rule["linkActive"] << 10) | (rule["linkIndex"] << 11)
                  | (rule["notifyHost"] << 23) | (rule["reloadActive"] << 31))
        return [create_burst_command(P_ROC_BUS_STATE_CHANGE_PROC_SELECT, addr, 3), w1, w2, w3]

    def switch_update_rule(self, switch_num, event_type, rule, drivers, drive_outputs_now):
        n = len(drivers)
        if n > 0 and len(self.free_rules) < n - 1:
            _set_error("Not enough free switch rule indexes: %d available, need %d"
                       % (len(self.free_rules), n))
            return False
        new_index = switch_rule_index(switch_num, event_type)
        old = self.switch_rules[new_index]
        while old["linkActive"]:
            link = old["linkIndex"]
            old = self.switch_rules[link]
            self.free_rules.append(link)
            if len(self.free_rules) > 128:
                _set_error("Too many free switch rule indicies!")
                return False
        if n > 0:
            saved = None
            for k in range(n - 1, -1, -1):
                d = drivers[k]
                if k > 0:
                    idx = self.free_rules.popleft()
                    r = self.switch_rules[idx]
                    r["driver"] = dict(d)
                    r["changeOutput"] = 1
                    if k == n - 1:
                        r["linkActive"] = 0
                    else:
                        r["linkActive"], r["linkIndex"] = 1, saved
                    saved = idx
                    words = self._rule_words(r, False)
                else:
                    r = self.switch_rules[new_index]
                    r["notifyHost"] = _i32(rule["notifyHost"])
                    r["reloadActive"] = _i32(rule["reloadActive"])
                    r["changeOutput"] = 1
                    r["driver"] = dict(d)
                    if n > 1:
                        r["linkActive"], r["linkIndex"] = 1, saved
                    else:
                        r["linkActive"] = 0
                    words = self._rule_words(r, drive_outputs_now)
                if not self.prepare_write_data(words):
                    r = self.switch_rules[new_index]
                    r["changeOutput"] = r["linkActive"] = 0
                    self.prepare_write_data(self._rule_words(r, False))
                    return False
            return True
        r = self.switch_rules[new_index]
        r["notifyHost"] = _i32(rule["notifyHost"])
        r["reloadActive"] = _i32(rule["reloadActive"])
        r["changeOutput"] = r["linkActive"] = 0
        return self.prepare_write_data(self._rule_words(r, False))

    def switch_get_states(self, num_switches=256):
        banks = num_switches // 32
        for i in range(banks):
            if self.chip_id == P_ROC_CHIP_ID:
                self.request_data(P_ROC_BUS_SWITCH_CTRL_SELECT, P_ROC_SWITCH_CTRL_STATE_BASE_ADDR + i, 1)
                base = P_ROC_SWITCH_CTRL_OLD_DEBOUNCE_BASE_ADDR \
                    if self.combined_version_revision < P_ROC_VER_REV_FIXED_SWITCH_STATE_READS \
                    else P_ROC_SWITCH_CTRL_DEBOUNCE_BASE_ADDR
                self.request_data(P_ROC_BUS_SWITCH_CTRL_SELECT, base + i, 1)
            else:
                self.request_data(P_ROC_BUS_SWITCH_CTRL_SELECT, P3_ROC_SWITCH_CTRL_STATE_BASE_ADDR + i, 1)
                self.request_data(P_ROC_BUS_SWITCH_CTRL_SELECT, P3_ROC_SWITCH_CTRL_DEBOUNCE_BASE_ADDR + i, 1)
        need = 4 * banks
        if not self._wait_requested(need):
            return None
        if len(self.requested) != need:
            _set_error("Switch response length does not match.")
            return None
        states = []
        for i in range(banks):
            self.requested.popleft()
            state = self.requested.popleft()
            self.requested.popleft()
            debounce = self.requested.popleft()
            for j in range(32):
                if (state >> j) & 1:
                    et = EventTypeSwitchOpenDebounced if (debounce >> j) & 1 else EventTypeSwitchOpenNondebounced
                else:
                    et = EventTypeSwitchClosedDebounced if (debounce >> j) & 1 else EventTypeSwitchClosedNondebounced
                states.append(et)
        return states

    # ---- events
    def get_events(self, max_events=2048):
        if not self.sort_returning_data():
            _set_error("GetEvents ERROR: Error in CollectReadData")
            return None
        events = []
        v2 = self.version >= 2
        while self.unrequested and len(events) < max_events:
            w = self.unrequested.popleft()
            if v2:
                value, typ = w & 0x7FF, (w & 0xC000) >> 14
                is_open, debounced = (w & 0x1000) >> 12, (w & 0x2000) >> 13
                t = (w & 0xFFFF0000) >> 16
            else:
                typ, value = (w & 0xC00) >> 10, w & 0xFF
                is_open, debounced = (w & 0x100) >> 8, (w & 0x200) >> 9
                t = (w & 0xFFFFF000) >> 12
            if typ == P_ROC_EVENT_TYPE_SWITCH:
                if is_open:
                    et = EventTypeSwitchOpenDebounced if debounced else EventTypeSwitchOpenNondebounced
                else:
                    et = EventTypeSwitchClosedDebounced if debounced else EventTypeSwitchClosedNondebounced
            elif typ == P_ROC_EVENT_TYPE_DMD:
                et = EventTypeDMDFrameDisplayed
            elif typ == P_ROC_EVENT_TYPE_BURST_SWITCH:
                et = EventTypeBurstSwitchOpen if is_open else EventTypeBurstSwitchClosed
            else:
                t >>= 2
                value = w & 0x3FFF
                et = (EventTypeAccelerometerX, EventTypeAccelerometerY,
                      EventTypeAccelerometerZ, EventTypeAccelerometerIRQ)[(w & 0x30000) >> 16]
            events.append({"type": et, "value": value, "time": t})
        return events

    # ---- DMD
    def dmd_update_config(self, c):
        self.dmd_config = dict(c)
        words = [create_burst_command(P_ROC_BUS_DMD_SELECT, 0, 1),
                 _u32((1 << 31) | (c.get("enableFrameEvents", 0) << 30)
                      | (c.get("autoIncBufferWrPtr", 0) << 29)
                      | (_u8(c.get("numFrameBuffers", 0)) << 24)
                      | (_u8(c.get("numSubFrames", 0)) << 16)
                      | (_u8(c.get("numRows", 0)) << 8)
                      | (_u16(c.get("numColumns", 0)) << 0)),
                 create_burst_command(P_ROC_BUS_DMD_SELECT, 8, 4)]
        for i in range(4):
            words.append(_u32((_u8(c.get("rclkLowCycles", [0] * 4)[i]) << 24)
                              | (_u8(c.get("latchHighCycles", [0] * 4)[i]) << 16)
                              | (_u16(c.get("deHighCycles", [0] * 4)[i]) << 6)
                              | (_u8(c.get("dotclkHalfPeriod", [0] * 4)[i]) << 0)))
        return self.prepare_write_data(words)

    def dmd_draw(self, dots):
        c = self.dmd_config
        per_sub = (c["numColumns"] * c["numRows"]) // 32
        n = per_sub * c["numSubFrames"]
        words = [create_burst_command(P_ROC_BUS_DMD_SELECT, P_ROC_DMD_DOT_TABLE_BASE_ADDR, n)]
        for k in range(n):      # (uint32_t *)dots on little-endian x86
            words.append(dots[4 * k] | (dots[4 * k + 1] << 8) | (dots[4 * k + 2] << 16)
                         | (dots[4 * k + 3] << 24))
        return self.prepare_write_data(words)

    # ---- PD-LED boards
    def _pdb_words(self, board, reg, value):
        return [create_burst_command(P_ROC_BUS_DRIVER_CTRL_SELECT, P_ROC_DRIVER_PDB_ADDR, 1),
                _u32((P_ROC_DRIVER_PDB_WRITE_COMMAND << 24) | (_u8(board) << 16)
                     | (reg << 8) | _u8(value))]

    def led_color(self, board, index, color):
        self.prepare_write_data(self._pdb_words(board, LED_REG_INDEX, index))
        return self.prepare_write_data(self._pdb_words(board, LED_REG_COLOR, color))

    def led_fade(self, board, index, fade_color, fade_rate):
        fade_rate = _u16(fade_rate)
        self.prepare_write_data(self._pdb_words(board, LED_REG_FADE_RATE_LOW, fade_rate & 0xff))
        self.prepare_write_data(self._pdb_words(board, LED_REG_FADE_RATE_HIGH, fade_rate >> 8))
        self.prepare_write_data(self._pdb_words(board, LED_REG_INDEX, index))
        return self.prepare_write_data(self._pdb_words(board, LED_REG_FADE_COLOR, fade_color))

    def led_fade_color(self, board, index, fade_color):
        self.prepare_write_data(self._pdb_words(board, LED_REG_INDEX, index))
        return self.prepare_write_data(self._pdb_words(board, LED_REG_FADE_COLOR, fade_color))

    def led_fade_rate(self, board, fade_rate):
        fade_rate = _u16(fade_rate)
        self.prepare_write_data(self._pdb_words(board, LED_REG_FADE_RATE_LOW, fade_rate & 0xff))
        return self.prepare_write_data(self._pdb_words(board, LED_REG_FADE_RATE_HIGH, fade_rate >> 8))


def _aux_word(c):
    c = dict((k, int(c[k])) for k in AUX_KEYS)
    if c["command"] == AUX_CMD_OUTPUT:
        return _u32(((c["active"] & 1) << 31) | ((c["delayTime"] & 0x7ff) << 20)
                    | ((c["muxEnables"] & 1) << 19) | ((c["command"] & 3) << 16)
                    | ((c["enables"] & 0xF) << 12) | ((c["extraData"] & 0xF) << 8)
                    | ((c["data"] & 0xFF) << 0))
    if c["command"] == AUX_CMD_DELAY:
        return _u32((c["active"] << 31) | ((c["command"] & 3) << 16)
                    | ((c["delayTime"] & 0x3FFF) << 0))
    if c["command"] == AUX_CMD_JUMP:
        return _u32((c["active"] << 31) | ((c["command"] & 3) << 16)
                    | ((c["jumpAddr"] & 0xFF) << 0))
    return 0


_last_error = [""]


def _set_error(text):
    _last_error[0] = text
    if os.environ.get("PROC_EMU_QUIET") != "1":
        sys.stderr.write(text + "\n")


# ------------------------------------------------------------------- PinPROC
def _truthy_py(v):
    """pypinproc compares its PyObject flags with Py_True."""
    return 1 if v is True else 0


_DMD_COLUMNS, _DMD_ROWS = 128, 32


def _dmd_defaults():
    return dict(enableFrameEvents=1, numRows=_DMD_ROWS, numColumns=_DMD_COLUMNS,
                numSubFrames=4, numFrameBuffers=3, autoIncBufferWrPtr=1,
                rclkLowCycles=[15] * 4, latchHighCycles=[15] * 4,
                dotclkHalfPeriod=[1] * 4, deHighCycles=[90, 190, 50, 377])


class PinPROC(object):
    """pinproc.PinPROC: a P-ROC / P3-ROC board."""

    def __init__(self, machine_type):
        self.machine_type = normalize_machine_type(machine_type)
        if self.machine_type == MachineTypeInvalid:
            raise ValueError("Unknown machine type.  Expecting wpc, wpc95, sternSAM, "
                             "sternWhitestar, or custom.")
        self._dev = _Device.create(self.machine_type)
        if self._dev is None:
            raise IOError(_last_error[0])
        self._dmd_configured = False
        self._dmd_mapping = list(range(16))

    def __del__(self):
        dev = getattr(self, "_dev", None)
        if dev is not None:
            dev.close()

    def _ok(self, res, message):
        if not res:
            raise IOError(message)

    def reset(self, flags):
        self._ok(self._dev.reset(int(flags)), _last_error[0])

    def driver_update_global_config(self, enable_outputs, global_polarity, use_clear,
                                    strobe_start_select, start_strobe_time,
                                    matrix_row_enable_index_0, matrix_row_enable_index_1,
                                    active_low_matrix_rows, tickle_stern_watchdog,
                                    encode_enables, watchdog_expired, watchdog_enable,
                                    watchdog_reset_time):
        g = dict(enableOutputs=_truthy_py(enable_outputs),
                 globalPolarity=_truthy_py(global_polarity), useClear=_truthy_py(use_clear),
                 strobeStartSelect=_truthy_py(strobe_start_select),
                 startStrobeTime=_u8(start_strobe_time),
                 matrixRowEnableIndex0=_u8(matrix_row_enable_index_0),
                 matrixRowEnableIndex1=_u8(matrix_row_enable_index_1),
                 activeLowMatrixRows=_truthy_py(active_low_matrix_rows),
                 tickleSternWatchdog=_truthy_py(tickle_stern_watchdog),
                 encodeEnables=_truthy_py(encode_enables),
                 watchdogExpired=_truthy_py(watchdog_expired),
                 watchdogEnable=_truthy_py(watchdog_enable),
                 watchdogResetTime=_u16(watchdog_reset_time))
        self._ok(self._dev.driver_update_global_config(g), "Error configuring driver globals")

    def driver_update_group_config(self, group_num, slow_time, enable_index,
                                   row_activate_index, row_enable_select, matrixed,
                                   polarity, active, disable_strobe_after):
        g = dict(groupNum=_u8(group_num), slowTime=_u16(slow_time),
                 enableIndex=_u8(enable_index), rowActivateIndex=_u8(row_activate_index),
                 rowEnableSelect=_u8(row_enable_select), matrixed=_truthy_py(matrixed),
                 polarity=_truthy_py(polarity), active=_truthy_py(active),
                 disableStrobeAfter=_truthy_py(disable_strobe_after))
        self._ok(self._dev.driver_update_group_config(g), "Error configuring driver group")

    def driver_group_disable(self, number):
        g = dict(self._dev.groups[_u8(number) % 26])
        g["active"] = 0
        self._ok(self._dev.driver_update_group_config(g), "Error disabling driver group")

    def _driver_op(self, number, fn, message, *args):
        d = self._dev.driver_get_state(_u8(number))
        fn(d, *args)
        self._ok(self._dev.driver_update_state(d), message)

    def driver_pulse(self, number, milliseconds):
        self._driver_op(number, _state_pulse, "Error pulsing driver", milliseconds)

    def driver_future_pulse(self, number, milliseconds, future_time):
        self._driver_op(number, _state_future_pulse, "Error requesting driver future pulse.",
                        milliseconds, future_time)

    def driver_schedule(self, number, schedule, cycle_seconds, now):
        self._driver_op(number, _state_schedule, "Error scheduling driver",
                        schedule, _u8(cycle_seconds), now is True)

    def driver_patter(self, number, milliseconds_on, milliseconds_off, original_on_time, now):
        self._driver_op(number, _state_patter, "Error pattering driver",
                        milliseconds_on, milliseconds_off, original_on_time, now is True)

    def driver_pulsed_patter(self, number, milliseconds_on, milliseconds_off,
                             milliseconds_overall_patter_time, now):
        self._driver_op(number, _state_pulsed_patter, "Error pulse-pattering driver",
                        milliseconds_on, milliseconds_off, milliseconds_overall_patter_time,
                        now is True)

    def driver_disable(self, number):
        self._driver_op(number, _state_disable, "Error disabling driver")

    def driver_get_state(self, number):
        return _to_py(self._dev.driver_get_state(_u8(number)))

    def driver_update_state(self, number):
        # (sic) pypinproc's keyword for the state dict is "number"
        self._ok(self._dev.driver_update_state(_driver_from_dict(number)),
                 "Error getting driver state")

    def flush(self):
        self._ok(self._dev.flush_write_data(), _last_error[0])

    def switch_get_states(self):
        states = self._dev.switch_get_states(SwitchCount + 1)
        if states is None:
            raise IOError("Error getting driver state")
        return states

    def switch_update_rule(self, number, event_type, rule, linked_drivers=None,
                           drive_outputs_now=False):
        global _g_switch_config_sent
        et = {"closed_debounced": EventTypeSwitchClosedDebounced,
              "open_debounced": EventTypeSwitchOpenDebounced,
              "closed_nondebounced": EventTypeSwitchClosedNondebounced,
              "open_nondebounced": EventTypeSwitchOpenNondebounced}.get(event_type)
        if et is None:
            raise ValueError("event_type is unrecognized; valid values are "
                             "<closed|open>_[non]debounced")
        rule = {"notifyHost": _i32(rule["notifyHost"]), "reloadActive": _i32(rule["reloadActive"])}
        drivers = [_driver_from_dict(d) for d in (linked_drivers or [])]
        if not _g_switch_config_sent:
            _g_switch_config_sent = True
            self._dev.switch_update_config(dict(
                clear=0, use_column_8=int(_g_machine_type == MachineTypeWPC), use_column_9=0,
                hostEventsEnable=1, directMatrixScanLoopTime=2, pulsesBeforeCheckingRX=10,
                inactivePulsesAfterBurst=12, pulsesPerBurst=6, pulseHalfPeriodTime=13))
        self._ok(self._dev.switch_update_rule(_u8(number), et, rule, drivers,
                                              drive_outputs_now is True), _last_error[0])

    def aux_send_commands(self, address, aux_commands):
        sys.stderr.write("\n\nSending Aux Commands: numCommands:%d, addr:%d\n\n"
                         % (len(aux_commands), address))
        self._ok(self._dev.driver_aux_send_commands(list(aux_commands), address), _last_error[0])

    def write_data(self, module, address, data):
        if not self._dev.flush_write_data():
            raise IOError(_last_error[0])
        self._ok(self._dev.write_data([create_burst_command(int(module), int(address), 1),
                                       _u32(data)]), _last_error[0])

    def write_i2c_data(self, address, data):
        # Not in upstream pypinproc: American Pinball's own build (the Aimtron
        # motherboard's) adds it for the PCA9685 RGB LED chips on the P3-ROC's
        # I2C bus (procgame/game/rgb_led.py, BBQ on).  It is write_data(7,
        # address, data) BUFFERED - queued with the other prepared writes and
        # sent on the next flush, where write_data flushes and sends at once.
        self._ok(self._dev.prepare_write_data([create_burst_command(7, int(address), 1),
                                               _u32(data)]), _last_error[0])

    def watchdog_tickle(self):
        self._dev.driver_watchdog_tickle()

    def get_events(self):
        events = self._dev.get_events()
        if events is None:
            raise IOError(_last_error[0])
        return events

    def led_fade_rate(self, board_addr, fade_rate):
        self._ok(self._dev.led_fade_rate(board_addr, fade_rate), "Error setting LED fade rate")

    def led_color(self, board_addr, led_index, color):
        self._ok(self._dev.led_color(board_addr, led_index, color), "Error setting LED color")

    def led_fade(self, board_addr, led_index, color, fade_rate):
        self._ok(self._dev.led_fade(board_addr, led_index, color, fade_rate),
                 "Error setting LED fade")

    def led_fade_color(self, board_addr, led_index, color):
        self._ok(self._dev.led_fade_color(board_addr, led_index, color),
                 "Error setting LED fade color")

    def dmd_update_config(self, high_cycles=None):
        c = _dmd_defaults()
        if high_cycles is not None:
            if len(high_cycles) != 4:
                raise ValueError("len(high_cycles) must be 4")
            for i, v in enumerate(high_cycles):
                if not isinstance(v, _int_types):
                    raise ValueError("high_cycles members must be integers")
                c["deHighCycles"][i] = _u16(v)
                sys.stderr.write("dmdConfig.deHighCycles[%d] = %d\n" % (i, c["deHighCycles"][i]))
        self._dev.dmd_update_config(c)
        self._dmd_configured = True

    def set_dmd_color_mapping(self, mapping):
        if len(mapping) != 16:
            raise ValueError("len(mapping) incorrect")
        for i, v in enumerate(mapping):
            if not isinstance(v, _int_types):
                raise ValueError("mapping members must be integers")
            self._dmd_mapping[i] = _u8(v)
            sys.stderr.write("dmdMapping[%d] = %d\n" % (i, self._dmd_mapping[i]))

    def dmd_draw(self, dots):
        if not self._dmd_configured:
            self._ok(self._dev.dmd_update_config(_dmd_defaults()), _last_error[0])
            self._dmd_configured = True
        if not isinstance(dots, DMDBuffer):
            raise ValueError("Expected DMDBuffer or string.")
        if dots._w != _DMD_COLUMNS or dots._h != _DMD_ROWS:
            raise ValueError("Buffer dimensions are incorrect")
        packed = _proc_subframes(dots, self._dmd_mapping)
        self._ok(self._dev.dmd_draw(packed), _last_error[0])


# ------------------------------------------------------------------ DMDBuffer
_PROC_COLOR_MAP = (0, 2, 8, 10, 1, 3, 9, 11, 4, 6, 12, 14, 5, 7, 13, 15)
_alpha_map = None


def _get_alpha_map():
    """dmd.c DMDGetAlphaMap(), with its char truncation."""
    global _alpha_map
    if _alpha_map is None:
        m = bytearray(256 * 256)
        for src in range(256):
            sd, sa = src & 0xf, src >> 4
            for dst in range(256):
                dd, da = dst & 0xf, dst >> 4
                a = int(sa + da * ((15.0 - sa) / 15.0))
                if a == 0:
                    dot = 0
                else:
                    dot = int((sd * (sa / 15.0) + dd * (da / 15.0) * ((15.0 - sa) / 15.0))
                              / (a / 15.0))
                m[src * 256 + dst] = ((a << 4) | (dot & 0xf)) & 0xff
        _alpha_map = m
    return _alpha_map


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

    def copy_to_rect(self, dst, dst_x, dst_y, src_x, src_y, width, height, op=None):
        modes = ("copy", "add", "sub", "blacksrc", "alpha", "alphaboth")
        if op is None:
            op = "copy"
        if op not in modes:
            raise ValueError("Operation type not recognized.")
        src = self
        sx, sy, sw, sh = _rect_intersection((0, 0, src._w, src._h), (src_x, src_y, width, height))
        dx, dy, dw, dh = _rect_intersection((0, 0, dst._w, dst._h), (dst_x, dst_y, sw, sh))
        if dst_x < 0:
            sx, sw = sx - dst_x, sw + dst_x
        if dst_y < 0:
            sy, sh = sy - dst_y, sh + dst_y
        if sw == 0 or sh == 0:
            return
        amap = _get_alpha_map() if op in ("alpha", "alphaboth") else None
        sb, db = src._buf, dst._buf
        for row in range(dh):
            s0 = (sy + row) * src._w + sx
            d0 = (dy + row) * dst._w + dx
            if op == "copy":
                db[d0:d0 + dw] = sb[s0:s0 + dw]
                continue
            for k in range(dw):
                s, d = sb[s0 + k], db[d0 + k]
                if op == "add":
                    db[d0 + k] = min(d + s, 0xF)
                elif op == "sub":
                    db[d0 + k] = max(d - s, 0)
                elif op == "blacksrc":
                    if s & 0xf:
                        db[d0 + k] = (d & 0xf0) | (s & 0xf)
                elif op == "alpha":
                    v = amap[s * 256 + (d | 0xf0)]
                    db[d0 + k] = (d & 0xf0) | (v & 0x0f)
                else:
                    db[d0 + k] = amap[s * 256 + d]


def _proc_subframes(frame, color_map):
    """dmd.c DMDFrameCopyPROCSubframes() for a 128x32 frame, 4 sub-frames."""
    w, h = frame._w, frame._h
    dots = bytearray(4 * w * h // 8)
    sub = w * h // 8
    for row in range(h):
        for col in range(w):
            dot = frame._buf[row * w + col]
            if dot == 0:
                continue
            dot = _PROC_COLOR_MAP[color_map[dot & 0x0f] & 0x0f]
            byte, bit = (row * w + col) // 8, 1 << (col % 8)
            for s in range(4):
                if dot & (1 << s):
                    dots[s * sub + byte] |= bit
    return dots
