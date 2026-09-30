"""tools/spooky_emu (PAD-266): the parts of the Beetlejuice rig that can be
checked without WSL - the emulated Warden board's answers, ball moves and
control requests, sw.py's switch names and the switch window's model."""

import importlib.util
import json
import pathlib

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spooky_emu"


def _load(name, path):
    spec = importlib.util.spec_from_file_location("spk_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


warden = _load("warden", RIG / "spkwarden.py")
sw = _load("sw", RIG / "sw.py")


@pytest.fixture
def board(tmp_path, monkeypatch):
    b = warden.Board(str(tmp_path), pty=False)
    b.sent = []
    monkeypatch.setattr(b, "send", lambda data: b.sent.append(bytes(data)))
    monkeypatch.setattr(b, "later", lambda secs, fn, *a: fn(*a))
    yield b
    b.log.close()


def test_machine_at_rest_has_a_full_trough(board):
    on = sorted(n for n, v in board.state.items() if v)
    # Six balls: TROUGH 1..6 (7, 6, 5, 4, 3, 1); TROUGH 7 and the jam clear.
    assert on == [1, 3, 4, 5, 6, 7]
    assert board.state[0] == 0 and board.state[2] == 0


def test_answers_switch_state_and_the_watchdog(board):
    board.host_bytes(bytes([0x3E, 152, 7, 0x3E, 152, 87, 0x3E, 168, 6]))
    assert board.sent == [bytes([0x3C, 152, 7, 1]), bytes([0x3C, 152, 87, 0]),
                          bytes([0x3C, 168, 6, 0, 0, 0, 255])]


def test_eject_serves_a_ball_and_launch_clears_the_lane(board):
    board.host_bytes(bytes([0x3E, 191, 51, 0x0F, 0xA0]))   # pulse-and-hold eject
    assert board.balls == 5 and board.state[8] == 1
    assert board.state[1] == 0                             # TROUGH 6 emptied
    assert bytes([0x3C, 1, 8]) in board.sent
    board.host_bytes(bytes([0x3E, 133, 51]))               # lane full: no double serve
    assert board.balls == 5
    board.host_bytes(bytes([0x3E, 132, 54, 50]))           # auto-launch
    assert board.state[8] == 0
    board.drain()
    assert board.balls == 6 and board.state[1] == 1


def test_a_message_split_across_reads_is_kept(board):
    assert board.host_bytes(bytes([1, 2, 3, 0x3E])) == bytes([3, 0x3E])
    assert board.host_bytes(bytes([7])) == b""              # nothing can start there
    tail = board.host_bytes(bytes([9, 9, 0x3E, 152]))
    assert board.host_bytes(tail + bytes([87])) == b""
    assert board.sent == [bytes([0x3C, 152, 87, 0])]


def test_control_requests(board):
    assert board.command("sw 87 1") == "ok"
    assert board.sent == [bytes([0x3C, 1, 87])]
    board.command("sw 87 1")                                # no change, no report
    board.command("sw 87 0")
    assert board.sent[-1] == bytes([0x3C, 0, 87])
    assert board.command("tap 25 50") == "ok"
    assert board.sent[-2:] == [bytes([0x3C, 1, 25]), bytes([0x3C, 0, 25])]
    assert board.command("nonsense").startswith("err")


def test_state_plunge_and_drain(board):
    st = json.loads(board.command("state"))
    assert st["balls"] == {"trough": 6, "shooter": 0, "in_play": 0}
    assert st["switches"]["7"] == 1 and not st["connected"]
    assert board.command("drain").startswith("err")          # nothing in play
    assert board.command("plunge").startswith("err")         # lane empty
    board.host_bytes(bytes([0x3E, 133, 51]))                 # serve
    assert json.loads(board.command("state"))["balls"]["shooter"] == 1
    assert board.command("plunge") == "ok"
    assert json.loads(board.command("state"))["balls"] == {
        "trough": 5, "shooter": 0, "in_play": 1}
    assert board.command("drain") == "ok"
    assert json.loads(board.command("state"))["balls"]["trough"] == 6


def test_sw_names_the_switches():
    assert sw.lookup("start") == 87
    assert sw.lookup("START_BUTTON") == 87
    assert sw.lookup("top pop") == 25
    assert sw.lookup("12") == 12
    with pytest.raises(SystemExit):
        sw.lookup("pop bumper")                             # three of them
    with pytest.raises(SystemExit):
        sw.lookup("no-such-switch")


def test_sw_and_board_agree_on_the_trough():
    for i, n in enumerate(warden.TROUGH):
        assert sw.SWITCHES[n] == "TROUGH %d" % (i + 1)
    assert sw.SWITCHES[warden.SHOOTER] == "SHOOTER LANE"


def test_switch_window_model_groups_beetlejuice_switches():
    """spkpf.py hands bofpf's page a profile built from sw.py's table."""
    import sys
    sys.path.insert(0, str(RIG))
    sys.path.insert(0, str(RIG.parent / "bof_emu"))
    sys.path.insert(0, str(RIG.parent / "spike2_emu"))
    try:
        spkpf = _load("pf", RIG / "spkpf.py")
        bofpf = sys.modules["bofpf"]
    finally:
        for p in (str(RIG), str(RIG.parent / "bof_emu"), str(RIG.parent / "spike2_emu")):
            sys.path.remove(p)
    model = bofpf.page_model(spkpf.profile())
    assert len(model["switches"]) == len(sw.SWITCHES)
    keys = {r["n"]: r["key"] for r in model["switches"] if r["key"]}
    assert keys == {87: "1", 90: "5", 86: "Z", 80: "/", 85: "Space", 81: "A"}
    assert not any(r["placed"] for r in model["switches"])   # list only
    assert spkpf.group(7) == "Trough" and spkpf.group(87) == "Cabinet"
    assert spkpf.group(25) == "Playfield"
