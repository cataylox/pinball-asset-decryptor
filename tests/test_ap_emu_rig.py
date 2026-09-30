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
