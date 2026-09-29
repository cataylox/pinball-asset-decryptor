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
