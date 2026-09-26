"""PAD-222: which unpacker a Barrels of Fun PCK gets, and what the run says
when it could not unpack.

cooltoy's Labyrinth (January 2026 code, a stock Godot 4.5 pack) went to
GDRE Tools because the choice was made on ``is_may_format`` alone, and on a
Mac - where nothing installs GDRE Tools - the extract "succeeded" with an
empty pck/ folder.  The pack's own file directory is what the native
extractor reads, so it is preferred whenever it is there.
"""

import base64
import hashlib
import re
import struct

import pytest

from pinball_decryptor.plugins.bof import pipeline as bp
from pinball_decryptor.plugins.bof import manufacturer as bm


def _entries(files):
    body = bytearray()
    blob = bytearray()
    ofs = 0
    for path, data in files:
        praw = path + b"\x00" * (((len(path) + 3) // 4 * 4) - len(path))
        body += struct.pack("<I", len(praw)) + praw
        body += struct.pack("<QQ", ofs, len(data))
        body += hashlib.md5(data).digest() + struct.pack("<I", 0)
        blob += data
        ofs += len(data)
    return bytes(blob), bytes(body)


def _v3_binary(tmp_path, files, *, directory=True, name="GDCraze.x86_64"):
    """A Godot 4.5 binary: format v3 header, entries from ofs 0, and (unless
    *directory* is False) a plaintext directory at ``dir_offset``."""
    blob, body = _entries(files)
    base = 104
    hdr = bytearray(base)
    hdr[0:4] = b"GDPC"
    struct.pack_into("<I", hdr, 4, 3)
    struct.pack_into("<III", hdr, 8, 4, 5, 1)
    struct.pack_into("<I", hdr, 20, 2)
    struct.pack_into("<Q", hdr, 24, base)
    if directory:
        struct.pack_into("<Q", hdr, 32, base + len(blob))
        pck = bytes(hdr) + blob + struct.pack("<I", len(files)) + body
    else:
        pck = bytes(hdr) + blob
    binary = tmp_path / name
    binary.write_bytes(b"\x7fELF" + b"\x00" * 508 + pck
                       + struct.pack("<Q", len(pck)) + b"GDPC")
    return str(binary)


def _v2_binary(tmp_path, files, name="old.x86_64"):
    """A pre-4.5 stock pack: 96-byte header, then the u32 file_count and
    the directory right away (no dir_offset field)."""
    blob, body = _entries(files)
    hdr = bytearray(96)
    hdr[0:4] = b"GDPC"
    struct.pack_into("<I", hdr, 4, 2)
    struct.pack_into("<III", hdr, 8, 4, 3, 0)
    pck = bytes(hdr) + struct.pack("<I", len(files)) + body + blob
    binary = tmp_path / name
    binary.write_bytes(b"\x7fELF" + b"\x00" * 508 + pck
                       + struct.pack("<Q", len(pck)) + b"GDPC")
    return str(binary)


# Labyrinth's shape: a compiled script first, sounds and a clip after it.
_LABYRINTH = [
    (b"res://scripts/main.gdc", b"GDSC" + b"\x00" * 60),
    (b"res://.godot/imported/song.wav-abc.sample", b"RSRC" + b"\x01" * 40),
    (b"res://assets/videos/intro.ogv", b"OggS" + b"\x02" * 80),
]


def test_a_stock_45_pack_is_unpacked_from_its_own_directory(tmp_path):
    binary = _v3_binary(tmp_path, _LABYRINTH)
    from pinball_decryptor.plugins.bof.may_extractor import is_may_format
    with open(binary, "rb") as f:
        f.seek(512)
        head = f.read(200)
    assert not is_may_format(head), "the fixture must NOT look like May"
    which, detail = bp.pick_pck_unpacker(binary)
    assert which == "directory"
    assert "3 entries" in detail and "plaintext" in detail


def test_a_may_pack_without_a_directory_still_takes_the_may_path(tmp_path):
    binary = _v3_binary(
        tmp_path, [(b"res://a.ctex", b"GST2" + b"\x00" * 40)], directory=False)
    which, detail = bp.pick_pck_unpacker(binary)
    assert which == "may"


def test_an_old_pack_is_the_only_one_left_to_gdre(tmp_path):
    binary = _v2_binary(tmp_path, _LABYRINTH)
    which, detail = bp.pick_pck_unpacker(binary)
    assert which == "gdre"
    assert "no Godot 4.5 file directory" in detail


def test_an_unreadable_file_goes_to_gdre_with_the_reason(tmp_path):
    which, detail = bp.pick_pck_unpacker(str(tmp_path / "missing.x86_64"))
    assert which == "gdre"
    assert detail


class _FileExecutor:
    """Answers the two header sniffs (`tail -c N file | base64` and
    `tail -c $((N + 12)) file | head -c M | base64`) from a local file,
    the way WSL or a Mac shell would."""

    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()

    def run(self, cmd, timeout=120):
        m = re.match(r"tail -c (?:\$\(\((\d+) \+ 12\)\)|(\d+)) .*?"
                     r"(?:\| head -c (\d+) )?\| base64$", cmd)
        assert m, cmd
        n = int(m.group(1)) + 12 if m.group(1) else int(m.group(2))
        out = self.data[-n:]
        if m.group(3):
            out = out[:int(m.group(3))]
        return base64.b64encode(out).decode()


def _write_pipeline(executor):
    p = bp.ModifyPipeline.__new__(bp.ModifyPipeline)
    p.executor = executor
    return p


def test_write_sees_the_directory_the_same_way_through_the_shell(tmp_path):
    binary = _v3_binary(tmp_path, _LABYRINTH)
    p = _write_pipeline(_FileExecutor(binary))
    assert p._detect_may_format(binary) is False
    assert p._detect_v3_directory(binary) is True


def test_write_leaves_an_old_pack_to_gdre(tmp_path):
    binary = _v2_binary(tmp_path, _LABYRINTH)
    p = _write_pipeline(_FileExecutor(binary))
    assert p._detect_v3_directory(binary) is False


def test_missing_gdre_is_spelled_per_desktop(monkeypatch):
    monkeypatch.setattr(bp, "_mac_gdre_binary",
                        lambda: "/Users/x/.local/share/gdre_tools/Godot RE Tools")
    mac = bp.missing_gdre_text("darwin", "no Godot 4.5 file directory")
    assert "not installed on this Mac" in mac
    assert "/Users/x/.local/share/gdre_tools/Godot RE Tools" in mac
    assert "older Godot pack" in mac
    win = bp.missing_gdre_text("win32", "no Godot 4.5 file directory")
    assert "Install Missing" in win
    assert "Mac" not in win


def test_the_mac_gdre_prefix_names_the_same_binary(monkeypatch):
    monkeypatch.setattr(bp, "_platform", lambda: "darwin")
    monkeypatch.setattr(bp, "_mac_gdre_binary", lambda: "/tmp/gdre/Godot RE Tools")
    p = bp.DecryptPipeline.__new__(bp.DecryptPipeline)
    assert "'/tmp/gdre/Godot RE Tools' --headless" in p._gdre_prefix()


def test_the_gdre_row_says_current_code_needs_none():
    row = {p.name: p for p in bm.build_prerequisites("darwin")}["gdre_tools"]
    assert row.where == "wsl"
    assert "natively" in row.reason
    assert "Labyrinth" in row.reason
