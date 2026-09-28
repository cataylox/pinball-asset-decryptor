"""PAD-251: a Spike 2 ``scene.radium`` read as the tree the game reads, and written back.

The Scenes preview drew Godzilla's Battle Select "all over the place" because
``scene_layout`` scans for byte patterns.  :mod:`scene_tree` walks the whole file with the
grammar the game reads (``scene_write``'s, measured with ``modes/scenelog.c``) plus what the
census of every stock card found: the per-node colour track, timeline events, ``Shape``,
``StreamingFlipbook``, ``Spine``, a Text's list of font sizes.  Measured: all 7,274 scenes on
49 stock Spike 2 cards walk to their last byte and come back byte for byte
(``scripts/pad251_scene_census.py``).

What has to hold, and is tested here:

* every structure reads into the model and an unedited scene serialises byte for byte;
* a writer that RE-ORDERS or DELETES emits each shared definition (class, object, texture)
  where its id first occurs in the new order, so the result still parses;
* anything that does not walk to the last byte is refused, never half-read;
* on the real Godzilla scenes (skipped when the extracted files are absent), Battle Select's
  tree is the screen the player sees.
"""
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import scene_tree as T

FLAG = 0x80000000


# ---------------------------------------------------------------------------------------------
# a tiny emitter for the synthetic scene (independent of scene_tree's writer)
# ---------------------------------------------------------------------------------------------
def u8(v):
    return struct.pack("<B", v)


def u32(v):
    return struct.pack("<I", v)


def u64(v):
    return struct.pack("<Q", v)


def fs(*v):
    return struct.pack("<%df" % len(v), *v)


def s(t):
    b = t.encode("latin1") if isinstance(t, str) else t
    return u64(len(b)) + b


def mat(sx=1.0, tx=0.0, ty=0.0):
    return fs(sx, 0, 0, 0, 0, sx, 0, 0, 0, 0, 1, 0, tx, ty, 0, 1)


def cls(cid, name=None):
    return u32(FLAG | cid) + s(name) if name else u32(cid)


def node(nid, name, comps, kf=((1, 1),), colors=(), tracks=((1, mat()),), events=()):
    out = u32(FLAG | nid) + s(name) + u32(1)
    out += u64(len(kf)) + b"".join(u32(f) + u8(v) for f, v in kf)
    out += u64(len(colors)) + b"".join(u32(f) + fs(*m) + fs(*a) for f, m, a in colors)
    out += u64(len(tracks)) + b"".join(u32(f) + m for f, m in tracks)
    out += u64(len(comps)) + b"".join(comps)
    out += u64(len(events))
    for fr, calls in events:
        out += u32(fr) + u64(len(calls))
        for name_, args in calls:
            out += s(name_) + u64(len(args)) + b"".join(s(a) for a in args)
    return out


def sprite(sym, name, frames, kids, labels=()):
    return (u32(sym) + s(name) + u32(frames) + u64(len(kids)) + b"".join(kids) + u64(0)
            + u64(len(labels)) + b"".join(s(n) + u32(f) for n, f in labels))


def texture(tid, w=8, h=4, blob=None):
    blob = blob if blob is not None else bytes(range(16)) * 2
    return u32(FLAG | tid) + u32(w) + u32(h) + u32(5) + s("") + u32(len(blob)) + blob


def bitmap(sym, w, h, tex):
    return u32(sym) + s("") + u32(w) + u32(h) + tex


def text(sym, string, used=(9,)):
    return (u32(sym) + s("") + fs(-2, -2, 200, 40) + fs(1, 1, 1, 1) + u8(1) + u8(1) + u32(1)
            + fs(2, 0) + s(string) + u32(used[0]) + u64(1) + s("GameFont") + u32(used[0])
            + u64(len(used)) + b"".join(u32(x) for x in used) + u8(0) + u32(0))


def scene():
    """A scene with one of every structure.  Returns the bytes."""
    lib = [
        u32(3) + cls(1, "Bitmap") + u32(FLAG | 10) + bitmap(3, 8, 4, texture(20)),
        u32(4) + cls(2, "Sprite") + u32(FLAG | 11) + sprite(4, "", 2, [
            node(40, "Frame_Art", [u32(1) + cls(1) + u32(10)])],
            labels=[("Locked", 1), ("Open", 2)]),
    ]
    root_kids = [
        # a picture with a fade (colour track) and a script event
        node(50, "Art",
             [u32(1) + cls(1) + u32(FLAG | 12) + bitmap(3, 16, 8, texture(21, 16, 8))],
             kf=((1, 1), (10, 0)), colors=((1, (0.5,) * 4, (0,) * 4), (5, (1,) * 4, (0,) * 4)),
             tracks=((1, mat(0.8, 100, 50)), (5, mat(1.0, 110, 50))),
             events=((3, [("SetAnimation", ["Sweep", "24"])]),)),
        # the library's Sprite placed twice (a shared object)
        node(51, "Tile_1", [u32(1) + cls(2) + u32(11)], tracks=((1, mat(1, 10, 10)),)),
        node(52, "Tile_2", [u32(1) + cls(2) + u32(11)], tracks=((1, mat(1, 10, 200)),)),
        # a text drawing with two font sizes, and a shape with no fill and one with a picture
        node(53, "Title", [u32(1) + cls(3, "Text") + u32(FLAG | 13) + text(5, "KAIJU", (9, 7))]),
        node(54, "Box", [u32(1) + cls(4, "Shape") + u32(FLAG | 14) + u32(6) + s("")
                         + fs(0, 0, 1360, 768) + u32(0)]),
        node(55, "Fill", [u32(1) + cls(4) + u32(FLAG | 15) + u32(6) + s("") + fs(0, 0, 64, 64)
                          + u32(0x40000000) + u32(FLAG | 16) + bitmap(3, 64, 64, u32(20))]),
        # a flipbook: a Sprite, then frames (none, a new frame, the same frame again)
        node(56, "Flip", [u32(1) + cls(5, "StreamingFlipbook") + u32(FLAG | 17)
                          + sprite(7, "stream.Zap", 3, [], labels=[("Go", 1)]) + u32(20) + u32(10)
                          + u64(3) + u32(0)
                          + u32(FLAG | 18) + u32(20) + u32(10) + u32(5) + u32(FLAG | 19)
                          + s("16.asset") + u32(999) + u32(16) + mat(1, -10, -5)
                          + u32(18)]),
        # a Spine skeleton with one atlas page, and a video with a clip and a marker
        node(57, "Skel", [u32(1) + cls(6, "Spine") + u32(FLAG | 22) + u32(8) + s("spine.X")
                          + s('{"skeleton":{}}') + s("page.png\n") + u64(1) + texture(23)]),
        node(58, "Clip", [u32(1) + cls(7, "Video") + u32(FLAG | 24) + u32(9) + s("video.x")
                          + u32(1360) + u32(768) + u32(1) + u8(0)
                          + u64(1) + s("Intro") + u32(FLAG | 25) + s("2.asset/1.asset") + u32(77)
                          + u64(1) + s("Intro") + u32(FLAG | 26) + fs(30.0) + u64(1) + u32(5)
                          + s("Pause")]),
    ]
    root = sprite(2, "", 20, root_kids, labels=[("Start", 1), ("End", 20)])
    return (u8(1) + u64(len(lib)) + b"".join(lib) + u64(0)
            + u32(1360) + u32(768) + fs(30.0) + fs(0.2, 0.2, 0.2, 1.0) + root)


# ---------------------------------------------------------------------------------------------
def test_every_structure_reads_and_comes_back_byte_for_byte():
    data = scene()
    sc = T.parse(data)
    assert T.serialize(sc) == data
    assert sc.stage[:3] == (1360, 768, 30.0)
    assert sc.root["labels"] == [("Start", 1), ("End", 20)]
    by = {n.name: n for n, _p, _d in sc.walk(library=True)}
    staged = {n.name: p for n, p, _d in sc.walk()}
    assert staged["Frame_Art"].name == "Tile_1"         # a placed template draws its children
    art = by["Art"]
    assert art.keyframes == [(1, 1), (10, 0)]
    assert art.colors[0][1] == [0.5] * 4 and art.colors[1][0] == 5
    assert [t[1][12] for t in art.tracks] == [100.0, 110.0]
    assert art.events == [(3, [("SetAnimation", ["Sweep", "24"])])]
    assert by["Tile_1"].components[0].obj is by["Tile_2"].components[0].obj
    assert by["Frame_Art"].components[0].obj.kind == "Bitmap"
    title = by["Title"].components[0].obj.body
    assert title["text"] == b"KAIJU" and title["used"] == [9, 7]
    assert by["Box"].components[0].obj.body["bitmap"] is None
    assert by["Fill"].components[0].obj.body["bitmap"].body["tex"] == 20
    flip = by["Flip"].components[0].obj.body
    assert flip["labels"] == [("Go", 1)] and (flip["w"], flip["h"]) == (20, 10)
    assert flip["seq"][0] is None and flip["seq"][1] is flip["seq"][2]
    assert sc.assets[19] == ("16.asset", 999)
    assert by["Skel"].components[0].obj.body["pages"] == [23]
    assert sc.clips[25] == ("2.asset/1.asset", 77) and sc.markers[26][1] == [(5, "Pause")]
    assert sc.textures[21]["w"] == 16


def test_reordering_moves_each_definition_to_its_new_first_use():
    """Tile_2 before the library would not do (the library is always first), but the Fill
    shape's texture 20 is DEFINED in the library's first Bitmap; re-order the root so the
    Flip node - whose frame is new - comes first, and put Title last: all ids stay defined
    before use and the file parses to the same tree."""
    sc = T.parse(scene())
    kids = sc.root["kids"]
    sc.root["kids"] = [kids[6], kids[0], kids[2], kids[1]] + kids[4:6] + kids[7:] + [kids[3]]
    back = T.parse(T.serialize(sc))
    assert [n.name for n in back.root["kids"]] == [
        "Flip", "Art", "Tile_2", "Tile_1", "Box", "Fill", "Skel", "Clip", "Title"]
    assert T.serialize(back) == T.serialize(sc)


def test_deleting_the_node_that_defined_a_shared_object_moves_the_definition():
    """Two root nodes share object 12 (the Art picture): delete the first one and the second,
    formerly a bare reference, now carries the definition."""
    sc = T.parse(scene())
    art_obj = sc.root["kids"][0].components[0].obj
    twin = T.Node(60, "Twin", components=[T.Component(1, sc.class_id("Bitmap"), art_obj)],
                  tracks=[(1, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 5, 0, 1])])
    sc.root["kids"].append(twin)
    both = T.serialize(sc)
    assert both.count(u32(FLAG | 12)) == 1                       # defined once, then referenced
    del sc.root["kids"][0]
    alone = T.serialize(sc)
    back = T.parse(alone)
    assert back.root["kids"][-1].name == "Twin"
    assert back.root["kids"][-1].components[0].obj.body["w"] == 16
    assert alone.count(u32(FLAG | 12)) == 1


@pytest.mark.parametrize("damage", ["truncate", "trailing", "not_a_scene", "bad_ref"])
def test_anything_that_does_not_walk_exactly_is_refused(damage):
    data = scene()
    if damage == "truncate":
        data = data[:-3]
    elif damage == "trailing":
        data = data + b"\0"
    elif damage == "not_a_scene":
        data = b"\x02" + data[1:]
    else:                               # Tile_1's reference to the library Sprite -> undefined id
        at = data.index(s("Tile_1"))
        ref = data.index(u32(11), at)
        data = data[:ref] + u32(99) + data[ref + 4:]
    with pytest.raises(T.SceneTreeError):
        T.parse(data)


# ---------------------------------------------------------------------------------------------
# the real Godzilla scenes (LE 1.16), when extracted (c:\tmp\pad251\pull.py)
# ---------------------------------------------------------------------------------------------
REAL = os.environ.get("PAD_SCENE_DIR", r"c:\tmp\pad251")


def _real(name):
    path = os.path.join(REAL, name + ".radium")
    if not os.path.isfile(path):
        pytest.skip("stock scene not present: %s" % path)
    return open(path, "rb").read()


@pytest.mark.parametrize("name", ["cac32730", "32e6ae28", "762a9b99"])
def test_stock_godzilla_scenes_round_trip(name):
    data = _real(name)
    assert T.serialize(T.parse(data)) == data


def test_battle_select_is_the_screen_the_player_sees():
    sc = T.parse(_real("cac32730"))
    assert sc.stage[:3] == (1360, 768, 30.0)
    assert sc.root["frames"] == 308
    assert ("OverlayFadeIn_Start", 35) in sc.root["labels"]
    by = {}
    for n, parent, depth in sc.walk():
        by.setdefault(n.name, []).append((n, parent, depth))
    (sel, _p, _d), = by["CharacterSelect_Instance"]
    assert round(sel.tracks[0][1][0], 2) == 0.73
    labels = dict(sel.components[0].obj.body["labels"])
    assert labels["Ebirah_FadeIn_Start"] == 1 and labels["Gigan_FadeIn_Start"] == 16
    title = [n for n, _p, _d in by["Line1_Instance"]
             if n.components[0].obj.body["text"] == b"KAIJU BATTLE SELECT"][0]
    assert title.tracks[0][1][12:14] == pytest.approx([-144.4, -660.1], abs=0.5)
