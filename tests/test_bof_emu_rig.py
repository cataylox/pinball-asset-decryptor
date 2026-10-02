"""tools/bof_emu (PAD-257): the emulated boards' replies, the ball model and
the per-title profiles - everything that can be checked without WSL.

Each reply shape here is pinned to the title's own parser (the decompiled
fast_stem.gd / bics.gd); the comments name the line of GDScript that reads
it, because a reply that "looks like FAST" but that parser rejects is exactly
the bug this guards against.
"""

import importlib.util
import json
import pathlib
import re
import shutil
import subprocess

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "bof_emu"


def _load_bofhw():
    spec = importlib.util.spec_from_file_location("bofhw", RIG / "bofhw.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bofhw = _load_bofhw()


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


def profile(title):
    return json.loads((RIG / "profiles" / ("%s.json" % title)).read_text())


def emu(title):
    """An Emulator with fake ports: replies accumulate in port.tx."""
    prof = profile(title)
    e = bofhw.Emulator("/nonexistent", prof, _Log())
    for spec in prof.get("ports", bofhw.DEFAULT_PORTS):
        e.ports[spec["role"]] = _FakePort(spec["role"])
    return e


def take(e, role):
    p = e.ports[role]
    out, p.tx = p.tx, b""
    return out.decode("latin-1")


TITLES = ("dune", "winchester", "labyrinth")


# ------------------------------------------------------------------ NET
@pytest.mark.parametrize("title", TITLES)
def test_neuron_id_parses_as_the_game_reads_it(title):
    e = emu(title)
    e.on_net_line("ID:")
    reply = take(e, "net")
    assert reply.endswith("\r")
    cmd, _, data = reply.rstrip("\r").partition(":")
    assert cmd == "ID" and data.startswith("NET")
    # fast_stem.gd: _details = _data[1].split(" "); firmware = _details[3]
    fw = data.split(" ")[3]
    assert fw == profile(title)["neuron_fw"]


def test_labyrinth_wants_its_exact_firmware_string():
    # Labyrinth's older driver compares strings: `_details[3] != "02.25"`
    # sends it into a firmware update that never ends.
    assert profile("labyrinth")["neuron_fw"] == "02.25"


@pytest.mark.parametrize("title", TITLES)
def test_node_list_names_every_board_with_six_fields(title):
    e = emu(title)
    e.on_net_line("CN:")
    lines = [l for l in take(e, "net").split("\r") if l]
    assert len(lines) == len(profile(title)["node_boards"])
    for line in lines:
        cmd, _, data = line.partition(":")
        assert cmd == "NN"
        # process_node_board_reply reads split(" ")[1] and [5]
        assert len(data.split(" ")) >= 6


def test_switch_states_are_physical_levels():
    e = emu("dune")
    # configure_switch: "SL:%s,%d,%X,%X" - mode 2 = reversed (an opto);
    # trough 1 is 0x48 = 72
    e.on_net_line("SL:48,2,A,A")
    e.switches = {72: 1, 12: 1}
    e.on_net_line("SA:")
    reply = take(e, "net").split("\r")[-2]
    hexs = reply.split(",")[1]
    # byte n//8, bit n%8; an active opto reads 0 (the game inverts it back)
    byte = lambda n: int(hexs[2 * (n // 8):2 * (n // 8) + 2], 16)
    assert not byte(72) & (1 << 0)
    assert byte(12) & (1 << (12 % 8))


def test_switch_events_use_the_games_prefixes():
    e = emu("dune")
    e.set_switch(14, 1)
    e.set_switch(14, 0)
    assert take(e, "net") == "-L:0E\r/L:0E\r"


# ------------------------------------------------------------------ EXP
def test_expansion_ids_answer_only_the_boards_present():
    e = emu("labyrinth")
    e.on_exp_line("ID@48:")
    reply = take(e, "exp")
    assert reply.startswith("ID:EXP ") and reply.split(" ")[3].strip() == "00.44"
    e.on_exp_line("ID@ac:")              # a topper this machine has not got
    assert take(e, "exp") == ""


def test_binary_led_frames_are_parsed_by_length_not_by_cr():
    e = emu("dune")
    p = e.ports["exp"]
    # an RD frame whose colour bytes include 0x0D, then an ASCII line
    p.rx = b"RD@b4:" + bytes([2, 5, 13, 0, 255, 6, 1, 2, 3]) + b"RA@84:ff0000\r"
    e.pump_exp(p)
    assert e.leds[("b4", 5)] == (13, 0, 255)
    assert e.leds[("b4", 6)] == (1, 2, 3)
    assert p.rx == b""


# ----------------------------------------------------------------- BICS
def bics(e, line):
    e.on_bics_line(line)
    return take(e, "bics")


def test_dune_worm_board_homes():
    e = emu("dune")
    assert "WRANGLER" in bics(e, "ID:")
    assert bics(e, "HOME:STEPPER ALL") == "HOME:STEPPER ALL,ACK\r\n"
    assert bics(e, "HOME:EDGES?") == "HOME:EDGES ACK\r\n"
    assert bics(e, "HOME:FAST MOUTH") == "HOME:FAST MOUTH,ACK\r\n"


def test_dune_positions_match_the_offsets_as_strings():
    # bics.gd compares worm_known_position == worm_offsets[2] as STRINGS
    e = emu("dune")
    offs = bics(e, "SET:OFFSETS? WORM").strip().split(",")[1:]
    bics(e, "MOVE:STEPPER ALL,FLUSH,0")
    pos = bics(e, "POSITION:STEPPER? WORM").strip().split(",")[1]
    assert pos == offs[2]


def test_winchester_haunt_handler_dialect():
    e = emu("winchester")
    reply = bics(e, "ID:")
    assert "Barrel_of_Interactive_Control_Systems_" in reply
    assert reply.strip().split(",")[3] == "v0.6.1"
    assert bics(e, "HOME:STEPPER") == "HOME:STEPPER ACK\r\n"
    assert "STEPPER:FAST ACK" in bics(e, "HOME:STEPPER:FAST")
    # the watchdog: begins_with("SWITCH? 6")
    assert bics(e, "SET:SWITCH? 6").startswith("SET:SWITCH? 6")


def test_winchester_bics_switch_three_flips_its_prefix():
    e = emu("winchester")
    e.set_switch(100, 1)                 # BICS index 3: "-L" means active
    e.set_switch(98, 1)                  # BICS index 0: "/L" means active
    assert take(e, "bics") == "-L:3\r\n/L:0\r\n"


def test_bics_never_offers_a_firmware_update():
    assert bics(emu("dune"), "FLASH?") == ""


# ------------------------------------------------------------ the balls
def test_eject_plunge_drain():
    e = emu("dune")
    balls = profile("dune")["balls"]
    assert e.in_trough == balls
    e.on_driver(["%X" % profile("dune")["trough_eject_driver"], "01"])
    assert e.in_trough == balls - 1
    e.timers.clear()                     # the ball reaches the lane at once
    e.set_switch(e.shooter, 1, "ball")
    assert e.plunge() and e.in_play == 1
    assert e.drain() and e.in_trough == balls and e.in_play == 0
    assert not e.drain()


# ------------------------------------------------------------- profiles
@pytest.mark.parametrize("title", TITLES)
def test_profile_boots_with_a_full_trough_and_closed_door(title):
    p = profile(title)
    assert len(p["trough_switches"]) >= p["balls"]
    # EXACTLY the ball count: one ball too many reads as "not full" to
    # trough.is_full() and Start is refused (Labyrinth: 5 balls, 6 slots)
    active = set(p["active_at_boot"])
    assert len(active & set(p["trough_switches"])) == p["balls"]
    assert p["coin_door_switch"] in active


@pytest.mark.parametrize("title", TITLES)
def test_profile_switch_table_is_whole(title):
    p = profile(title)
    ns = [s["n"] for s in p["switches"]]
    assert len(ns) == len(set(ns)), "a switch number appears twice"
    assert p["keys"]["start"] in ns
    for key in ("trough_eject_driver", "shooter_switch"):
        assert p[key] is not None


def test_ball_counts_are_the_titles_own():
    assert {t: profile(t)["balls"] for t in TITLES} == {
        "dune": 6, "winchester": 6, "labyrinth": 5}


# ---------------------------------------------------------------- files
def test_the_shim_is_checked_in_and_built():
    so = (RIG / "bofhwshim.so").read_bytes()
    assert so[:4] == b"\x7fELF"


SCRIPTS = sorted(p.name for p in RIG.glob("*.sh"))


@pytest.mark.skipif(shutil.which("bash") is None, reason="no bash")
@pytest.mark.parametrize("script", SCRIPTS)
def test_rig_scripts_parse(script):
    # On stdin, not by path: on Windows `bash` may be WSL's, which cannot
    # open a C:\ path.
    out = subprocess.run(["bash", "-n"], input=(RIG / script).read_bytes(),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert out.returncode == 0, out.stdout.decode()


def test_scripts_have_no_carriage_returns():
    for p in list(RIG.glob("*.sh")) + list(RIG.glob("*.py")):
        assert b"\r" not in p.read_bytes(), p.name


# ------------------------------------------------------ the switch window
def _load_bofpf():
    import sys
    sys.path.insert(0, str(RIG.parent / "spike2_emu"))
    spec = importlib.util.spec_from_file_location("bofpf", RIG / "bofpf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("title", TITLES)
def test_switch_window_model(title):
    """Every switch is listed; the ones with a test-screen position are
    placed on the drawing; the keys land on the switches the profile names."""
    pf = _load_bofpf()
    prof = profile(title)
    m = pf.page_model(prof)
    assert len(m["switches"]) == len(prof["switches"])
    placed = [s for s in m["switches"] if s["placed"]]
    assert len(placed) > len(m["switches"]) // 2
    assert all(s["x"] and s["y"] for s in placed)
    keyed = {s["key"]: s["n"] for s in m["switches"] if s["key"]}
    assert keyed["1"] == prof["keys"]["start"]
    flippers = [s for s in m["switches"] if s["hold"]]
    # every flipper button holds (upper ones too); nothing else does
    assert {s["n"] for s in flippers} == {
        n for k, n in prof["keys"].items() if k.startswith("flipper")}
    groups = {s["group"] for s in m["switches"]}
    assert groups <= {"Cabinet", "Playfield", "Mechanism"}
    assert ("Mechanism" in groups) == bool(prof.get("bics_switches"))


def test_switch_window_page_files_ship():
    for f in ("index.html", "bof.css", "bof.js"):
        assert (RIG / "bofpage" / f).is_file()


def test_the_game_loads_nothing_from_the_rigs_own_folder():
    """An installed app's rig is /mnt/c/Program Files/..., and LD_PRELOAD is
    a space-separated list: ld.so tried "/mnt/c/Program", "Files/Pinball"...,
    ignored them all, and the game never found its boards on any installed
    copy (PAD-313).  The shim is copied into the slot's folder and preloaded
    from there."""
    src = (RIG / "run_game.sh").read_text()
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for m in re.finditer(r'LD_(?:PRELOAD|LIBRARY_PATH)="?(\S+)', line):
            assert not re.search(r"\$\{?(BOF_TOOLS|BOF_SHIM|HERE)\b", m.group(1)), line
    assert 'cp "$BOF_SHIM" "$BOF_RIG/bofhwshim.so"' in src
    assert 'LD_PRELOAD="$BOF_RIG/bofhwshim.so"' in src


def test_the_game_window_gets_the_playfield_keys():
    """PAD-313: on the desktop run_game.sh starts the shared game-window key
    listener, which finds the game's windows by this rig's mark."""
    run = (RIG / "run_game.sh").read_text()
    assert "ap_emu/gamekeys.py" in run and '--mark "BOFEMU_LOG_DIR=$BOF_RIG"' in run
    assert "PAD_GAMEKEYS:-$VISIBLE" in run
