"""tools/dp_emu (PAD-263): the parts of the Dutch Pinball rig that can be
checked without WSL - finding /home on a disk image, laying update zips over
an installed version folder the way the machine's updater does, and reading
the build's keyboard.yaml into switch keys."""

import importlib.util
import os
import pathlib
import shutil
import struct
import zipfile

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "dp_emu"


def _load(name):
    spec = importlib.util.spec_from_file_location("dp_" + name, RIG / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


prepare = _load("prepare")
sw = _load("sw")


def _mbr(path, parts):
    """A disk image with an MBR partition table: parts = [(type, lba, sectors)]."""
    mbr = bytearray(512)
    for i, (typ, lba, count) in enumerate(parts):
        struct.pack_into("<B3xB3xII", mbr, 446 + 16 * i, 0, typ, lba, count)
    mbr[510:512] = b"\x55\xaa"
    path.write_bytes(bytes(mbr) + b"\0" * 512)


def test_partitions_mbr(tmp_path):
    img = tmp_path / "tbl.img"
    # The TBL image's own layout: /home is partition 3 at LBA 93823657.
    _mbr(img, [(0x83, 2048, 1024000), (0x83, 1026048, 92797609), (0x83, 93823657, 1000)])
    assert prepare.partitions(str(img)) == [
        (2048 * 512, 1024000 * 512),
        (1026048 * 512, 92797609 * 512),
        (93823657 * 512, 1000 * 512),
    ]


def test_partitions_gpt(tmp_path):
    img = tmp_path / "gpt.img"
    data = bytearray(512 * 40)
    struct.pack_into("<B3xB3xII", data, 446, 0, 0xEE, 1, 39)
    data[510:512] = b"\x55\xaa"
    struct.pack_into("<QII", data, 512 + 72, 2, 2, 128)        # entries at LBA 2
    entry = b"\x11" * 16 + b"\0" * 16 + struct.pack("<QQ", 34, 99)
    data[1024:1024 + len(entry)] = entry                        # second entry empty
    img.write_bytes(bytes(data))
    assert prepare.partitions(str(img)) == [(34 * 512, 66 * 512)]


def test_partitions_bare_filesystem(tmp_path):
    img = tmp_path / "ext4.img"
    img.write_bytes(b"\0" * 2048)
    assert prepare.partitions(str(img)) == [(0, 2048)]


def _update_zip(path, version, files, delta=None):
    with zipfile.ZipFile(path, "w") as z:
        for rel, data in files.items():
            z.writestr("%s/%s" % (version, rel), data)
        if delta is not None:
            z.writestr("%s/delta" % version, delta)
    return str(path)


def test_zip_version_reads_the_delta_marker(tmp_path):
    z = _update_zip(tmp_path / "u.zip", "1.15", {"start": b"x"}, "1.01,1.10,1.13")
    assert prepare.zip_version(z) == ("1.15", ["1.01", "1.10", "1.13"])
    full = _update_zip(tmp_path / "f.zip", "1.00", {"start": b"x"})
    assert prepare.zip_version(full) == ("1.00", [])


def _base_build(root):
    base = root / "cache" / "img"
    (base / "assets" / "display").mkdir(parents=True)
    (base / "assets" / "display" / "dot_shapes.png").write_bytes(b"png")
    v = base / "1.13"
    (v / "assets" / "fonts").mkdir(parents=True)
    (v / "start").write_bytes(b"old start")
    (v / "assets" / "fonts" / "only_installed.txt").write_bytes(b"kept")
    (base / "version").write_text("1.13")
    return base


@pytest.mark.skipif(os.name == "nt" or not shutil.which("cp"),
                    reason="the rig runs in WSL: cp -al and a symlink")
def test_zip_is_laid_over_the_installed_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "CACHE", str(tmp_path / "cache"))
    base = _base_build(tmp_path)
    z = _update_zip(tmp_path / "TBL-v1.15.zip", "1.15",
                    {"start": b"new start", "._start": b"appledouble"}, "1.12,1.13,1.14")
    out = pathlib.Path(prepare.from_zips([z], str(base), "zip-1.15"))
    assert (out / "version").read_text() == "1.15"
    assert (out / "1.15" / "start").read_bytes() == b"new start"
    # The file only the installed folder had is still there - the whole
    # point of laying the zip over it.
    assert (out / "1.15" / "assets" / "fonts" / "only_installed.txt").read_bytes() == b"kept"
    assert not (out / "1.15" / "._start").exists()
    # The base build was hard-linked, never written through.
    assert (base / "1.13" / "start").read_bytes() == b"old start"
    assert os.path.realpath(out / "assets") == os.path.realpath(base / "assets")


def test_zip_that_does_not_install_onto_the_base_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "CACHE", str(tmp_path / "cache"))
    base = _base_build(tmp_path)
    z = _update_zip(tmp_path / "TBL-v1.10.zip", "1.10", {"start": b"s"}, "0.92,1.00,1.01")
    with pytest.raises(SystemExit):
        prepare.from_zips([z], str(base), "bad")
    assert not (tmp_path / "cache" / "bad").exists()


def test_keymap_from_keyboard_yaml(tmp_path, monkeypatch):
    rig = tmp_path / "rig0"
    cfg = rig / "game" / "1.15" / "config"
    cfg.mkdir(parents=True)
    (rig / "ver").write_text("1.15\n")
    # The shape of TBL's own file: BOM, comments, a name list, a keysym
    # number, and a coil map that must not be read as switches.
    (cfg / "keyboard.yaml").write_bytes(
        "﻿# The Big Lebowski Pinball keyboard configuration\n\n"
        "keyboard_switch_map:\n\n  # Start:\n  1: startButton\n  2: launchButton\n"
        "  274: launchButton\n  n: flipperLwL\n  m: flipperLwR,flipperUpR\n\n"
        "keyboard_coil_map:\n\n  276: flipperLwL\n".encode("utf-8"))
    monkeypatch.setattr(sw, "RIG", str(rig))
    assert sw.keymap() == {
        "startButton": ord("1"),
        "launchButton": ord("2"),
        "flipperLwL": ord("n"),
        "flipperLwR": ord("m"),
        "flipperUpR": ord("m"),
    }


dpswitches = _load("dpswitches")
dpctl = _load("dpctl")

MACHINE_YAML = """﻿# The Big Lebowski Pinball machine configuration

PRGame:
    machineType: pdb

PRSwitches:
    # **** Format ****
    #  ____
    trough2:
        title: 'Trough 2'
        label: 'FMB - J8 - Pin 5'
        number: SD0
        type:  'NC'
        machine_x: 458
        machine_y: 931
        machine_color: 0x92ce13
    startButton:
        title: 'Start Button'
        number: SD8
    leftSling:
        title: 'Left Slingshot'   # a comment
        number: 0/1
        machine_x: 100
        machine_y: 700

PRCoils:
    trough:
        number: A0-B0-0
"""

KEYBOARD_YAML = ("﻿# keys\n\nkeyboard_switch_map:\n\n  1: startButton\n"
                 "  n: flipperLwL\n\nkeyboard_coil_map:\n\n  276: flipperLwL\n")


def _version(tmp_path):
    v = tmp_path / "1.13"
    (v / "config").mkdir(parents=True)
    (v / "config" / "machine.yaml").write_text(MACHINE_YAML, encoding="utf-8")
    (v / "config" / "keyboard.yaml").write_text(KEYBOARD_YAML, encoding="utf-8")
    (v / "assets" / "display").mkdir(parents=True)
    (v / "assets" / "display" / "machine.png").write_bytes(b"png")
    return v


def test_machine_yaml_switches_in_file_order(tmp_path):
    v = _version(tmp_path)
    sw = dpswitches.read_switches(str(v / "config" / "machine.yaml"))
    assert [s["name"] for s in sw] == ["trough2", "startButton", "leftSling"]
    assert sw[0] == {"name": "trough2", "title": "Trough 2", "label": "FMB - J8 - Pin 5",
                     "number": "SD0", "nc": True, "x": 458, "y": 931}
    assert sw[1]["x"] is None and not sw[1]["nc"]
    assert sw[2]["title"] == "Left Slingshot" and sw[2]["number"] == "0/1"


def test_every_switch_gets_a_key_and_the_cache_is_not_written(tmp_path):
    v = _version(tmp_path)
    kb = v / "config" / "keyboard.yaml"
    cache_copy = tmp_path / "cache_keyboard.yaml"
    os.link(kb, cache_copy)                 # the rig's copy is a hard link
    out = tmp_path / "switches.json"
    dpswitches.main([str(v), str(out)])
    import json
    table = json.loads(out.read_text())
    assert [(s["n"], s["sym"], s["key"]) for s in table["switches"]] == [
        (0, 1000, ""), (1, 1001, "1"), (2, 1002, "")]
    assert table["art"].endswith("machine.png")
    text = kb.read_text(encoding="utf-8")
    # one mapping section, the rig's keys first, the shipped ones kept
    assert text.count("keyboard_switch_map:") == 1
    head = text.split("keyboard_coil_map:")[0]
    for line in ("  1000: trough2", "  1001: startButton", "  1002: leftSling",
                 "  1: startButton", "  n: flipperLwL"):
        assert line + "\n" in head
    # the hard-linked original (the cache) is untouched
    assert cache_copy.read_text(encoding="utf-8") == KEYBOARD_YAML
    # and sw.py's keymap still reads the shipped keys, not the rig's
    rig = tmp_path / "rig0"
    (rig / "game").mkdir(parents=True)
    os.symlink(v, rig / "game" / "1.13") if os.name != "nt" else shutil.copytree(v, rig / "game" / "1.13")
    (rig / "ver").write_text("1.13")
    old = sw.RIG
    try:
        sw.RIG = str(rig)
        assert sw.keymap() == {"startButton": ord("1"), "flipperLwL": ord("n")}
    finally:
        sw.RIG = old


class _Fifo:
    def __init__(self):
        self.lines = []


def test_dpctl_holds_taps_and_reports(tmp_path, monkeypatch):
    rig = tmp_path / "rig0"
    rig.mkdir()
    (rig / "switches.json").write_text(
        '{"switches": [{"n": 0, "sym": 1000}, {"n": 1, "sym": 1001}]}')
    ctl = dpctl.Ctl.__new__(dpctl.Ctl)
    ctl.rig = str(rig)
    ctl.held = set()
    ctl.syms = {0: 1000, 1: 1001}
    sent = []
    monkeypatch.setattr(ctl, "send", lambda line: sent.append(line) or True)
    monkeypatch.setattr(ctl, "up", lambda: True)
    assert ctl.run(["sw", "1", "1"]) == {"ok": True}
    assert ctl.run(["state"]) == {"up": True, "held": [1], "switches": {"1": 1}}
    assert ctl.run(["sw", "1", "0"]) == {"ok": True}
    assert ctl.run(["tap", "0", "90"]) == {"ok": True}
    assert sent == ["down 1001", "up 1001", "tap 1000 90"]
    assert ctl.run(["tap", "7"])["ok"] is False
    assert ctl.run(["bogus"])["ok"] is False


def test_dpctl_with_no_game_reading_says_so(tmp_path):
    rig = tmp_path / "rig0"
    rig.mkdir()
    ctl = dpctl.Ctl.__new__(dpctl.Ctl)
    ctl.rig, ctl.held, ctl.syms = str(rig), set(), {0: 1000}
    # no FIFO at all: nothing to write to, never a hang
    assert ctl.run(["tap", "0"]) == {"ok": False}
    assert ctl.run(["state"])["up"] is False


def test_ftd2xx_stub_is_a_loadable_32bit_dll_exporting_the_ordinals(tmp_path):
    stub = _load("ftd2xx_stub")
    data = stub.build()
    assert data[:2] == b"MZ"
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    machine, nsect = struct.unpack_from("<HH", data, pe + 4)
    chars = struct.unpack_from("<H", data, pe + 22)[0]
    assert machine == 0x14C and nsect == 1 and chars & 0x2000   # i386 DLL
    try:
        import pefile
    except ImportError:
        return
    p = pefile.PE(data=data)
    ords = {e.ordinal for e in p.DIRECTORY_ENTRY_EXPORT.symbols}
    # the ordinals Bride of Pinbot 2.0's pinproc.pyd imports
    assert {2, 3, 4, 6, 7, 18, 27, 28} <= ords
    assert p.DIRECTORY_ENTRY_EXPORT.name == b"FTD2XX.dll"
