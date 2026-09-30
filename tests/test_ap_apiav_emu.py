"""tools/ap_emu/apiav (PAD-265): the rig for the American Pinball titles whose
screens and sound come from AP's native `apiav` (Barry-O's BBQ Challenge on).
The boot itself is proven in WSL (run_game.sh on the real .pkg); this pins
what runs anywhere: the scripts, and prepare.py's unpacking of a build.
"""

import importlib.util
import os
import pathlib
import struct
import sys
import zipfile

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "ap_emu" / "apiav"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


prepare = _load("ap_apiav_prepare", RIG / "prepare.py")


def test_rig_scripts_are_lf_and_complete():
    for name in ("avpath.sh", "setup.sh", "run_game.sh", "netns.sh", "killgame.sh", "shot.sh",
                 "sw.sh", "status.sh", "prepare.py"):
        data = (RIG / name).read_bytes()
        assert b"\r\n" not in data, name


def test_every_path_comes_from_avpath():
    # avpath.sh owns every path; the other scripts never hard-code the root.
    for name in ("run_game.sh", "netns.sh", "killgame.sh", "shot.sh", "sw.sh", "status.sh",
                 "setup.sh"):
        assert "/var/tmp/pad_apav" not in (RIG / name).read_text(), name


def test_the_ap_key_is_the_apps_own():
    from pinball_decryptor.plugins.ap.games import AP_AES_KEY
    assert prepare.ap_key() == AP_AES_KEY


def _fake_build(tmp_path, members):
    zpath = tmp_path / "inner.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for name, data in members.items():
            info = zipfile.ZipInfo(name)
            if name == "apiav":
                info.external_attr = 0o100755 << 16
            z.writestr(info, data)
    pkg = tmp_path / "bbq-gamecode_24.07.04.pkg"
    pkg.write_bytes(struct.pack("<Q", zpath.stat().st_size) + b"\0" * 16)
    return pkg, zpath


def test_prepare_unpacks_a_build_and_names_its_title(tmp_path, monkeypatch):
    pkg, zpath = _fake_build(tmp_path, {
        "launcher.py": "run", "apiav": b"\x7fELF", "procgame/__init__.py": "",
        "bbq/assets/defs/screens.json": "{}", "bbq/._launcher.py": "x", ".DS_Store": "x",
        "__MACOSX/bbq/x": "x"})
    monkeypatch.setattr(prepare, "AV_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(prepare, "decrypt", lambda src, out: pathlib.Path(out).write_bytes(zpath.read_bytes()))
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(pkg)])
    prepare.main()
    out = tmp_path / "cache" / "bbq_24.07.04"
    assert (out / "title").read_text().strip() == "bbq"
    assert (out / "launcher.py").exists() and (out / "bbq/assets/defs/screens.json").exists()
    assert not (out / ".DS_Store").exists() and not (out / "bbq/._launcher.py").exists()
    assert not (out / "__MACOSX").exists()
    assert not (tmp_path / "cache" / "bbq_24.07.04.zip").exists()
    if os.name == "posix":
        assert os.access(out / "apiav", os.X_OK)


def test_prepare_refuses_a_build_without_apiav(tmp_path, monkeypatch):
    # Houdini .. Oktoberfest draw in-process (tools/ap_emu's own rig).
    pkg, zpath = _fake_build(tmp_path, {"houdini.py": "run", "procgame/__init__.py": ""})
    monkeypatch.setattr(prepare, "AV_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(prepare, "decrypt", lambda src, out: pathlib.Path(out).write_bytes(zpath.read_bytes()))
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(pkg)])
    with pytest.raises(SystemExit, match="not an apiav-era build"):
        prepare.main()
