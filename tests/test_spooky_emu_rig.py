"""tools/spooky_emu (PAD-266, PAD-267): the parts of the Spooky Warden rig
that can be checked without WSL - the emulated Warden board's framing,
answers and state, its ball moves and per-title mechanics, the title
profiles and detection, sw.py's switch names and the virtual playfield's
table (spkswitches.py) and window (spkpf.py, on tools/ap_emu/appf.py)."""

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


def _ask(board, line):
    return json.loads(board.command(line))


def test_control_requests(board):
    """The requests tools/ap_emu's game answers (appf.py's), in JSON."""
    assert _ask(board, "sw 87 1") == {"ok": True}
    assert board.sent == [bytes([RX, 1, 87])]
    board.command("sw 87 1")                                # no change, no report
    board.command("sw 87 0")
    assert board.sent[-1] == bytes([RX, 0, 87])
    assert _ask(board, "tap 25 50") == {"ok": True}
    assert board.sent[-2:] == [bytes([RX, 1, 25]), bytes([RX, 0, 25])]
    assert "err" in _ask(board, "nonsense")


def test_state_plunge_drain_and_reset(board):
    st = _ask(board, "state")
    assert st["up"] and st["lights"] == {} and not st["paused"]
    assert st["title"] == "Beetlejuice" and st["key"] == "bj"
    assert not st["connected"]
    # only the switches that are made (appf.py reads the keys)
    assert st["switches"] == {"1": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1}
    assert st["balls"] == {"trough": 6, "shooter": 0, "in_play": 0}
    assert "err" in _ask(board, "drain")                     # nothing in play
    assert "err" in _ask(board, "plunge")                    # lane empty
    board.host_bytes(bytes([TX, 133, 51]))                   # serve
    assert _ask(board, "state")["balls"]["shooter"] == 1
    # Plunge presses the Launch button (no Warden game has a manual
    # plunger); the lane empties either way
    assert _ask(board, "plunge") == {"ok": True}
    assert bytes([RX, 1, 85]) in board.sent
    assert _ask(board, "state")["balls"] == {"trough": 5, "shooter": 0, "in_play": 1}
    assert _ask(board, "drain") == {"ok": True}
    assert _ask(board, "state")["balls"]["trough"] == 6
    board.host_bytes(bytes([TX, 133, 51]))                   # serve again
    assert _ask(board, "reset") == {"ok": True}
    assert _ask(board, "state")["balls"] == {"trough": 6, "shooter": 0, "in_play": 0}


def test_a_ball_left_in_the_lane_can_be_drained(board):
    board.host_bytes(bytes([TX, 133, 51]))
    assert _ask(board, "drain") == {"ok": True}
    assert _ask(board, "state")["balls"] == {"trough": 6, "shooter": 0, "in_play": 0}


def test_pause_freezes_the_game_by_its_pid(board, monkeypatch, tmp_path):
    (tmp_path / "game.pid").write_text("4242\n")
    sent = []
    monkeypatch.setattr(warden.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert _ask(board, "pause 1") == {"paused": True}
    assert _ask(board, "pause 0") == {"paused": False}
    assert sent == [(4242, warden.SIGSTOP), (4242, warden.SIGCONT)]


def test_a_zero_length_press_is_held_long_enough_to_count(board, monkeypatch):
    """A browser key press is 0 ms; the games re-ask the board about Start
    before they believe it, so the release waits out MIN_PRESS_S."""
    waits = []
    monkeypatch.setattr(board, "later", lambda secs, fn, *a: waits.append((secs, fn, a)))
    board.command("sw 87 1")
    board.command("sw 87 0")
    assert board.state[87] == 1                    # still held
    secs, fn, a = waits[-1]
    assert 0 < secs <= warden.MIN_PRESS_S
    fn(*a)                                          # the timer fires
    assert board.state[87] == 0
    assert board.sent[-1] == bytes([RX, 0, 87])


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
    assert _ask(b, "plunge") == {"ok": True} and b.state[14] == 0


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


def _import_rig(name):
    import importlib
    for p in (RIG, RIG.parent / "ap_emu", RIG.parent / "jjp_emu", RIG.parent / "spike2_emu"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    return importlib.import_module(name)


def test_the_table_is_in_the_ap_windows_format(monkeypatch):
    monkeypatch.delenv("SPK_TITLE", raising=False)
    t = _import_rig("spkswitches").table()
    assert t["title"] == "Beetlejuice"
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


@pytest.mark.parametrize("key", sorted(titles.TITLES))
def test_every_title_gets_its_own_table(key, tmp_path, monkeypatch):
    """run_game.sh writes the rig's title; the table is that game's."""
    monkeypatch.delenv("SPK_TITLE", raising=False)
    spk = _import_rig("spkswitches")
    (tmp_path / "title").write_text(key + "\n")
    assert spk.main([str(tmp_path)]) == 0
    t = json.loads((tmp_path / "switches.json").read_text())
    p = titles.TITLES[key]
    assert t["title"] == p["name"] and t["balls"] == p["balls"]
    assert t["shooter"] == p["shooter"]
    assert len(t["switches"]) == len(p["switches"])
    names = [s["name"] for s in t["switches"]]
    assert len(set(names)) == len(names)
    for n in ("exit", "down", "up", "enter", "shooter", "troughJam") + tuple(
            "trough%d" % i for i in range(1, 8)):
        assert n in names, (key, n)
    keys = {r["keys"]: r["ns"] for r in t["rows"] if r["keys"]}
    assert keys["1"] == [87] and keys["5"] == [90] and keys["Space"] == [85]
    groups = {s["n"]: s["group"] for s in t["switches"]}
    for lane in p["launch"].values():
        assert groups[lane] == "Trough"
    # no end-of-stroke switch takes a letter
    keyed = {n for r in t["rows"] if r["keys"] for n in r["ns"]}
    assert not any("EOS" in p["switches"][n].upper() for n in keyed)


def test_the_ap_window_serves_beetlejuice(monkeypatch):
    """spkpf.py hands tools/ap_emu/appf.py the table and this rig's pipe."""
    monkeypatch.delenv("SPK_TITLE", raising=False)
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


def test_the_window_says_its_keys_are_its_own(monkeypatch):
    monkeypatch.delenv("SPK_TITLE", raising=False)
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
