"""tools/spooky_emu (PAD-266): the parts of the Beetlejuice rig that can be
checked without WSL - the emulated Warden board's answers and ball moves,
and sw.py's switch names."""

import importlib.util
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
    board.command("drain")
    assert board.balls == 6 and board.state[1] == 1


def test_a_message_split_across_reads_is_kept(board):
    assert board.host_bytes(bytes([1, 2, 3, 0x3E])) == bytes([3, 0x3E])
    assert board.host_bytes(bytes([7])) == b""              # nothing can start there
    tail = board.host_bytes(bytes([9, 9, 0x3E, 152]))
    assert board.host_bytes(tail + bytes([87])) == b""
    assert board.sent == [bytes([0x3C, 152, 87, 0])]


def test_switch_commands(board):
    board.command("87 on")
    assert board.sent == [bytes([0x3C, 1, 87])]
    board.command("87 on")                                  # no change, no report
    board.command("87 off")
    assert board.sent[-1] == bytes([0x3C, 0, 87])
    board.command("25 pulse 50")
    assert board.sent[-2:] == [bytes([0x3C, 1, 25]), bytes([0x3C, 0, 25])]


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
