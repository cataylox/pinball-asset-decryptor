"""tools/spooky_emu (PAD-266, PAD-267): the parts of the Spooky Warden rig
that can be checked without WSL - the emulated Warden board's framing,
answers and state, its ball moves and per-title mechanics, the title
profiles and detection, sw.py's switch names and the switch window's
model."""

import importlib.util
import json
import os
import pathlib
import sys

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spooky_emu"


def _load(name, path):
    spec = importlib.util.spec_from_file_location("spk_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


warden = _load("warden", RIG / "spkwarden.py")
titles = warden.spktitles
# sw.py reads the running rig's title at import: point it at no rig.
_root = os.environ.get("SPK_ROOT")
os.environ["SPK_ROOT"] = str(RIG / "no-such-rig")
try:
    sw = _load("sw", RIG / "sw.py")
finally:
    if _root is None:
        del os.environ["SPK_ROOT"]
    else:
        os.environ["SPK_ROOT"] = _root

TX, RX = 0x3E, 0x3C


def _board(tmp_path, monkeypatch, title=None):
    b = warden.Board(str(tmp_path), pty=False, title=title)
    b.sent = []
    monkeypatch.setattr(b, "send", lambda data: b.sent.append(bytes(data)))
    monkeypatch.setattr(b, "later", lambda secs, fn, *a: fn(*a))
    return b


@pytest.fixture
def board(tmp_path, monkeypatch):
    b = _board(tmp_path, monkeypatch)
    yield b
    b.log.close()


@pytest.fixture
def make(tmp_path, monkeypatch):
    made = []

    def mk(title):
        d = tmp_path / title
        d.mkdir()
        made.append(_board(d, monkeypatch, title))
        return made[-1]
    yield mk
    for b in made:
        b.log.close()


# --- Beetlejuice, as PAD-266 left it -------------------------------------

def test_machine_at_rest_has_a_full_trough(board):
    on = sorted(n for n, v in board.state.items() if v)
    # Six balls: TROUGH 1..6 (7, 6, 5, 4, 3, 1); TROUGH 7 and the jam clear.
    assert on == [1, 3, 4, 5, 6, 7]
    assert board.state[0] == 0 and board.state[2] == 0


def test_answers_switch_state_and_hardware_info(board):
    board.host_bytes(bytes([TX, 152, 7, TX, 152, 87, TX, 151]))
    assert board.sent == [bytes([RX, 152, 7, 1]), bytes([RX, 152, 87, 0]),
                          # Evil Dead / Texas Chainsaw read exactly 7 bytes
                          # and want "WARDEN"; Looney pings for it.
                          bytes([RX, 151]) + b"WARDEN\x00"]


def test_watchdog_gets_back_the_coil_config_the_host_set(board):
    board.host_bytes(bytes([TX, 168, 6]))                   # a fresh board
    assert board.sent[-1] == bytes([RX, 168, 6, 0, 0, 0, 0])
    board.host_bytes(bytes([TX, 143, 6, 20, 255, 0, 255]))  # Dummy6: hold 100%
    board.host_bytes(bytes([TX, 168, 6]))
    assert board.sent[-1] == bytes([RX, 168, 6, 20, 255, 0, 255])


def test_eject_serves_a_ball_and_launch_clears_the_lane(board):
    board.host_bytes(bytes([TX, 191, 51, 0x0F, 0xA0]))    # pulse-and-hold eject
    assert board.balls == 5 and board.state[8] == 1
    assert board.state[1] == 0                             # TROUGH 6 emptied
    assert bytes([RX, 1, 8]) in board.sent
    board.host_bytes(bytes([TX, 133, 51]))                 # lane full: no double serve
    assert board.balls == 5
    board.host_bytes(bytes([TX, 132, 54, 50]))             # auto-launch
    assert board.state[8] == 0
    board.drain()
    assert board.balls == 6 and board.state[1] == 1


def test_a_message_split_across_reads_is_kept(board):
    assert board.host_bytes(bytes([1, 2, 3, TX])) == bytes([TX])   # junk skipped
    assert board.host_bytes(bytes([152])) == bytes([TX, 152])
    assert board.host_bytes(bytes([87, TX, 143, 6, 20])) == bytes([TX, 143, 6, 20])
    assert board.sent == [bytes([RX, 152, 87, 0])]
    assert board.host_bytes(bytes([255, 0, 255])) == b""
    assert board.coil_config[6] == [20, 255, 0, 255]


def test_every_opcode_is_framed_by_its_argument_count(board):
    """A '>' inside arguments (LED value 62, coil 62...) must never start a
    message: the board frames by count, so the switch-state request that
    follows each message is answered exactly once, in order."""
    stream = b""
    for op, n in sorted(warden.ARGS.items()):
        if op in (150, 151, 152, 168, 212):
            continue                                       # these answer
        stream += bytes([TX, op] + [TX] * n + [TX, 152, 87])
    board.host_bytes(stream)
    asked = [m for m in board.sent if m[:2] == bytes([RX, 152])]
    assert len(asked) == len(warden.ARGS) - 5
    assert not board.unknown and board.pend == b""


def test_an_unknown_opcode_is_skipped_to_the_next_message(board):
    board.host_bytes(bytes([TX, 0x70, 1, 2, TX, 152, 7]))
    assert board.unknown == {0x70: 1}
    assert board.sent == [bytes([RX, 152, 7, 1])]


def test_control_requests(board):
    assert board.command("sw 87 1") == "ok"
    assert board.sent == [bytes([RX, 1, 87])]
    board.command("sw 87 1")                                # no change, no report
    board.command("sw 87 0")
    assert board.sent[-1] == bytes([RX, 0, 87])
    assert board.command("tap 25 50") == "ok"
    assert board.sent[-2:] == [bytes([RX, 1, 25]), bytes([RX, 0, 25])]
    assert board.command("nonsense").startswith("err")


def test_state_plunge_and_drain(board):
    st = json.loads(board.command("state"))
    assert st["balls"] == {"trough": 6, "shooter": 0, "in_play": 0}
    assert st["switches"]["7"] == 1 and not st["connected"]
    assert st["title"] == "Beetlejuice" and st["key"] == "bj"
    assert board.command("drain").startswith("err")          # nothing in play
    assert board.command("plunge").startswith("err")         # lane empty
    board.host_bytes(bytes([TX, 133, 51]))                   # serve
    assert json.loads(board.command("state"))["balls"]["shooter"] == 1
    assert board.command("plunge") == "ok"
    assert json.loads(board.command("state"))["balls"] == {
        "trough": 5, "shooter": 0, "in_play": 1}
    assert board.command("drain") == "ok"
    assert json.loads(board.command("state"))["balls"]["trough"] == 6


# --- what the board keeps: LEDs, coils, power, lamps, servos, stepper ------

def test_leds_every_colour_form(board):
    board.host_bytes(bytes([TX, 154, 0, 4, TX, 154, 1, 2]))       # 6 LEDs
    board.host_bytes(bytes([TX, 128, 1, 0b11000000]))             # 8-bit red
    board.host_bytes(bytes([TX, 171, 2, 1, 2, 3]))                # 24-bit
    board.host_bytes(bytes([TX, 167, 3, 0xF, 0x0F]))              # 12-bit
    board.host_bytes(bytes([TX, 160, 4, 0x70, 1]))                # palette white
    leds = json.loads(board.command("leds"))
    assert leds == {"1": "ff0000", "2": "010203", "3": "ff00ff",
                    "4": "ffffff"}
    assert board.led_mode[4] == "blink"
    board.host_bytes(bytes([TX, 181, 1, 0b00000111]))             # overlay blue
    assert json.loads(board.command("leds"))["1"] == "0000ff"
    board.host_bytes(bytes([TX, 155, 0]))                         # all off
    assert json.loads(board.command("leds")) == {"1": "0000ff"}   # overlay stays
    board.host_bytes(bytes([TX, 174, 0]))
    assert json.loads(board.command("state"))["leds_lit"] == 0
    board.host_bytes(bytes([TX, 198, 0, 3, 9, 9, 9]))             # 3 at once
    assert json.loads(board.command("state"))["leds_lit"] == 3


def test_coils_power_lamps_servos(board):
    board.host_bytes(bytes([TX, 139, TX, 137]))
    board.host_bytes(bytes([TX, 131, 24, 255, TX, 133, 20, TX, 133, 20]))
    board.host_bytes(bytes([TX, 188, 0xFC | 2]))                  # start lit
    board.host_bytes(bytes([TX, 153, 33, 145]))
    st = json.loads(board.command("state"))
    assert st["power"] == {"48v": 1, "pwm": 1}
    assert st["coils"]["fired"] == {"20": 2, "24": 1}
    assert st["coils"]["held"] == [24]
    assert st["lamps"] == {"start": 1, "launch": 0}
    assert st["servos"] == {"33": 145}
    board.host_bytes(bytes([TX, 131, 24, 0, TX, 140]))
    st = json.loads(board.command("state"))
    assert st["coils"]["held"] == [] and st["power"]["48v"] == 0


def test_stepper_homes_moves_and_reports(board):
    board.host_bytes(bytes([TX, 217, TX, 211, TX, 212]))
    assert board.sent[-1] == bytes([RX, 212, warden.STEPPER_IDLE])
    board.host_bytes(bytes([TX, 209, 0, 0, 0, 50, TX, 210, 0, 0, 0, 100]))
    assert board.stepper["mm"] == 100
    board.host_bytes(bytes([TX, 216, TX, 212]))
    assert board.sent[-1] == bytes([RX, 212, warden.STEPPER_DISABLED])


def test_stepper_is_busy_until_the_move_ends(board, monkeypatch):
    waiting = []
    monkeypatch.setattr(board, "later", lambda secs, fn, *a: waiting.append((fn, a)))
    board.host_bytes(bytes([TX, 211, TX, 212]))
    assert board.sent[-1] == bytes([RX, 212, warden.STEPPER_HOMING])
    fn, a = waiting.pop()
    fn(*a)
    board.host_bytes(bytes([TX, 212]))
    assert board.sent[-1] == bytes([RX, 212, warden.STEPPER_IDLE])


def test_flipper_button_fires_its_coil_and_closes_its_eos(board):
    board.host_bytes(bytes([TX, 144, 86, 3, 4, 21]))      # LEFT FLIPPER BUTTON
    board.command("sw 86 1")
    assert board.coil_fired == {3: 1} and board.state[21] == 1
    board.command("sw 86 0")
    assert board.state[21] == 0
    board.host_bytes(bytes([TX, 142]))                    # flippers off
    board.command("sw 86 1")
    assert board.coil_fired == {3: 1}


def test_a_switch_tied_to_a_coil_fires_it(board):
    board.host_bytes(bytes([TX, 146, 20, 4, 0]))           # LEFT SLING -> coil 4
    board.command("tap 20 10")
    assert board.coil_fired == {4: 1}
    board.host_bytes(bytes([TX, 147]))
    board.command("tap 20 10")
    assert board.coil_fired == {4: 1}


# --- the other titles' profiles and mechanics ------------------------------

def test_every_title_profile_is_consistent():
    for key, t in titles.TITLES.items():
        names = t["switches"]
        assert len(t["trough"]) == 7 and t["balls"] <= 7, key
        for i, n in enumerate(t["trough"]):
            assert "TROUGH" in names[n] and str(i + 1) in names[n], (key, n)
        assert "JAM" in names[t["jam"]], key
        assert "SHOOTER" in names[t["shooter"]], key
        for coil, lane in t["launch"].items():
            assert "SHOOTER" in names[lane], (key, coil)
        # The Warden's cabinet inputs are the same on every game.
        assert "START" in names[87].upper(), key
        assert "COIN" in names[90].upper(), key
        assert "LAUNCH" in names[85].upper(), key
        assert t["engine"] in ("unity", "godot") and t["layout"] in ("flat", "code")
        assert t["attract"], key


@pytest.mark.parametrize("key, balls", [
    ("bj", 6), ("scooby", 7), ("tcm", 7), ("ed", 6), ("looney", 7)])
def test_each_title_rests_with_its_trough_full(make, key, balls):
    b = make(key)
    t = titles.TITLES[key]
    assert [b.state[n] for n in t["trough"]] == [1] * balls + [0] * (7 - balls)
    for n in t.get("rest", ()):
        assert b.state[n] == 1


@pytest.mark.parametrize("key, eject, launch", [
    ("scooby", 10, 8), ("tcm", 12, 9), ("looney", 12, 9)])
def test_each_title_serves_and_launches(make, key, eject, launch):
    b = make(key)
    shooter = titles.TITLES[key]["shooter"]
    b.host_bytes(bytes([TX, 133, eject]))
    assert b.state[shooter] == 1
    b.host_bytes(bytes([TX, 133, launch]))
    assert b.state[shooter] == 0
    assert b.balls_state()["in_play"] == 1


def test_evil_dead_serves_to_the_lane_its_diverter_points_at(make):
    b = make("ed")
    b.host_bytes(bytes([TX, 153, 33, 145, TX, 186, 15]))   # load right
    assert b.state[15] == 1 and not b.state.get(14)
    b.host_bytes(bytes([TX, 153, 33, 90, TX, 186, 15]))    # load left
    assert b.state[14] == 1
    assert b.balls_state()["shooter"] == 2
    b.host_bytes(bytes([TX, 133, 14]))                     # RIGHT AUTO LAUNCHER
    assert b.state[15] == 0 and b.state[14] == 1
    assert b.command("plunge") == "ok" and b.state[14] == 0


def test_evil_dead_drop_banks_stand_back_up(make):
    b = make("ed")
    b.command("sw 45 0")                                   # G knocked down
    b.command("sw 49 0")                                   # V knocked down
    b.host_bytes(bytes([TX, 133, 6]))                      # UPPER DROP BANK
    assert b.state[45] == 1 and b.state[49] == 0
    b.host_bytes(bytes([TX, 133, 7]))                      # LOWER DROP BANK
    assert b.state[49] == 1


def test_texas_chainsaw_diverter_opens_while_its_coil_holds(make, monkeypatch):
    b = make("tcm")
    timers = []
    monkeypatch.setattr(b, "later", lambda secs, fn, *a: timers.append((fn, a)))
    assert b.state[43] == 1
    b.host_bytes(bytes([TX, 191, 22, 0x03, 0xE8]))         # hold 1000 ms
    assert b.state[43] == 0
    b.host_bytes(bytes([TX, 191, 22, 0x03, 0xE8]))         # held again
    fn, a = timers[0]
    fn(*a)                                                 # the FIRST timer ends
    assert b.state[43] == 0                                # ... not this hold
    fn, a = timers[1]
    fn(*a)
    assert b.state[43] == 1


# --- which game an update holds -------------------------------------------

def _unity(d, sub, product):
    (d / sub).mkdir(parents=True)
    (d / sub / "app.info").write_text("Spooky Pinball\n%s\n" % product)
    return d


def _godot(path, name):
    """A binary with a Godot 4 PCK (format 2) holding project.binary."""
    key = b"application/config/name"
    val = name.encode()
    proj = (b"ECFG" + b"\0" * 4 + key + (16).to_bytes(4, "little")
            + (4).to_bytes(4, "little") + len(val).to_bytes(4, "little") + val)
    fname = b"res://project.binary"
    pad = (-len(fname)) % 4
    table = (len(fname).to_bytes(4, "little") + fname + b"\0" * pad
             + (0).to_bytes(8, "little") + len(proj).to_bytes(8, "little")
             + b"\0" * 16 + b"\0" * 4)
    header = (b"GDPC" + (2).to_bytes(4, "little") + (4).to_bytes(4, "little")
              + (1).to_bytes(4, "little") + (2).to_bytes(4, "little")
              + b"\0" * 4)
    pck_start = 64                                  # after a fake ELF head
    base = pck_start + 100 + len(table)
    header += base.to_bytes(8, "little") + b"\0" * 64 + (1).to_bytes(4, "little")
    pck = header + table + proj
    path.write_bytes(b"\x7fELF" + b"\0" * 60 + pck
                     + len(pck).to_bytes(8, "little") + b"GDPC")


@pytest.mark.parametrize("sub, product, key", [
    ("main_Data", "SPF", "bj"), ("main_Data", "Scooby", "scooby"),
    ("uptest/main_Data", "TCM", "tcm"), ("uptest/main_Data", "Evil Dead", "ed")])
def test_detect_unity_titles(tmp_path, sub, product, key):
    assert titles.detect(str(_unity(tmp_path, sub, product))) == (key, None)


def test_detect_refuses_pinotaur_and_misplaced_builds(tmp_path):
    key, why = titles.detect(str(_unity(tmp_path / "um", "uptest/main_Data",
                                        "VideoServer")))
    assert key is None and "Pinotaur" in why
    key, why = titles.detect(str(_unity(tmp_path / "x", "uptest/main_Data",
                                        "Scooby")))
    assert key is None and "Scooby-Doo" in why
    key, why = titles.detect(str(tmp_path / "empty"))
    assert key is None


def test_detect_looney_tunes_from_its_godot_pack(tmp_path):
    _godot(tmp_path / "main.x86_64", "GDToons")
    assert titles.godot_project(str(tmp_path / "main.x86_64")) == "GDToons"
    assert titles.detect(str(tmp_path)) == ("looney", None)
    _godot(tmp_path / "main.x86_64", "Something Else")
    key, why = titles.detect(str(tmp_path))
    assert key is None and "Something Else" in why


def test_get_prints_fields_for_the_shell(capsys):
    assert titles.main(["get", "tcm", "trough"]) == 0
    assert capsys.readouterr().out.strip() == "49 6 5 4 3 2 1"
    assert titles.main(["get", "looney", "attract_in"]) == 0
    assert capsys.readouterr().out.strip() == "warden.log"
    assert titles.main(["get", "nope", "x"]) == 2


# --- sw.py and the switch window ------------------------------------------

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
    t = titles.get("bj")
    for i, n in enumerate(t["trough"]):
        assert sw.SWITCHES[n] == "TROUGH %d" % (i + 1)
    assert sw.SWITCHES[t["shooter"]] == "SHOOTER LANE"


def _spkpf():
    paths = [str(RIG), str(RIG.parent / "bof_emu"), str(RIG.parent / "spike2_emu")]
    for p in paths:
        sys.path.insert(0, p)
    try:
        return _load("pf", RIG / "spkpf.py"), sys.modules["bofpf"]
    finally:
        for p in paths:
            sys.path.remove(p)


def test_switch_window_model_groups_beetlejuice_switches():
    """spkpf.py hands bofpf's page a profile built from the title's table."""
    spkpf, bofpf = _spkpf()
    model = bofpf.page_model(spkpf.profile())
    assert len(model["switches"]) == len(sw.SWITCHES)
    keys = {r["n"]: r["key"] for r in model["switches"] if r["key"]}
    assert keys == {87: "1", 90: "5", 86: "Z", 80: "/", 85: "Space", 81: "A"}
    assert not any(r["placed"] for r in model["switches"])   # list only
    assert spkpf.group(7) == "Trough" and spkpf.group(87) == "Cabinet"
    assert spkpf.group(25) == "Playfield"


def test_switch_window_follows_the_running_title():
    spkpf, bofpf = _spkpf()
    p = spkpf.profile("ed")
    assert p["title"] == "Evil Dead"
    assert len(p["switches"]) == len(titles.TITLES["ed"]["switches"])
    assert spkpf.group(14, "ed") == "Trough" and spkpf.group(15, "ed") == "Trough"
    assert spkpf.group(66, "ed") == "Trough" and spkpf.group(45, "ed") == "Playfield"

    class Asks(spkpf.Rig):
        def __init__(self, reply):
            self.reply = reply

        def ask(self, line):
            return self.reply
    assert Asks(json.dumps({"key": "looney"})).title_key() == "looney"
    assert Asks(json.dumps({"key": "nope"})).title_key() is None
    assert Asks(None).title_key() is None
