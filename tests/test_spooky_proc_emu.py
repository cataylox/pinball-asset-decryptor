"""tools/spooky_emu/proc (PAD-269): the rig for Spooky's P-ROC titles (Rick
and Morty, Alice Cooper's Nightmare Castle) on tools/proc_emu's board.
The boot itself is proven in WSL (run_game.sh on the real .pkg files); this
pins what runs anywhere: the scripts, and prepare.py's unpacking of a build.
"""

import importlib.util
import os
import pathlib
import struct
import sys
import zipfile

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spooky_emu" / "proc"
SCRIPTS = ("sppath.sh", "setup.sh", "run_game.sh", "netns.sh", "killgame.sh", "shot.sh",
           "sw.sh", "status.sh", "bootcheck.sh", "prepare.py", "spprun.py")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


prepare = _load("spooky_proc_prepare", RIG / "prepare.py")


def test_rig_scripts_are_lf_and_complete():
    for name in SCRIPTS:
        data = (RIG / name).read_bytes()
        assert b"\r\n" not in data, name


def test_every_path_comes_from_sppath():
    # sppath.sh owns every path; the other scripts never hard-code the roots.
    for name in SCRIPTS:
        if name in ("sppath.sh", "prepare.py"):
            continue
        text = (RIG / name).read_text()
        assert "/var/tmp/pad_spkproc" not in text and "/var/tmp/pad_ap" not in text, name


def test_spprun_is_python2_source():
    # The games are Python 2.7; spprun.py runs inside them.  It must at least
    # parse (py2 and py3 share this syntax), and it never prints.
    src = (RIG / "spprun.py").read_text()
    compile(src, "spprun.py", "exec")
    assert "print" not in src


def test_every_title_has_a_profile():
    run = (RIG / "run_game.sh").read_text()
    for title in prepare.TITLES:
        assert "    %s) DIR=" % title in run, title
    assert run.count("BALLS=\"eject=") == len(prepare.TITLES)


def test_the_keys_are_the_apps_own():
    from pinball_decryptor.plugins.spooky import games
    keys = prepare.keys()
    assert keys["RM_AES_KEY"] == games.RM_AES_KEY and keys["AC_AES_KEY"] == games.AC_AES_KEY


def test_titles_by_file_name():
    assert prepare.title_of("/x/rm-gamecode-20220902.pkg") == "rm"
    assert prepare.title_of("/x/ac-gamecode.pkg") == "ac"
    for other in ("tna-gamecode.pkg", "code_H78.pkg", "v2025.12.01.09.scooby"):
        with pytest.raises(SystemExit) as e:
            prepare.title_of("/x/" + other)
        assert e.value.code == 4


def _fake_pkg(tmp_path, name, members):
    zpath = tmp_path / "inner.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for member, data in members.items():
            z.writestr(zipfile.ZipInfo(member), data)
    pkg = tmp_path / name
    pkg.write_bytes(struct.pack("<Q", zpath.stat().st_size) + b"\0" * 16)
    return pkg, zpath


def _run(monkeypatch, tmp_path, pkg, zpath):
    monkeypatch.setattr(prepare, "SPP_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(prepare, "decrypt",
                        lambda src, out, key: pathlib.Path(out).write_bytes(zpath.read_bytes()))
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(pkg)])
    prepare.main()


def test_prepare_names_rick_and_morty_by_its_date(tmp_path, monkeypatch):
    pkg, zpath = _fake_pkg(tmp_path, "rm-gamecode-20220902.pkg", {
        "RMGame.pyc": b"\x03\xf3", "procgame/__init__.pyc": b"", "config/RM_PROTOTYPE1.yaml": ""})
    _run(monkeypatch, tmp_path, pkg, zpath)
    out = tmp_path / "cache" / "rm_20220902"
    assert (out / "title").read_text().strip() == "rm"
    assert (out / "RMGame.pyc").exists()
    assert sorted(os.listdir(tmp_path / "cache")) == ["rm_20220902"]     # no scratch, no zip


def test_prepare_names_alice_cooper_by_its_version(tmp_path, monkeypatch):
    pkg, zpath = _fake_pkg(tmp_path, "ac-gamecode.pkg", {
        "ACGame.py": "run", "WHATSNEW.txt": "File is in c:\\temp\n\nv1.1.0.5\n  fixes\nV1.1.0.4\n",
        "uptest/main.x86_64": b"\x7fELF"})
    _run(monkeypatch, tmp_path, pkg, zpath)
    out = tmp_path / "cache" / "ac_1.1.0.5"
    assert (out / "title").read_text().strip() == "ac"
    if os.name == "posix":
        assert os.access(out / "uptest" / "main.x86_64", os.X_OK)


def test_prepare_refuses_the_wrong_game_under_a_name(tmp_path, monkeypatch):
    pkg, zpath = _fake_pkg(tmp_path, "ac-gamecode.pkg", {"RMGame.pyc": b""})
    with pytest.raises(SystemExit, match="has no ACGame.py"):
        _run(monkeypatch, tmp_path, pkg, zpath)
    assert os.listdir(tmp_path / "cache") == []         # nothing left behind
