"""tools/ap_emu (PAD-264): the parts of the American Pinball rig that can be
checked without WSL - the pinproc stand-in the games import, the rig's
config.yaml, the .pkg member filter and sw.py's switch list."""

import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "ap_emu"


def _load(name, path):
    spec = importlib.util.spec_from_file_location("ap_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pinproc = _load("pinproc", RIG / "py" / "pinproc.py")
prepare = _load("prepare", RIG / "prepare.py")
sw = _load("sw", RIG / "sw.py")


def test_pinproc_machine_type_and_decode():
    assert pinproc.normalize_machine_type("pdb") == pinproc.MachineTypePDB == 7
    assert pinproc.normalize_machine_type("wpc") == pinproc.MachineTypeWPC
    assert pinproc.normalize_machine_type(5) == 5
    assert pinproc.normalize_machine_type("nonsense") == pinproc.MachineTypeInvalid
    # PDB numbers are plain integers to libpinproc (procgame's PDBConfig does
    # the A0-B1-2 addresses); WPC names decode as the real module does.
    assert pinproc.decode("pdb", "12") == 12
    assert pinproc.decode("wpc", "S11") == 32
    assert pinproc.decode("wpc", "C01") == 40
    with pytest.raises(TypeError):
        pinproc.decode("pdb", 12)


def test_pinproc_driver_states_keep_c_widths():
    blank = dict((k, 0) for k in pinproc.DRIVER_KEYS)
    blank["driverNum"] = 20
    pulse = pinproc.driver_state_pulse(blank, 300)
    assert pulse["state"] == 1 and pulse["outputDriveTime"] == 300 & 0xff
    patter = pinproc.driver_state_patter(blank, 2, 18, 30, True)
    assert patter["patterEnable"] == 1 and patter["waitForFirstTimeSlot"] == 0
    assert pinproc.driver_state_disable(pulse)["state"] == 0
    assert pinproc.aux_command_disable()["active"] == 0
    with pytest.raises(IOError):
        pinproc.PinPROC(pinproc.MachineTypePDB)


def test_pinproc_dmdbuffer():
    b = pinproc.DMDBuffer(4, 3)
    b.fill_rect(1, 1, 10, 10, 7)
    assert b.get_dot(0, 0) == 0 and b.get_dot(3, 2) == 7
    with pytest.raises(ValueError):
        b.get_dot(4, 0)


def test_prepare_skips_macos_litter():
    assert prepare.litter("assets/.DS_Store")
    assert prepare.litter("__MACOSX/assets/x.png")
    assert prepare.litter("assets/._x.png")
    assert not prepare.litter("assets/dmd/x.png")


def test_prepare_reads_the_apps_ap_key():
    key = prepare.ap_key()
    assert isinstance(key, bytes) and len(key) == 32


def _mkconfig(tmp_path, game, env=None):
    yaml = pytest.importorskip("yaml")
    out = tmp_path / "local_config" / "config.yaml"
    subprocess.run([sys.executable, str(RIG / "py" / "mkconfig.py"), str(game), str(out),
                    "/sdl", str(game)], check=True, capture_output=True,
                   env=dict(os.environ, **(env or {})))
    return yaml.safe_load(out.read_text())


def test_mkconfig_takes_the_titles_config_and_runs_it_on_the_fake_proc(tmp_path):
    game = tmp_path / "houdini"
    (game / "assets" / "dmd" / "fonts").mkdir(parents=True)
    (game / "config.yaml").write_text(
        "pinproc_class: pinproc.PinPROC\nuse_desktop: false\ndmd_path: ./x/\n"
        "default_modes:\n  osc_input: true\n")
    cfg = _mkconfig(tmp_path, game)
    assert cfg["pinproc_class"] == "procgame.fakepinproc.FakePinPROC"
    assert cfg["use_desktop"] is True
    assert cfg["dmd_path"] == "./x/"                 # the title's own wins
    assert cfg["hdfont_dir"] == "./assets/dmd/fonts/"
    assert cfg["default_modes"]["osc_input"] is False
    # no ball search: its coil fire ends in a free ball save, and Drain after
    # an idle spell never ended the ball (PAD-292)
    assert cfg["default_modes"]["ball_search"] is False
    assert cfg["dmd_framerate"] == 30
    assert cfg["dmd_dot_filter"] is False            # no dmdgrid*.png shipped
    assert "dmd" not in cfg["default_modes"]


def test_mkconfig_av_title_hands_the_screen_to_apiav(tmp_path):
    game = tmp_path / "hotWheels"
    (game / "assets" / "screen" / "fonts").mkdir(parents=True)
    (game / "assets" / "sounds").mkdir()
    cfg = _mkconfig(tmp_path, game, {"AP_AVC": "1"})
    assert cfg["dmd_path"] == "./assets/screen/"
    assert cfg["sound_path"] == "./assets/sounds/"
    for mode in ("dmd", "score_display", "service_mode", "attract"):
        assert cfg["default_modes"][mode] is False
    assert "tilt_mode" not in cfg["default_modes"]  # Hot Wheels needs it
    assert cfg["screen_position_x"] >= 2560         # parked off the display


def test_mkconfig_points_the_dot_grid_at_assets_dmd(tmp_path):
    game = tmp_path / "legends"
    (game / "assets" / "dmd").mkdir(parents=True)
    (game / "assets" / "dmd" / "dmdgrid32x32.png").write_bytes(b"")
    cfg = _mkconfig(tmp_path, game)
    assert cfg["dmd_grid_path"] == "./assets/dmd/"


def test_sw_reads_the_switch_list(tmp_path, monkeypatch):
    (tmp_path / "switches").write_text(
        "trough1 54 NC TROUGH JAM\nstartButton 60 NO Start Button\nplain 3 NO\n")
    monkeypatch.setattr(sw, "RIG", str(tmp_path))
    assert sw.switches() == [("trough1", 54, "NC", "TROUGH JAM"),
                             ("startButton", 60, "NO", "Start Button"),
                             ("plain", 3, "NO", "")]


def test_mkconfig_frames_a_visible_run(tmp_path):
    game = tmp_path / "legends"
    (game / "assets").mkdir(parents=True)
    assert _mkconfig(tmp_path, game)["dmd_window_border"] is False
    assert _mkconfig(tmp_path, game, {"AP_VISIBLE": "1"})["dmd_window_border"] is True


# -- PAD-292: the Emulate AP tab's switch table, control pipe and window ------
SWITCHES = (
    "flipperLwL 0 NO LeftFlipper\n"
    "flipperLwR 1 NO RightFlipper\n"
    "ActionButton 2 NO Action Button\n"
    "enter 3 NO Enter\n"
    "exit 4 NO Exit\n"
    "down 5 NO Down\n"
    "up 6 NO Up\n"
    "startButton 8 NO StartButton\n"
    "coinDoor 9 NO Coin Door\n"
    "coin1 10 NO Coin 1\n"
    "flipperMwL 15 NO MiddleFlipper\n"
    "leftOrbit 32 NO LeftOrbit\n"
    "rightOrbit 38 NO RightOrbit\n"
    "scoop 41 NC Scoop\n"
    "spinner 47 NO Spinner\n"
    "trough1 48 NC Trough1\n"
    "troughEject 54 NC TroughEject\n"
    "shooter 55 NO ShooterLane\n"
    "unused_24 56 NO Unused\n"
    "TBD39 57 NO Not Used\n"
    "SD2 58 NO Not Used\n")

#: A real layout's shape: playfield switches spread down the picture, the
#: coins parked in its corner, one switch beside it, lamps.
LAYOUT = """bg_image: playfield.jpg
window_size: {width: 508, height: 980}
button_locations:
- leftOrbit: {x: 75, y: 345}
- scoop: {x: 107, y: 652}
- spinner: {x: 180, y: 229}
- rightOrbit: {x: 471, y: 384}
- coin1: {x: 50, y: 60}
- flipperLwL: {x: 74, y: 888}
- startButton: {x: 20, y: 961}
lamp_locations:
- Ship: {x: 374, y: 499, color_on: {r: 0, g: 255, b: 255}}
- gi01: {x: 58, y: 791}
- off_picture: {x: 600, y: 10}
"""


def _png(path, w, h):
    """The first bytes of a PNG: enough for a size (apswitches reads only that)."""
    import struct
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", w, h)
                     + b"\x08\x02\x00\x00\x00")


def _build(tmp_path, mdir="legends"):
    rig = tmp_path / "rig0"
    rig.mkdir(exist_ok=True)
    (rig / "switches").write_text(SWITCHES)
    build = tmp_path / "lov_25.08.27"
    build.mkdir()
    (build / "machine_dir").write_text(mdir)
    # the layout says .jpg; the build ships .png (Houdini, Hot Wheels...)
    _png(build / "playfield.png", 450, 999)
    (build / "lov.layout").write_text(LAYOUT)
    # a default layout nobody laid out: everything piled at the top edge
    (build / "junk.layout").write_text(
        "bg_image: playfield.jpg\nbutton_locations:\n" +
        "".join("- %s: {x: %d, y: 5}\n" % (n, 10 + i) for i, n in
                enumerate(("leftOrbit", "scoop", "spinner", "rightOrbit", "coin1",
                           "flipperLwL", "startButton", "trough1"))))
    return rig, build


def test_apswitches_image_size_reads_png_and_jpeg(tmp_path):
    aps = _load("apswitches", RIG / "apswitches.py")
    _png(tmp_path / "a.png", 346, 768)
    assert aps.image_size(str(tmp_path / "a.png")) == (346, 768)
    jpg = tmp_path / "a.jpg"
    # SOI, an APP0 segment, then a SOF0 with height 999, width 450
    jpg.write_bytes(b"\xff\xd8" + b"\xff\xe0\x00\x04ab" + b"\xff\xc0\x00\x11\x08\x03\xe7\x01\xc2"
                    + b"\x00" * 12)
    assert aps.image_size(str(jpg)) == (450, 999)
    assert aps.image_size(str(tmp_path / "missing.png")) is None


def test_apswitches_places_playfield_switches_on_the_games_own_layout(tmp_path):
    pytest.importorskip("yaml")
    aps = _load("apswitches", RIG / "apswitches.py")
    rig, build = _build(tmp_path)
    t = aps.table(str(rig), str(build), "Legends of Valhalla", root=str(tmp_path / "root"))
    by = {s["name"]: s for s in t["switches"]}
    assert t["title"] == "Legends of Valhalla" and t["size"] == [450, 999]
    # the .png the build ships, whatever the layout calls it
    assert t["art"] == str(build / "playfield.png")
    assert t["art_from"] == "the game's own layout"
    # Legends of Valhalla's layout sits 14 px right and 4 px high: moved back
    assert (by["leftOrbit"]["x"], by["leftOrbit"]["y"]) == (61, 349)
    # beside the picture (x 471 on a 450 picture): not placed
    assert "x" not in by["rightOrbit"]
    # the coins, the flippers and Start are the panel's, not the picture's
    assert not {"x"} & set(by["coin1"]) and "x" not in by["flipperLwL"]
    assert "x" not in by["startButton"]
    # the lights the picture places, calibrated too; one off it is not
    assert t["lights"] == [["Ship", 360, 503], ["gi01", 44, 795]]
    assert not {"unused_24", "TBD39", "SD2"} & set(by)
    assert by["scoop"]["nc"] and not by["leftOrbit"]["nc"]
    assert [by[n]["group"] for n in ("flipperLwL", "coin1", "leftOrbit", "trough1", "shooter")] == [
        "Cabinet", "Cabinet", "Playfield", "Trough", "Trough"]
    assert (t["shooter"], t["coin_door"]) == (55, 9)


def test_apswitches_refuses_a_layout_nobody_laid_out(tmp_path):
    pytest.importorskip("yaml")
    aps = _load("apswitches", RIG / "apswitches.py")
    rig, build = _build(tmp_path, mdir="hw")
    (build / "lov.layout").unlink()
    t = aps.table(str(rig), str(build), root=str(tmp_path / "root"))
    assert t["art"] == "" and t["size"] is None and t["lights"] == []
    assert not any("x" in s for s in t["switches"])


def test_apswitches_takes_the_simulator_positions_when_the_game_has_them(tmp_path):
    """Galactic Tank Force 2026: the machine yaml's x/y on AP's own simulator
    picture beat any layout."""
    pytest.importorskip("yaml")
    import json
    aps = _load("apswitches", RIG / "apswitches.py")
    rig, build = _build(tmp_path, mdir="tank")
    svc = build / "tank" / "assets" / "screen" / "service"
    svc.mkdir(parents=True)
    _png(svc / "playfield.png", 346, 768)
    (rig / "pfpos.json").write_text(json.dumps({
        "switches": {"scoop": [100, 200]}, "leds": {"Ship": [50, 60], "far": [900, 10]},
        "balls": 6}))
    t = aps.table(str(rig), str(build), root=str(tmp_path / "root"))
    by = {s["name"]: s for s in t["switches"]}
    assert t["art"] == str(svc / "playfield.png") and t["size"] == [346, 768]
    assert t["art_from"] == "AP's playfield simulator"
    assert (by["scoop"]["x"], by["scoop"]["y"]) == (100, 200) and "x" not in by["leftOrbit"]
    assert t["lights"] == [["Ship", 50, 60]] and t["balls"] == 6


def test_apswitches_writes_switches_json(tmp_path):
    pytest.importorskip("yaml")
    rig, build = _build(tmp_path)
    out = subprocess.run([sys.executable, str(RIG / "apswitches.py"), str(rig), str(build), "LoV"],
                         check=True, capture_output=True, text=True,
                         env=dict(os.environ, AP_ROOT=str(tmp_path / "root"))).stdout
    assert "18 switches, 3 on the playfield picture, 2 lights placed (the game's own layout)" in out
    import json
    assert json.loads((rig / "switches.json").read_text())["title"] == "LoV"


def test_apswitches_borrows_the_layout_a_newer_package_dropped(tmp_path):
    """Legends of Valhalla 26.08.22 ships no .layout and no playfield
    picture: the one kept from 25.08.27 stands in, and with the older build
    gone from the cache too, the kept copy still does."""
    pytest.importorskip("yaml")
    aps = _load("apswitches", RIG / "apswitches.py")
    root = tmp_path / "root"
    rig, old = _build(tmp_path)
    (root / "cache").mkdir(parents=True)
    old = old.rename(root / "cache" / "lov_25.08.27")
    new = root / "cache" / "lov_26.08.22"
    new.mkdir()
    (new / "machine_dir").write_text("legends")
    # nothing kept yet: another cached build of the title lends its layout
    t = aps.table(str(rig), str(new), root=str(root))
    by = {s["name"]: s for s in t["switches"]}
    assert (by["leftOrbit"]["x"], by["leftOrbit"]["y"]) == (61, 349)
    assert "lov_25.08.27" in t["art_from"]
    # ...and is kept: with the old build deleted, the kept copy answers
    import shutil
    shutil.rmtree(old)
    t = aps.table(str(rig), str(new), root=str(root))
    assert t["art"] == str(root / "layouts" / "legends" / "playfield.png")
    assert "kept" in t["art_from"]
    # a different title borrows nothing
    (new / "machine_dir").write_text("tank")
    t = aps.table(str(rig), str(new), root=str(root))
    assert t["art"] == "" and t["art_from"] == ""
    assert not any("x" in s for s in t["switches"])


def _ctl(tmp_path, monkeypatch):
    apctl = _load("apctl", RIG / "apctl.py")
    rig = tmp_path / "rig0"
    rig.mkdir(exist_ok=True)
    import json
    (rig / "switches.json").write_text(json.dumps({
        "shooter": 55, "switches": [{"n": 0}, {"n": 8}, {"n": 48}, {"n": 55}]}))
    (rig / "input").write_text("")               # stands in for the FIFO
    (rig / "game.pid").write_text("%d\n" % os.getpid())
    monkeypatch.setattr(apctl, "ROOT", str(tmp_path))
    monkeypatch.setattr(apctl, "MIN_HOLD_S", 0)
    return apctl.Ctl("0"), rig


def test_apctl_turns_presses_into_fifo_lines(tmp_path, monkeypatch):
    ctl, rig = _ctl(tmp_path, monkeypatch)
    assert ctl.run(["sw", "0", "1"]) == {"ok": True}
    assert ctl.held == {0}
    assert ctl.run(["sw", "0", "0"]) == {"ok": True}
    assert ctl.run(["tap", "8"]) == {"ok": True}
    assert ctl.run(["plunge"]) == {"ok": True}
    assert ctl.run(["drain"]) == {"ok": True}
    assert ctl.run(["reset"]) == {"ok": True}
    assert ctl.run(["sw", "99", "1"])["ok"] is False          # not this machine's
    assert (rig / "input").read_text().splitlines() == [
        "0 close", "0 open", "8 tap 150", "55 open", "!drain", "!reset"]


def test_apctl_state_is_what_the_game_has_active_plus_what_it_holds(tmp_path, monkeypatch):
    ctl, rig = _ctl(tmp_path, monkeypatch)
    (rig / "active").write_text("48 55\n")
    (rig / "lights.json").write_text('{"Ship": [0, 255, 255]}')
    ctl.run(["sw", "0", "1"])
    st = ctl.run(["state"])
    assert st["up"] is True and st["held"] == [0] and st["paused"] is False
    assert st["switches"] == {"0": 1, "48": 1, "55": 1}
    assert st["lights"] == {"Ship": [0, 255, 255]}
    (rig / "game.pid").write_text("999999999\n")
    assert ctl.run(["state"])["up"] is False


# -- the virtual playfield: the Stern page, served for an AP game ------------
class FakeRig:
    def __init__(self):
        self.lines = []

    def ask(self, line):
        self.lines.append(line)
        if line.startswith("pause"):
            return {"ok": True, "paused": line.endswith("1")}
        return {"ok": True}


class FakeHost:
    def __init__(self):
        self.events = []

    def publish(self, etype, data=None):
        self.events.append((etype, data))


def _appf_app(tmp_path, field=True, audio=True):
    pytest.importorskip("yaml")
    import json
    aps = _load("apswitches", RIG / "apswitches.py")
    appf = _load("appf", RIG / "appf.py")
    rig, build = _build(tmp_path)
    if not field:
        (build / "lov.layout").unlink()
    t = aps.table(str(rig), str(build), "Legends of Valhalla", root=str(tmp_path / "root"))
    t["balls"] = 6
    ctl = ""
    if audio:
        ctl = str(tmp_path / "audio_ctl.json")
        (tmp_path / "audio_ctl.json").write_text(json.dumps({"gain": 0.5, "muted": False}))
    app = appf.App(t, FakeRig(), t["art"], "Legends of Valhalla", slot="0", audio_ctl=ctl)
    app.host = FakeHost()
    return appf, app


def test_appf_serves_the_stern_page():
    appf = _load("appf", RIG / "appf.py")
    assert appf.PAGE_DIR.endswith(os.path.join("spike2_emu", "pfpage"))
    assert os.path.isfile(os.path.join(appf.PAGE_DIR, "pf.js"))


def test_appf_snapshot_is_the_stern_field_view(tmp_path):
    appf, app = _appf_app(tmp_path)
    app.active = {48, 9}
    app.lights = {"Ship": [0, 128, 128], "gi01": [0, 0, 0]}
    s = app.state("main")
    assert s["kind"] == "field" and s["title"] == "Legends of Valhalla - virtual playfield"
    v = s["view"]
    assert v["base"] == [450, 999] and v["art"] is True
    assert [sw[3] for sw in v["switches"]] == [32, 41, 47]          # the placed ones
    assert v["fixtures"] == [["Ship", 360, 503], ["gi01", 44, 795]]
    # a lit light at full colour, its brightness the alpha; a dark one None
    assert s["dyn"]["fx"] == {"Ship": [0, 255, 255, 0.5, appf.LED_R], "gi01": None}
    assert s["dyn"]["sw"] == {"48": 1, "9": 1}
    assert s["run"] == {"paused": False, "audio": {"gain": 0.5, "muted": False}}
    spec = s["panel"]["spec"]
    rows = {r["label"]: r for r in spec["rows"]}
    assert rows["StartButton"]["keys"] == "1" and rows["Coin 1"]["keys"] == "5"
    assert rows["Action Button"]["keys"] == "Space"
    # both left flippers on the Left arrow, as the Stern window's flippers
    assert rows["LeftFlipper + MiddleFlipper"]["keys"] == "Left"
    assert rows["RightFlipper"]["keys"] == "Right"
    # letters for playfield switches, the Stern window's first ones
    assert rows["LeftOrbit"]["keys"] == "A" and rows["RightOrbit"]["keys"] == "S"
    assert [b["label"] for b in spec["svc"]] == ["Service Back", "Service Minus",
                                                "Service Plus", "Service Select"]
    # one dot per BALL (6), not per trough switch
    assert spec["door"] == "C" and spec["balls"] == {"pos": ["1", "2", "3", "4", "5", "6"]}
    d = s["panel"]["dyn"]
    assert d["door"] is True and d["dots"]["flags"] == [True] + [False] * 5
    assert d["ball"].startswith("balls 6   trough 1") and d["drain"] is True


def test_appf_without_a_picture_is_the_schematic_view(tmp_path):
    appf, app = _appf_app(tmp_path, field=False)
    app.lights = {"Ship": [255, 0, 0], "gi01": [0, 0, 0]}
    s = app.state("main")
    assert s["kind"] == "schematic"
    cells = [c["k"] for c in s["view"]["grid"]["blocks"][0]["cells"]]
    assert cells == ["Ship", "gi01"]
    assert [e["id"] for e in s["view"]["entries"]][:3] == [0, 1, 2]
    assert s["dyn"]["grid"] == {"Ship": [255, 0, 0, 1.0], "gi01": None}
    # the schematic lists every switch: the panel keeps its keyed rows only
    assert all(r["keys"] for r in s["panel"]["spec"]["rows"])


def test_apswitches_keymap_is_one_map_for_the_window_and_the_game(tmp_path):
    pytest.importorskip("yaml")
    aps = _load("apswitches", RIG / "apswitches.py")
    rig, build = _build(tmp_path)
    t = aps.table(str(rig), str(build), root=str(tmp_path / "root"))
    km = {c: k for k in t["keymap"] for c in k["codes"]}
    assert km["ArrowLeft"]["ns"] == [0, 15] and km["Digit1"]["ns"] == [8]
    assert km["Escape"]["ns"] == km["Backspace"]["ns"] == [4]        # service Back
    assert km["Enter"]["ns"] == [3]
    assert (km["KeyF"]["action"], km["KeyD"]["action"], km["KeyC"]["action"],
            km["F9"]["action"]) == ("plunge", "drain", "door", "pause")
    rows = {r["label"]: r for r in t["rows"]}
    assert rows["LeftOrbit"]["keys"] == "A" and not rows["LeftOrbit"]["unplaced"]
    assert rows["RightOrbit"]["keys"] == "S"
    # a switch off the picture with no letter left still gets a row
    assert all(r["codes"] or r["unplaced"] for r in t["rows"])


def test_appf_calls_press_switches_and_move_balls(tmp_path):
    appf, app = _appf_app(tmp_path)
    rig = app.rig
    app.api("hold", [32])
    app.api("unhold", [])
    assert rig.lines[-2:] == ["sw 32 1", "sw 32 0"]
    i = next(i for i, r in enumerate(app.rows) if r["keys"] == "Left")
    app.api("row", [i, True])
    assert rig.lines[-2:] == ["sw 0 1", "sw 15 1"]
    app.api("row", [i, False])
    # keys: the flippers hold while down; F / D / C are Plunge, Drain, the door
    app.api("key", ["ArrowRight", "ArrowRight", True])
    app.api("key", ["ArrowRight", "ArrowRight", False])
    assert rig.lines[-2:] == ["sw 1 1", "sw 1 0"]
    app.api("key", ["KeyF", "f", True])
    app.api("key", ["KeyD", "d", True])
    app.api("ball", ["reset"])
    assert rig.lines[-3:] == ["plunge", "drain", "reset"]
    app.active = {9}
    app.api("door", [])
    assert rig.lines[-1] == "sw 9 0"                    # closed -> open
    app.api("key", ["Backspace", "Backspace", True])
    assert rig.lines[-1] == "sw 4 1"                    # SERVICE: BACK is exit
    app.api("blur", [])
    assert rig.lines[-1] == "sw 4 0"                    # focus lost: let go


def test_appf_pause_and_volume(tmp_path):
    import json
    appf, app = _appf_app(tmp_path)
    app.api("pause", [])
    assert app.rig.lines[-1] == "pause 1" and app.paused
    assert ("run", {"paused": True, "audio": {"gain": 0.5, "muted": False}}) in app.host.events
    app.api("key", ["F9", "F9", True])
    assert app.rig.lines[-1] == "pause 0" and not app.paused
    app.api("volume", [30])
    app.api("mute", [True])
    assert json.loads((tmp_path / "audio_ctl.json").read_text()) == {"gain": 0.3, "muted": True}


def test_appf_frames_send_only_what_changed(tmp_path):
    appf, app = _appf_app(tmp_path)
    app.frame()
    app.active = {41}
    app.lights = {"Ship": [0, 0, 255]}
    f = app.frame()
    assert f["sw"] == {"41": 1} and f["fx"] == {"Ship": [0, 0, 255, 1.0, appf.LED_R]}
    app.active = set()
    f = app.frame()
    assert f["sw"] == {"41": 0} and "fx" not in f
    assert app.frame() == {}


def test_appf_win_path():
    appf = _load("appf", RIG / "appf.py")
    assert appf.win_path("/var/tmp/pad_ap/cache/x/playfield.jpg", "PAD-Runtime") == \
        r"\\wsl.localhost\PAD-Runtime\var\tmp\pad_ap\cache\x\playfield.jpg"


def test_prepare_redoes_a_changed_pkg(tmp_path):
    pkg = tmp_path / "lov-gamecode_25.08.27.pkg"
    pkg.write_bytes(b"x" * 10)
    first = prepare.stamp(str(pkg))
    pkg.write_bytes(b"x" * 11)
    assert prepare.stamp(str(pkg)) != first


def test_appf_closes_its_window_when_the_app_closes_the_pipe():
    """Stop closes appf.py's stdin; the window (a separate browser process)
    must be told to close and the host quit - killing appf.py alone left the
    window on screen."""
    import io
    appf = _load("appf", RIG / "appf.py")

    class Host:
        def __init__(self):
            self.events, self.quit_called = [], False

        def publish(self, e, data=None):
            self.events.append(e)

        def quit(self):
            self.quit_called = True

    class App:
        stopping = False
    app, host = App(), Host()
    appf.watch_parent(app, host, io.StringIO("anything\n"))   # then EOF
    assert app.stopping and host.events == ["close"] and host.quit_called
    # already on its way out: nothing twice
    host2 = Host()
    appf.watch_parent(app, host2, io.StringIO(""))
    assert host2.events == [] and not host2.quit_called


SINK_INPUTS = """Sink Input #0
	Driver: protocol-native.c
	Mute: no
	Volume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB
	Properties:
		application.process.id = "460"
		application.process.binary = "python2.7"
Sink Input #3
	Mute: no
	Volume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB
	Properties:
		application.process.id = "999"
"""


def test_apvol_holds_only_this_slots_streams():
    apvol = _load("apvol", RIG / "apvol.py")
    inputs = apvol.parse_sink_inputs(SINK_INPUTS)
    assert [(s["index"], s["pid"], s["volume"], s["muted"]) for s in inputs] == [
        (0, 460, 65536, False), (3, 999, 65536, False)]
    vol, mute = apvol.target_volume(0.5, True)
    assert mute and 0 < vol < 65536
    # the game (460) is set; somebody else's stream (999) never is
    assert apvol.plan(inputs, {460}, vol, mute) == [
        ["set-sink-input-volume", "0", str(vol)], ["set-sink-input-mute", "0", "1"]]
    # already there: nothing to do
    there = [dict(inputs[0], volume=vol, muted=True)]
    assert apvol.plan(there, {460}, vol, mute) == []


def test_apquit_wraps_the_one_event_call_apiav_makes():
    src = (RIG / "apquit.c").read_text()
    assert "int SDL_PollEvent(SDL_Event *event)" in src
    assert "SDL_WINDOWEVENT_CLOSE" in src and "SDL_QUIT" in src and "RTLD_NEXT" in src
