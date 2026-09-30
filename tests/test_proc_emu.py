"""tools/proc_emu (PAD-262): the shared fake P-ROC - pystub/pinproc.py (the
pypinproc + libpinproc port) against prochw.py (the FPGA), in one process.

The golden values here were printed by the REAL libpinproc + pypinproc on
fakeftdi (selftest/run.sh, probe.py): where the stub and the real stack must
agree to the bit, the real one is the reference.  The WSL half of the proof
(both Pythons, the real stack, a native libpinproc program, pyprocgame
booting to attract) is selftest/run.sh; this file is what runs anywhere.
"""

import importlib.util
import json
import pathlib
import sys

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "proc_emu"
YAML = RIG / "selftest" / "machine.yaml"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pinproc = _load("pinproc", RIG / "pystub" / "pinproc.py")
prochw = _load("prochw", RIG / "prochw.py")


@pytest.fixture(autouse=True)
def _fresh_module_state(monkeypatch):
    # pypinproc's two process-wide statics (decode's machine type, the
    # first-rule switch config) must not leak between tests.
    monkeypatch.setattr(pinproc, "_g_machine_type", pinproc.MachineTypeInvalid)
    monkeypatch.setattr(pinproc, "_g_switch_config_sent", False)
    monkeypatch.setenv("PROC_EMU_QUIET", "1")


def board(yaml=YAML, chip="p3roc", **kw):
    machine = prochw.Machine(str(yaml) if yaml else None)
    return prochw.Fpga(chip, machine, machine.initial_closed(**kw))


def attach(monkeypatch, fpga, machine_type="pdb"):
    monkeypatch.setattr(pinproc, "link_factory", lambda: prochw.InProcessLink(fpga))
    return pinproc.PinPROC(machine_type)


NOTIFY = {"notifyHost": True, "reloadActive": False}
QUIET = {"notifyHost": False, "reloadActive": False}


def blank(num, polarity=True):
    return {"driverNum": num, "outputDriveTime": 0, "polarity": polarity, "state": False,
            "waitForFirstTimeSlot": False, "timeslots": 0, "patterOnTime": 0,
            "patterOffTime": 0, "patterEnable": False, "futureEnable": False}


# ------------------------------------------------------------ module level
DECODE_INPUTS = ["S11", "S88", "SD1", "SF4", "SD12", "C01", "C28", "C33", "C40", "C45",
                 "L11", "L88", "L01", "L64", "G05", "FLRM", "FLRH", "FULM", "FURH", "flrm",
                 "42", "S01", "S16", "S17", "S64", "SD0"]
# Printed by the real libpinproc PRDecode() through pypinproc.
DECODE_GOLDEN = {
    "wpc": [32, 151, 8, 3, 8, 40, 67, 36, 147, 153, 80, 143, 72, 123, 76, 32, 33, 38, 37,
            32, 42, 16, 37, 38, 115, 7],
    "wpc95": [32, 151, 8, 3, 8, 40, 67, 36, 71, 153, 80, 143, 72, 123, 76, 32, 33, 38, 37,
              32, 42, 16, 37, 38, 115, 7],
    "sternSAM": [42, 112, 8, 255, 19, 32, 59, 64, 71, 76, 161, 90, 192, 87, 0, 0, 0, 0, 0,
                 0, 42, 39, 47, 55, 95, 7],
    "sternWhitestar": [53, 192, 8, 464, 19, 32, 59, 64, 71, 76, 161, 90, 192, 87, 0, 0, 0,
                       0, 0, 0, 42, 39, 48, 71, 144, 7],
    "pdb": [0] * 20 + [42, 0, 0, 0, 0, 0],
}


@pytest.mark.parametrize("machine", sorted(DECODE_GOLDEN))
def test_decode_matches_real_libpinproc(machine):
    assert [pinproc.decode(machine, s) for s in DECODE_INPUTS] == DECODE_GOLDEN[machine]


def test_machine_type_names_and_integers():
    assert pinproc.normalize_machine_type("pdb") == pinproc.MachineTypePDB == 7
    assert pinproc.normalize_machine_type("sternWhitestar") == 5
    assert pinproc.normalize_machine_type(3) == 3
    assert pinproc.normalize_machine_type("nonsense") == pinproc.MachineTypeInvalid
    with pytest.raises(ValueError):
        pinproc.PinPROC("nonsense")


def test_driver_state_helpers_keep_the_c_widths():
    # Real pypinproc: a 300 ms pulse is a uint8 (44), a schedule comes back as
    # a C int (negative), `now` only counts when it IS True.
    assert pinproc.driver_state_pulse(blank(7), 300)["outputDriveTime"] == 44
    assert pinproc.driver_state_schedule(blank(7), 0xff00ff00, 2, True)["timeslots"] == -16711936
    assert pinproc.driver_state_patter(blank(7), 2, 18, 30, True)["waitForFirstTimeSlot"] == 0
    assert pinproc.driver_state_patter(blank(7), 2, 18, 30, 1)["waitForFirstTimeSlot"] == 1
    pp = pinproc.driver_state_pulsed_patter(blank(7), 5, 5, 400, False)
    assert (pp["state"], pp["outputDriveTime"], pp["patterEnable"]) == (0, 144, 1)


def test_aux_commands():
    a = pinproc.aux_command_output_custom(0x1ff, 3, 9, True, 100)
    assert (a["data"], a["extraData"], a["enables"], a["muxEnables"], a["command"]) == (255, 3, 9, 1, 2)
    assert pinproc.aux_command_jump(7)["jumpAddr"] == 7
    assert pinproc.aux_command_disable()["active"] == 0


# -------------------------------------------------------- the machine yaml
def test_trough_optos_hold_the_balls_and_nc_rests_closed():
    m = prochw.Machine(str(YAML))
    assert m.machine_type == pinproc.MachineTypePDB and m.num_balls == 3
    assert m.trough() == [72, 73, 74, 75]
    closed = m.initial_closed()
    # NC opto with a ball = interrupted = open; the empty 4th = closed.
    assert {72, 73, 74}.isdisjoint(closed) and 75 in closed
    assert 9 in closed                      # coin door (NC) at rest: closed
    assert 8 not in closed                  # start button (NO) at rest: open


def test_a_bigger_trough_than_balls_leaves_the_top_empty(tmp_path):
    y = tmp_path / "m.yaml"
    y.write_text("PRGame: {machineType: pdb, numBalls: 2}\nPRSwitches:\n"
                 + "".join("  trough%d: {number: SD%d, type: NC}\n" % (i, 70 + i) for i in (1, 2, 3))
                 + "  shooter: {number: SD79}\n")
    m = prochw.Machine(str(y))
    assert m.initial_closed() == {73}
    assert m.initial_closed(balls=0) == {71, 72, 73}
    assert m.initial_closed(active=[79]) == {73, 79}


def test_switch_names_numbers_and_addresses_resolve():
    m = prochw.Machine(str(YAML))
    assert m.resolve("startButton") == 8
    assert m.resolve("STARTBUTTON") == 8
    assert m.resolve("SD72") == 72
    assert m.resolve("3/4") == 32 + 3 * 16 + 4
    assert m.resolve("17") == 17
    w = prochw.Machine(None, "wpc")
    assert w.resolve("S11") == 32
    for bad in ("nosuch", "C01"):           # PRDecode would atoi() these to 0 / a coil
        with pytest.raises(ValueError):
            w.resolve(bad)


# ------------------------------------------------------------- the board
def test_board_identifies_as_a_p3roc_and_reads_switches(monkeypatch):
    f = board()
    p = attach(monkeypatch, f)
    p.reset(1)
    states = p.switch_get_states()
    assert len(states) == 256
    closed = [i for i, s in enumerate(states) if s == pinproc.EventTypeSwitchClosedDebounced]
    assert closed == [9, 75]
    assert set(states) == {pinproc.EventTypeSwitchClosedDebounced,
                           pinproc.EventTypeSwitchOpenDebounced}
    assert p._dev.chip_id == pinproc.P3_ROC_CHIP_ID and p._dev.version == 2


def test_no_board_is_an_ioerror_like_pypinproc(monkeypatch):
    def unplugged():
        raise OSError("no socket")
    monkeypatch.setattr(pinproc, "link_factory", unplugged)
    with pytest.raises(IOError):
        pinproc.PinPROC("pdb")


def test_a_wpc_game_refuses_a_stern_wired_board(monkeypatch):
    # Create(): a WPC machine type on a board whose dips say Stern is refused.
    f = board(yaml=None)
    monkeypatch.setattr(pinproc, "link_factory", lambda: prochw.InProcessLink(f))
    with pytest.raises(IOError, match="Machine type"):
        pinproc.PinPROC("wpc")
    f = prochw.Fpga("proc", prochw.Machine(None, "wpc"))
    monkeypatch.setattr(pinproc, "link_factory", lambda: prochw.InProcessLink(f))
    assert pinproc.PinPROC("wpc")._dev.chip_id == pinproc.P_ROC_CHIP_ID


def test_rules_decide_what_the_host_hears(monkeypatch):
    f = board()
    p = attach(monkeypatch, f)
    p.reset(1)
    p.switch_update_rule(8, "closed_debounced", NOTIFY)
    p.switch_update_rule(8, "open_debounced", NOTIFY)
    p.flush()
    assert f.host_events, "the first rule turns host events on (pypinproc's static)"
    f.set_active(8, True)
    f.set_active(8, False)
    f.set_active(79, True)                  # no rule: the host never hears it
    ev = [(e["type"], e["value"]) for e in p.get_events()]
    assert ev == [(pinproc.EventTypeSwitchClosedDebounced, 8),
                  (pinproc.EventTypeSwitchOpenDebounced, 8)]


def test_linked_drivers_fire_on_the_board_not_the_host(monkeypatch):
    f = board()
    p = attach(monkeypatch, f)
    p.reset(1)
    for n in (1, 2):
        p.driver_update_state(blank(n))
    p.switch_update_rule(0, "closed_nondebounced", QUIET,
                         [pinproc.driver_state_pulse(blank(1), 30),
                          pinproc.driver_state_patter(blank(2), 2, 18, 0, True)])
    p.switch_update_rule(0, "open_nondebounced", QUIET,
                         [pinproc.driver_state_disable(blank(1)),
                          pinproc.driver_state_disable(blank(2))])
    p.flush()
    f.set_active(0, True)
    assert f.driver_table() == {"1": "pulse 30ms", "2": "patter 2/18"}
    f.set_active(0, False)
    assert f.driver_table() == {}
    rule = [(e["driver"], e["action"]) for e in f.log if e["by"].startswith("rule")]
    assert rule == [(1, "pulse 30ms"), (2, "patter 2/18"), (1, "off"), (2, "off")]
    assert p.get_events() == []


def test_rewriting_a_rule_frees_its_links(monkeypatch):
    f = board()
    p = attach(monkeypatch, f)
    p.reset(1)
    free = len(p._dev.free_rules)
    three = [pinproc.driver_state_pulse(blank(n), 10) for n in (1, 2, 3)]
    p.switch_update_rule(5, "closed_nondebounced", QUIET, three)
    assert len(p._dev.free_rules) == free - 2
    p.switch_update_rule(5, "closed_nondebounced", QUIET, [])
    assert len(p._dev.free_rules) == free


def test_host_drivers_pulses_end_and_leds(monkeypatch):
    clock = [100.0]
    machine = prochw.Machine(str(YAML))
    f = prochw.Fpga("p3roc", machine, machine.initial_closed(), clock=lambda: clock[0])
    p = attach(monkeypatch, f)
    for n in (5, 6):
        p.driver_update_state(blank(n))
    p.driver_pulse(5, 40)
    p.driver_schedule(6, 0xf0f0f0f0, 0, True)
    p.led_color(0, 3, 200)
    p.led_fade(1, 4, 99, 0x123)
    p.flush()
    assert f.driver_table() == {"5": "pulse 40ms", "6": "schedule f0f0f0f0"}
    clock[0] += 0.041
    f.tick()
    assert f.driver_table() == {"6": "schedule f0f0f0f0"}
    assert f.leds == {"0:3": 200, "1:4": 99}
    p.write_data(3, 0xC00, 0x01020105)      # a raw PD-LED write (pdb.py does these)
    assert f.leds["2:0"] == 5


def test_watchdog_and_state_report(monkeypatch):
    f = board()
    p = attach(monkeypatch, f)
    p.watchdog_tickle()
    p.flush()
    st = f.state()
    assert st["board"] == "P3-ROC 2.17" and st["watchdog_ms"] is not None
    assert st["active"] == ["trough1", "trough2", "trough3"]
    json.dumps(st)


def test_proc_board_uses_v1_events_and_dmd_frames(monkeypatch):
    f = prochw.Fpga("proc", prochw.Machine(None, "sternWhitestar"), dmd_fps=1000.0)
    p = attach(monkeypatch, f, "sternWhitestar")
    assert p._dev.version == 1
    p.switch_update_rule(40, "closed_debounced", NOTIFY)
    p.dmd_update_config()
    frame = pinproc.DMDBuffer(128, 32)
    frame.set_dot(0, 0, 15)
    frame.fill_rect(8, 0, 8, 1, 1)
    p.dmd_draw(frame)
    p.flush()
    f.set_switch(40, True)
    import time
    time.sleep(0.01)
    ev = p.get_events()
    assert {"type": pinproc.EventTypeSwitchClosedDebounced, "value": 40} in \
        [dict(type=e["type"], value=e["value"]) for e in ev]
    assert any(e["type"] == pinproc.EventTypeDMDFrameDisplayed for e in ev)
    assert f.dmd_frames == 1 and len(f.dmd_last) == 4 * 128 * 32 // 32
    # 128 words per sub-frame, bytes packed little-endian into each word.
    # dot (0,0) = 15 -> bit 0 in all four sub-frames; dots 8..15 = 1 -> the
    # P-ROC colour map makes that 2 -> sub-frame 1 only, byte 1 of word 0.
    assert [f.dmd_last[128 * s] for s in range(4)] == [0x1, 0xff01, 0x1, 0x1]


def test_dmdbuffer_blends_like_dmd_c():
    a, b = pinproc.DMDBuffer(4, 1), pinproc.DMDBuffer(4, 1)
    a.set_data(bytes([1, 2, 3, 0]))
    b.set_data(bytes([15, 15, 0, 7]))
    a.copy_to_rect(b, 0, 0, 0, 0, 4, 1, "add")
    assert b.get_data() == bytes([15, 15, 3, 7])
    a.copy_to_rect(b, 0, 0, 0, 0, 4, 1, "sub")
    assert b.get_data() == bytes([14, 13, 0, 7])
    a.copy_to_rect(b, 1, 0, 0, 0, 4, 1)      # clipped copy
    assert b.get_data() == bytes([14, 1, 2, 3])
    assert pinproc.DMDBuffer(1, 1).get_data_mult() == bytes([0])
    with pytest.raises(ValueError):
        a.copy_to_rect(b, 0, 0, 0, 0, 1, 1, "xor")


# ------------------------------------------------------------ ctl protocol
def test_ctl_commands(tmp_path):
    f = board()
    d = prochw.Daemon(str(tmp_path), f, open(tmp_path / "log", "w"))
    assert d.on_ctl("sw startButton 1").startswith("ok 8 closed")
    assert d.on_ctl("sw startButton 1").endswith("(unchanged)")
    assert d.on_ctl("sw trough1 0") == "ok 72 closed"     # NC: inactive = closed
    assert d.on_ctl("closed SD79 1") == "ok 79 closed"
    assert d.on_ctl("tap leftSling 50") == "ok 66 tapped 50ms"
    assert json.loads(d.on_ctl("switches"))["trough2"]["active"] is True
    assert json.loads(d.on_ctl("state"))["host"] is False
    assert d.on_ctl("sw nosuch 1").startswith("err")
    assert d.on_ctl("frobnicate").startswith("err")
    assert d.on_ctl("quit") == "ok bye" and not d.running


def test_rig_scripts_are_lf_and_complete():
    for name in ("procpath.sh", "build.sh", "hw.sh", "run_py.sh", "ctl.sh", "killgame.sh",
                 "status.sh", "prochw.py", "procctl.py", "fakeftdi.c", "pystub/pinproc.py",
                 "selftest/run.sh", "selftest/build_real.sh", "selftest/probe.py",
                 "selftest/probe.c", "selftest/demo_game.py", "selftest/py3port.py"):
        data = (RIG / name).read_bytes()
        assert b"\r\n" not in data, name


def test_fakeftdi_exports_what_libpinproc_calls():
    import re
    src = (RIG / "fakeftdi.c").read_text()
    exported = set(re.findall(r"^EXPORT [^(]*?\b(ftdi_\w+)\(", src, re.M))
    # PRHardware.cpp's whole libftdi1 vocabulary
    for fn in ("ftdi_init", "ftdi_deinit", "ftdi_usb_find_all", "ftdi_list_free",
               "ftdi_usb_get_strings", "ftdi_usb_open", "ftdi_usb_close", "ftdi_read_chipid",
               "ftdi_read_data_set_chunksize", "ftdi_set_latency_timer", "ftdi_read_data",
               "ftdi_write_data", "ftdi_get_error_string"):
        assert fn in exported, fn
