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


def _ask(board, line):
    return json.loads(board.command(line))


def test_control_requests(board):
    """The requests tools/ap_emu's game answers (appf.py's), in JSON."""
    assert _ask(board, "sw 87 1") == {"ok": True}
    assert board.sent == [bytes([0x3C, 1, 87])]
    board.command("sw 87 1")                                # no change, no report
    board.command("sw 87 0")
    assert board.sent[-1] == bytes([0x3C, 0, 87])
    assert _ask(board, "tap 25 50") == {"ok": True}
    assert board.sent[-2:] == [bytes([0x3C, 1, 25]), bytes([0x3C, 0, 25])]
    assert "err" in _ask(board, "nonsense")


def test_state_plunge_drain_and_reset(board):
    st = _ask(board, "state")
    assert st["up"] and st["lights"] == {} and not st["paused"]
    # only the switches that are made (appf.py reads the keys)
    assert st["switches"] == {"1": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1}
    assert st["balls"] == {"trough": 6, "shooter": 0, "in_play": 0}
    assert "err" in _ask(board, "drain")                     # nothing in play
    assert "err" in _ask(board, "plunge")                    # lane empty
    board.host_bytes(bytes([0x3E, 133, 51]))                 # serve
    assert _ask(board, "state")["balls"]["shooter"] == 1
    # Plunge presses the Launch button (Beetlejuice has no manual plunger);
    # the lane empties either way
    assert _ask(board, "plunge") == {"ok": True}
    assert bytes([0x3C, 1, 85]) in board.sent
    assert _ask(board, "state")["balls"] == {"trough": 5, "shooter": 0, "in_play": 1}
    assert _ask(board, "drain") == {"ok": True}
    assert _ask(board, "state")["balls"]["trough"] == 6
    board.host_bytes(bytes([0x3E, 133, 51]))                 # serve again
    assert _ask(board, "reset") == {"ok": True}
    assert _ask(board, "state")["balls"] == {"trough": 6, "shooter": 0, "in_play": 0}


def test_a_ball_left_in_the_lane_can_be_drained(board):
    board.host_bytes(bytes([0x3E, 133, 51]))
    assert _ask(board, "drain") == {"ok": True}
    assert _ask(board, "state")["balls"] == {"trough": 6, "shooter": 0, "in_play": 0}


def test_pause_freezes_the_game_by_its_pid(board, monkeypatch, tmp_path):
    (tmp_path / "game.pid").write_text("4242\n")
    sent = []
    monkeypatch.setattr(warden.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert _ask(board, "pause 1") == {"paused": True}
    assert _ask(board, "pause 0") == {"paused": False}
    assert sent == [(4242, warden.SIGSTOP), (4242, warden.SIGCONT)]


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


def _import_rig(name):
    import importlib
    import sys
    for p in (RIG, RIG.parent / "ap_emu", RIG.parent / "jjp_emu", RIG.parent / "spike2_emu"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    return importlib.import_module(name)


def test_the_table_is_in_the_ap_windows_format():
    t = _import_rig("spkswitches").table()
    assert t["balls"] == 6 and t["shooter"] == 8 and t["art"] == "" and t["size"] is None
    assert len(t["switches"]) == len(sw.SWITCHES)
    names = [s["name"] for s in t["switches"]]
    assert len(set(names)) == len(names)
    # the AP window finds the service buttons, the trough and the shooter by name
    for n in ("exit", "down", "up", "enter", "shooter", "trough1", "trough7"):
        assert n in names
    keys = {r["keys"]: r["ns"] for r in t["rows"] if r["keys"]}
    assert keys["1"] == [87] and keys["5"] == [90] and keys["Space"] == [85]
    assert keys["Left"] == [86, 83] and keys["Right"] == [80, 82]
    assert keys["T"] == [84] and keys["Down"] == [81]
    actions = {k["action"]: k["codes"] for k in t["keymap"] if k["action"]}
    assert actions["plunge"] == ["KeyF"] and actions["drain"] == ["KeyD"]
    # every switch can be pressed: a key row, a service button, or the list
    in_rows = {n for r in t["rows"] for n in r["ns"]}
    for s in t["switches"]:
        assert (s["n"] in in_rows or s["name"] in ("exit", "down", "up", "enter")
                or s["group"] == "Trough"), s


def test_the_ap_window_serves_beetlejuice():
    """spkpf.py hands tools/ap_emu/appf.py the table and this rig's pipe."""
    appf = _import_rig("appf")
    t = _import_rig("spkswitches").table()

    class Pipe:
        def ask(self, line):
            return {"up": True, "switches": {"1": 1, "3": 1, "8": 1}, "lights": {},
                    "paused": False}
    app = appf.App(t, Pipe(), "", "Beetlejuice")
    st = app.state("main")
    assert st["kind"] == "schematic"
    assert [b["label"] for b in st["panel"]["spec"]["svc"]] == [
        "Service Back", "Service Minus", "Service Plus", "Service Select"]
    assert st["panel"]["spec"]["balls"] == {"pos": ["1", "2", "3", "4", "5", "6"]}
    assert len(st["view"]["entries"]) == len(sw.SWITCHES)
    rig = _import_rig("spkpf").Rig("PAD-Runtime", "1")
    assert rig.cmd[-2].endswith("tools/spooky_emu/ctl.sh")


def test_a_zero_length_press_is_held_long_enough_to_count(board, monkeypatch):
    """A browser key press is 0 ms; the game re-asks the board about Start
    before it believes it, so the release waits out MIN_PRESS_S."""
    waits = []
    monkeypatch.setattr(board, "later", lambda secs, fn, *a: waits.append((secs, fn, a)))
    board.command("sw 87 1")
    board.command("sw 87 0")
    assert board.state[87] == 1                    # still held
    secs, fn, a = waits[-1]
    assert 0 < secs <= warden.MIN_PRESS_S
    fn(*a)                                          # the timer fires
    assert board.state[87] == 0
    assert board.sent[-1] == bytes([0x3C, 0, 87])


def test_the_window_says_its_keys_are_its_own():
    appf = _import_rig("appf")
    spkpf = _import_rig("spkpf")
    t = _import_rig("spkswitches").table()

    class Pipe:
        def ask(self, line):
            return None
    spec = spkpf.App(t, Pipe(), "", "Beetlejuice").state("main")["panel"]["spec"]
    assert spec["where"] == "works in this window"
    # the AP window itself keeps the page's default
    assert "where" not in appf.App(t, Pipe(), "", "x").state("main")["panel"]["spec"]
    # the flippers' end-of-stroke switches take no letter
    keyed = {n for r in t["rows"] if r["keys"] for n in r["ns"]}
    assert not keyed & {13, 21, 35}
