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
    "startButton 8 NO StartButton\n"
    "coinDoor 9 NO Coin Door\n"
    "coin1 10 NO Coin 1\n"
    "flipperMwL 15 NO MiddleFlipper\n"
    "leftOrbit 32 NO LeftOrbit\n"
    "scoop 41 NC Scoop\n"
    "trough1 48 NC Trough1\n"
    "shooter 55 NO ShooterLane\n"
    "unused_24 56 NO Unused\n"
    "TBD39 57 NO Not Used\n"
    "SD2 58 NO Not Used\n")


def _build(tmp_path):
    rig = tmp_path / "rig0"
    rig.mkdir()
    (rig / "switches").write_text(SWITCHES)
    build = tmp_path / "lov_25.08.27"
    build.mkdir()
    (build / "playfield.jpg").write_bytes(b"jpg")
    # the one naming more of this game's switches wins; one whose picture is
    # missing never does
    (build / "lov.layout").write_text(
        "bg_image: playfield.jpg\nbutton_locations:\n"
        "- leftOrbit:\n    x: 75\n    y: 345\n"
        "- scoop:\n    x: 300\n    y: 400\n"
        "- nothere:\n    x: 1\n    y: 1\n")
    (build / "old.layout").write_text(
        "bg_image: playfield.jpg\nbutton_locations:\n- leftOrbit:\n    x: 1\n    y: 2\n")
    (build / "nopic.layout").write_text(
        "bg_image: gone.jpg\nbutton_locations:\n"
        "- leftOrbit: {x: 1, y: 1}\n- scoop: {x: 1, y: 1}\n- shooter: {x: 1, y: 1}\n")
    return rig, build


def test_apswitches_places_the_switches_on_the_games_own_layout(tmp_path):
    pytest.importorskip("yaml")
    aps = _load("apswitches", RIG / "apswitches.py")
    rig, build = _build(tmp_path)
    t = aps.table(str(rig), str(build), "Legends of Valhalla", root=str(tmp_path / "root"))
    by = {s["name"]: s for s in t["switches"]}
    assert t["title"] == "Legends of Valhalla"
    assert t["art"] == str(build / "playfield.jpg")
    assert (by["leftOrbit"]["x"], by["leftOrbit"]["y"]) == (75, 345)
    assert "x" not in by["startButton"]
    # unused switches are left out
    assert not {"unused_24", "TBD39", "SD2"} & set(by)
    assert by["scoop"]["nc"] and not by["leftOrbit"]["nc"]
    assert [by[n]["group"] for n in ("flipperLwL", "coin1", "leftOrbit", "trough1", "shooter")] == [
        "Cabinet", "Cabinet", "Playfield", "Trough", "Trough"]
    # both left flippers on one key; flippers hold, Start taps
    assert by["flipperLwL"]["key"] == by["flipperMwL"]["key"] == "LShift"
    assert by["flipperLwL"]["hold"] and not by["startButton"]["hold"]
    assert (by["startButton"]["key"], by["coin1"]["key"], by["ActionButton"]["key"]) == ("1", "5", "Space")
    assert (t["shooter"], t["coin_door"]) == (55, 9)


def test_apswitches_writes_switches_json(tmp_path):
    pytest.importorskip("yaml")
    rig, build = _build(tmp_path)
    out = subprocess.run([sys.executable, str(RIG / "apswitches.py"), str(rig), str(build), "LoV"],
                         check=True, capture_output=True, text=True,
                         env=dict(os.environ, AP_ROOT=str(tmp_path / "root"))).stdout
    assert "11 switches, 2 on the playfield picture (the game's own layout)" in out
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
    (old / "machine_dir").write_text("legends")
    new = root / "cache" / "lov_26.08.22"
    new.mkdir()
    (new / "machine_dir").write_text("legends")
    # nothing kept yet: another cached build of the title lends its layout
    t = aps.table(str(rig), str(new), root=str(root))
    by = {s["name"]: s for s in t["switches"]}
    assert (by["leftOrbit"]["x"], by["leftOrbit"]["y"]) == (75, 345)
    assert "lov_25.08.27" in t["art_from"]
    # ...and is kept: with the old build deleted, the kept copy answers
    import shutil
    shutil.rmtree(old)
    t = aps.table(str(rig), str(new), root=str(root))
    assert t["art"] == str(root / "layouts" / "legends" / "playfield.jpg")
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
    assert ctl.run(["sw", "99", "1"])["ok"] is False          # not this machine's
    assert (rig / "input").read_text().splitlines() == [
        "0 close", "0 open", "8 tap 150", "55 open", "!drain"]


def test_apctl_state_is_what_the_game_has_active_plus_what_it_holds(tmp_path, monkeypatch):
    ctl, rig = _ctl(tmp_path, monkeypatch)
    (rig / "active").write_text("48 55\n")
    ctl.run(["sw", "0", "1"])
    st = ctl.run(["state"])
    assert st["up"] is True and st["held"] == [0]
    assert st["switches"] == {"0": 1, "48": 1, "55": 1}
    (rig / "game.pid").write_text("999999999\n")
    assert ctl.run(["state"])["up"] is False


def test_appf_page_model_groups_and_keys(tmp_path):
    pytest.importorskip("yaml")
    aps = _load("apswitches", RIG / "apswitches.py")
    rig, build = _build(tmp_path)
    appf = _load("appf", RIG / "appf.py")
    m = appf.page_model(aps.table(str(rig), str(build), root=str(tmp_path / "root")),
                        "Legends of Valhalla")
    assert [r["group"] for r in m["switches"]][:1] == ["Cabinet"]
    assert [r["group"] for r in m["switches"]][-1] == "Trough"
    by = {r["name"]: r for r in m["switches"]}
    assert by["flipperLwL"]["key"] == "Z" and "KeyZ" in by["flipperLwL"]["codes"]
    assert by["flipperLwR"]["key"] == "/" and "ShiftRight" in by["flipperLwR"]["codes"]
    assert by["startButton"]["codes"] == ["Digit1", "Numpad1"]
    assert by["leftOrbit"]["placed"] and not by["startButton"]["placed"]
    assert by["scoop"]["opto"]
    assert (m["shooter"], m["coin_door"]) == (55, 9)
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
