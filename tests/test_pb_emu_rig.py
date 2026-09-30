"""tools/pb_emu (PAD-271): Predator's emulated FAST boards - the replies, the
switch polarity, the ball model and the title profile - everything that can
be checked without WSL.

Each reply shape is pinned to pinprog's own reader (platform/pb/fast.c, read
from the binary's disassembly with its DWARF line info); the comments name
the function that parses it, because a reply that "looks like FAST" but that
parser reads differently is exactly the bug this guards against.
"""

import importlib.util
import pathlib
import sys

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "pb_emu"
sys.path.insert(0, str(RIG))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, RIG / ("%s.py" % name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pbfast = _load("pbfast")
pbtitles = _load("pbtitles")
PRED = pbtitles.TITLES["predator"]


class _Log:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


class _FakePort:
    def __init__(self, role):
        self.role, self.rx, self.tx = role, b"", b""


def emu():
    e = pbfast.Emulator("/nonexistent", PRED, _Log())
    for role in (pbfast.NET, pbfast.EXP):
        e.ports[role] = _FakePort(role)
    return e


def take(e, role):
    p = e.ports[role]
    out, p.tx = p.tx, b""
    return out.decode("latin-1")


def run_timers(e):
    while e.timers:
        _, _, fn, args = e.timers.pop(0)
        fn(*args)
        e.timers.sort()


# ------------------------------------------------------------------ NET
def test_neuron_id_is_what_fast_identify_matches():
    e = emu()
    e.on_net_line("ID:")
    reply = take(e, "net")
    # fast_identify: strncmp(reply, "ID:NET FP-CPU", 13) picks the NET port
    assert reply.startswith("ID:NET FP-CPU") and reply.endswith("\r")


@pytest.mark.parametrize("cmd", ["CH:2000,01", "DL:00,C1,00,18,01,FF,FF,00"])
def test_confirmed_commands_get_a_P(cmd):
    e = emu()
    e.on_net_line(cmd)
    # fast_wait_reply CONFIRM: the char after the first ':' must be 'P'
    assert take(e, "net") == cmd[:2] + ":P\r"


@pytest.mark.parametrize("cmd", ["WD:000005DC", "SL:18,02,C0,C0", "TL:02,03",
                                 "TL:11,01"])
def test_unwaited_commands_get_no_reply(cmd):
    """fast_read copies ANY unsolicited line into the reply being waited on:
    a stray WD:P would answer the next SA: or NN:."""
    e = emu()
    e.on_net_line(cmd)
    assert take(e, "net") == ""


@pytest.mark.parametrize("node", range(4))
def test_node_names_parse_as_fast_get_node_name_reads_them(node):
    e = emu()
    e.on_net_line("NN:%02X" % node)
    reply = take(e, "net").rstrip("\r")
    assert reply.startswith("NN:")
    # strtok(".,") after "NN:": [0] node [1] name [2] major (dec) [3] minor
    # (dec) [4] drivers (hex) [5] switches (hex)
    toks = [t for t in reply[3:].replace(".", ",").split(",") if t]
    name, drv, sw = PRED["nodes"][node]
    assert int(toks[0], 16) == node
    assert toks[1] == name
    assert int(toks[4], 16) == drv and int(toks[5], 16) == sw


def test_node_boards_add_up_to_what_pinprog_expects():
    # raven.log: "FAST: 104 switches, 40 drivers"
    assert sum(n[2] for n in PRED["nodes"]) == 104
    assert sum(n[1] for n in PRED["nodes"]) == 40


def _sa_bits(reply):
    # fast_read_switches: cc = hex chars 3-4, cc-1 bytes of hex from char 6
    cc = int(reply[3:5], 16)
    data = reply[6:].rstrip("\r")
    nbytes = cc - 1
    assert len(data) == nbytes * 2
    bits = {}
    for b in range(nbytes):
        v = int(data[b * 2:b * 2 + 2], 16)
        for bit in range(8):
            bits[b * 8 + bit] = (v >> bit) & 1
    return bits


def test_sa_covers_every_switch_and_starts_with_a_full_trough():
    e = emu()
    e.on_net_line("SA:")
    bits = _sa_bits(take(e, "net"))
    assert max(bits) >= max(int(k) for k in PRED["switches"])
    # A full trough is six BLOCKED optos: an opto's SA bit is set when it is
    # NOT blocked (fast_read_switches flips it for switch_is_opto), so a
    # blocked one reads 0.
    for n in PRED["trough_switches"]:
        assert bits[n] == 0
    # Other optos, empty, read 1 (not blocked); ordinary open switches 0.
    assert bits[30] == 1            # TROUGH JAM, clear
    assert bits[10] == 0            # START BUTTON, up
    assert bits[4] == 1             # INTERLOCK, the door closed


def test_switch_events_carry_the_logical_state_for_optos_too():
    """The board applies SL: mode 02 before it reports, so -L is 'active'
    for every switch (phy_switch_update)."""
    e = emu()
    e.set_switch(10, 1)
    assert take(e, "net") == "-L:0A\r"
    e.set_switch(10, 0)
    assert take(e, "net") == "/L:0A\r"
    e.set_switch(29, 0)             # TROUGH 6 (an opto) empties
    assert take(e, "net") == "/L:1D\r"


# ------------------------------------------------------------------ EXP
@pytest.mark.parametrize("addr,name", sorted(PRED["exp_boards"].items()))
def test_each_expansion_board_answers_its_id(addr, name):
    e = emu()
    e.on_exp_line("ID@%s:" % addr)
    assert take(e, "exp").startswith("ID:EXP %s " % name)


def test_an_absent_expansion_board_stays_silent():
    e = emu()
    e.on_exp_line("ID@88:")
    assert take(e, "exp") == ""


@pytest.mark.parametrize("cmd,reply", [
    ("BR:", "BR:P\r"), ("EM:00,01,FFFF,03E8,07D0,05DC", "EM:P\r"),
    ("ER:00,00", "ER:P\r"),
    ("MF:01,FA,DD", "MF:P\r"),          # fast_wakeup_dc_motor waits
    ("MF:00,FFFF", ""),                 # a run command does not
    ("MP:00,80,0000", ""), ("EA:B40", ""), ("RS:0CDCDCDC", ""),
])
def test_expansion_replies(cmd, reply):
    e = emu()
    e.on_exp_line(cmd)
    assert take(e, "exp") == reply


def test_led_writes_land_on_the_selected_board():
    e = emu()
    e.on_exp_line("EA:B40")
    e.on_exp_line("RS:0CDC1020")
    assert e.leds[("B4", 0x0C)] == (0xDC, 0x10, 0x20)


# ----------------------------------------------------------- ball model
def test_trough_release_serves_a_ball_and_the_launcher_plunges_it():
    e = emu()
    e.on_net_line("TL:%02X,01" % PRED["trough_eject_driver"])
    run_timers(e)
    assert e.in_trough == 5 and e.switches[PRED["shooter_switch"]] == 1
    e.on_net_line("TL:%02X,01" % PRED["launch_drivers"][0])
    run_timers(e)
    assert e.in_play == 1 and e.switches[PRED["shooter_switch"]] == 0
    assert e.drain() and e.in_trough == 6


def test_a_bank_reset_stands_its_drop_targets_up():
    e = emu()
    for sw in (45, 46, 47):
        e.set_switch(sw, 1)
    e.on_net_line("TL:17,01")           # LEFT BANK RESET (sol 23)
    run_timers(e)
    assert not any(e.switches.get(sw) for sw in (45, 46, 47))


def test_titles_cli_prints_a_field(capsys):
    assert pbtitles.main(["get", "predator", "attract"]) == 0
    assert "AMODE" in capsys.readouterr().out


# ------------------------------------------------------------ scripts
@pytest.mark.parametrize("script", sorted(p.name for p in RIG.glob("*.sh")))
def test_scripts_are_lf_and_source_the_path_file(script):
    raw = (RIG / script).read_bytes()
    assert b"\r\n" not in raw
    if script not in ("pbpath.sh", "build.sh"):
        assert b'pbpath.sh"' in raw


def test_kills_are_filtered_by_this_rigs_mark():
    """pbio_emu (PAD-272) runs programs with the SAME names (pinprog,
    vidprog) as the same user: a bare pkill would stop its games."""
    for script in ("killgame.sh", "run_game.sh"):
        src = (RIG / script).read_text()
        assert "pkill" not in src
    assert "PB_MARK=$PB_RIG" in (RIG / "pbpath.sh").read_text()
