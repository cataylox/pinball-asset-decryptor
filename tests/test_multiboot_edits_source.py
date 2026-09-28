"""PAD-241: a multi-boot image given as a BASE CARD PLUS AN EDITS FOLDER (an override set).

What this file proves on Windows, over the tiny ext4 fixture wrapped in a card table: the
composite's games tree - its manifest, and the bytes the store writes from it - is the same
as a copy of the base card with the same edits patched in place (what Write produces); the
source spec and its refusals; the stamps that keep an update from taking the composite for
its base.  The loop-mounted build of a real card, and the emulator boot, are the machine's.
"""
import gzip
import json
import os
import shutil
import struct
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu")
if RIG not in sys.path:
    sys.path.insert(0, RIG)
import editsource  # noqa: E402
import mkmulticard as mk  # noqa: E402
import treesync as ts  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "treesync_tiny.ext4.gz")
P3_LBA = 2048


def _card(path):
    """A card file: an MBR with p1 (a stub), p2 (a stub) and p3 = the tiny ext4 at P3_LBA."""
    with gzip.open(FIXTURE, "rb") as g:
        fs = g.read()
    mbr = bytearray(512)
    for i, (t, st, cnt) in enumerate([(0x0C, 64, 64), (0x83, 128, 1024), (0x83, P3_LBA, len(fs) // 512)]):
        e = 0x1BE + 16 * i
        mbr[e + 4] = t
        struct.pack_into("<II", mbr, e + 8, st, cnt)
    mbr[510:512] = b"\x55\xaa"
    with open(path, "wb") as f:
        f.write(bytes(mbr))
        f.seek(P3_LBA * 512)
        f.write(fs)
    return str(path)


def _reader(card):
    from pinball_decryptor.plugins.stern import ext4
    f = open(card, "rb")
    return f, ext4.Ext4Reader(f, P3_LBA * 512, 4 << 20)


def _patch_in_place(card, rel, off, data):
    """What Write does to a card: the edit's bytes written over the file's own blocks."""
    f, r = _reader(card)
    with f:
        node = r.read_inode(editsource.lookup(r, rel))
        runs = r.disk_ranges(node, off, len(data))
    with open(card, "r+b") as o:
        pos = 0
        for disk, n in runs:
            o.seek(disk)
            o.write(data[pos:pos + n])
            pos += n


def _edits(base, folder, edits, **manifest):
    """An override set as write_overrides lays it down: each touched file whole (the base's
    bytes with the edit on top) under its games-partition path, and overrides.json."""
    os.makedirs(folder, exist_ok=True)
    f, r = _reader(base)
    records = []
    with f:
        for rel, (off, data) in edits.items():
            node = r.read_inode(editsource.lookup(r, rel))
            buf = bytearray(r.read_file_bytes(node))
            buf[off:off + len(data)] = data
            dest = os.path.join(folder, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as o:
                o.write(buf)
            st = os.stat(dest)
            records.append({"path": "/" + rel, "size": st.st_size, "mtime": int(st.st_mtime),
                            "ranges": [[off, len(data)]]})
    st = os.stat(base)
    card = {"path": os.path.abspath(base), "size": st.st_size, "mtime": int(st.st_mtime)}
    m = {"version": editsource.VERSION, "generation": os.urandom(6).hex(), "parent": "", "card": card,
         "run_card": dict(card), "files": records, "removed": []}
    m.update(manifest)
    with open(os.path.join(folder, editsource.MANIFEST), "w") as o:
        json.dump(m, o)
    return str(folder)


EDIT_A = {"d/multi.bin": (4096, b"SONG-SET-A" * 50), "d/sub/one.txt": (0, b"A")}
EDIT_B = {"d/multi.bin": (700000, b"song set b " * 90)}


@pytest.fixture()
def cards(tmp_path, monkeypatch):
    monkeypatch.setenv(ts.CACHE_ENV, str(tmp_path / "cache"))
    editsource._CHECKED.clear()
    base = _card(tmp_path / "stock.raw")
    return tmp_path, base


def _variant(tmp_path, base, name, edits):
    """The full variant image: a copy of the base with the edits patched in place."""
    out = str(tmp_path / name)
    shutil.copyfile(base, out)
    for rel, (off, data) in edits.items():
        _patch_in_place(out, rel, off, data)
    return out


def test_the_override_shape_is_the_apps():
    from pinball_decryptor.plugins.stern import engine
    assert editsource.VERSION == engine.OVERRIDE_VERSION
    assert editsource.MANIFEST == engine.OVERRIDE_MANIFEST


def test_the_spec_splits_only_when_both_halves_are_there(cards, tmp_path):
    _tmp, base = cards
    ed = _edits(base, str(tmp_path / "songs+a"), EDIT_A)
    spec = editsource.join(base, ed)
    assert editsource.split(spec) == (base, ed)          # a '+' inside the folder's own name
    assert editsource.split(base) is None
    assert editsource.base_of(spec) == base and editsource.base_of(base) == base
    odd = str(tmp_path / "a+b.raw")                       # a card with a '+' in its name is a card
    shutil.copyfile(base, odd)
    assert editsource.split(odd) is None
    assert editsource.split(base + "+" + str(tmp_path / "nowhere")) is None
    with pytest.raises(mk.Refused, match="not an edits folder"):
        mk.refuse_broken_pair(base + "+" + str(tmp_path))
    with pytest.raises(mk.Refused, match="no such card image"):
        mk.refuse_broken_pair(str(tmp_path / "gone.raw") + "+" + ed)


def test_the_composite_tree_is_the_patched_cards(cards):
    """THE CLAIM: one stock card + an edits folder describes, and writes, the same games tree
    as a whole variant image built from the same edits."""
    tmp_path, base = cards
    for name, edits in (("a", EDIT_A), ("b", EDIT_B)):
        spec = editsource.join(base, _edits(base, str(tmp_path / ("songs_" + name)), edits))
        full = _variant(tmp_path, base, "variant_%s.raw" % name, edits)
        comp_man, _h = mk.source_tree(spec)
        full_man, _h = mk.source_tree(full)
        assert comp_man.tree == full_man.tree
        base_man, _h = mk.source_tree(base)
        assert comp_man.tree != base_man.tree
        changed = {r for r in comp_man.tree.files if comp_man.tree.files[r] != base_man.tree.files[r]}
        assert changed == set(edits)
        # ...and the bytes the store would write from each, file for file
        outs = []
        for src in (spec, full):
            man, _h = mk.source_tree(src)
            ops = ts.MemOps()
            f, r = mk.open_source(src)
            with f:
                if not man.tree.inodes:
                    for rel, kind, ino, _n in r.iter_tree(2):
                        if kind == "file":
                            man.tree.inodes[rel] = ino
                ts.apply_changes(ops, "", ts.diff_tree(None, man.tree), man.tree, ts.ReaderSource(r, man.tree))
            outs.append({rel: ops.read(rel) for rel in man.tree.files})
        assert outs[0] == outs[1]


def test_the_edited_files_read_through_every_reader_call(cards):
    tmp_path, base = cards
    spec = editsource.join(base, _edits(base, str(tmp_path / "songs_a"), EDIT_A))
    f, r = mk.open_source(spec)
    with f:
        node = r.read_inode(editsource.lookup(r, "d/sub/one.txt"))
        whole = r.read_file_bytes(node)
        assert whole.startswith(b"A") and len(whole) == node["size"] == 18
        assert b"".join(b for _o, b in r.read_file_chunks(node)) == whole
        assert r.read_range(node, 1, 4) == whole[1:5]
        with pytest.raises(editsource.EditsError):
            r.disk_ranges(node, 0, 1)
        plain = r.read_inode(editsource.lookup(r, "d/uid1000.txt"))
        assert r.disk_ranges(plain, 0, 1)                  # an untouched file is the base's own


def test_stamps_tell_the_composite_from_its_base_and_from_other_edits(cards):
    tmp_path, base = cards
    a = editsource.join(base, _edits(base, str(tmp_path / "songs_a"), EDIT_A))
    b = editsource.join(base, _edits(base, str(tmp_path / "songs_b"), EDIT_B))
    sa, sb, s0 = ts.source_stamp(a), ts.source_stamp(b), ts.source_stamp(base)
    assert not ts.stamps_equal(sa, s0) and not ts.stamps_equal(sa, sb)
    assert ts.stamps_equal(sa, ts.source_stamp(a))
    assert mk.source_exists(a) and not mk.source_exists(base + "+" + str(tmp_path))
    assert mk.default_title(a) == "songs_a"


@pytest.mark.parametrize("change, why", [
    (lambda m, d: m.update(version=editsource.VERSION + 1), "newer version"),
    (lambda m, d: m.update(version=1), "older version"),
    (lambda m, d: m.update(building=True), "never finished"),
    (lambda m, d: m["card"].update(size=m["card"]["size"] + 512), "different card"),
    (lambda m, d: m["card"].update(mtime=m["card"]["mtime"] - 5), "different card"),
    (lambda m, d: m["run_card"].update(path="built.raw", size=1), "run over another card"),
    (lambda m, d: m.update(modes={"added": ["x"]}), "custom modes"),
    (lambda m, d: m.update(files=[]), "no edited files"),
    (lambda m, d: os.remove(os.path.join(d, "d", "multi.bin")), "missing"),
    (lambda m, d: open(os.path.join(d, "d", "multi.bin"), "ab").write(b"x"), "not the file"),
])
def test_what_is_refused(cards, change, why):
    tmp_path, base = cards
    ed = _edits(base, str(tmp_path / "songs"), EDIT_A)
    path = os.path.join(ed, editsource.MANIFEST)
    with open(path) as f:
        m = json.load(f)
    change(m, ed)
    with open(path, "w") as f:
        json.dump(m, f)
    with pytest.raises(mk.Refused, match=why):
        mk.edits_set(editsource.join(base, ed))


def test_a_set_naming_a_file_the_base_lacks_is_refused(cards):
    tmp_path, base = cards
    ed = _edits(base, str(tmp_path / "songs"), EDIT_A)
    os.makedirs(os.path.join(ed, "d", "new"))
    with open(os.path.join(ed, "d", "new", "x.bin"), "wb") as f:
        f.write(b"x")
    path = os.path.join(ed, editsource.MANIFEST)
    with open(path) as f:
        m = json.load(f)
    st = os.stat(os.path.join(ed, "d", "new", "x.bin"))
    m["files"].append({"path": "/d/new/x.bin", "size": 1, "mtime": int(st.st_mtime), "ranges": []})
    with open(path, "w") as f:
        json.dump(m, f)
    with pytest.raises(mk.Refused, match="not a file on"):
        mk.source_tree(editsource.join(base, ed))


def test_composites_build_the_compact_layout_and_never_as_the_primary(cards):
    tmp_path, base = cards
    spec = editsource.join(base, _edits(base, str(tmp_path / "songs_a"), EDIT_A))
    assert mk.resolve_layout("auto", 1, edits=1) == "store"
    assert mk.resolve_layout("auto", 1) == "parts"
    for lay in ("parts", "multi"):
        with pytest.raises(mk.Refused, match="--layout store"):
            mk.resolve_layout(lay, 2, edits=1)
    with pytest.raises(mk.Refused, match="whole card image"):
        mk.make_plan(spec, [base])
    assert mk.count_edits([base, spec]) == 1


def test_the_output_guard_covers_both_halves(cards):
    tmp_path, base = cards
    ed = _edits(base, str(tmp_path / "songs_a"), EDIT_A)
    with pytest.raises(mk.Refused, match="also an input"):
        mk.check_output_path(base, [editsource.join(base, ed)], force=True)


def test_the_version_read_sees_the_edited_tree(cards, monkeypatch):
    """read_tree reads a composite through its edits: a set that rewrites a file the version
    comes from is what the version table reports (here: the reader, via tree_root_inode)."""
    tmp_path, base = cards
    spec = editsource.join(base, _edits(base, str(tmp_path / "songs_a"), EDIT_A))
    seen = {}

    def fake_game(r, root):
        node = r.read_inode(editsource.lookup(r, "d/sub/one.txt"))
        seen["bytes"] = r.read_file_bytes(node)
        raise mk.Refused("no game here")
    monkeypatch.setattr(mk, "tree_game", fake_game)
    with pytest.raises(mk.Refused):
        mk.read_tree(spec, mk.source_part(spec))
    assert seen["bytes"].startswith(b"A")
