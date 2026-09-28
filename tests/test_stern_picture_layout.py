"""PAD-251: move and resize a PICTURE a Spike 2 scene draws.

A modder asked to lay out Godzilla's Battle Select and HUD art the way the
Scenes window already lays out a line of text: X/Y and size.  A picture's
place, size and tilt are its sprite node's track MATRICES (64-byte
column-major 4x4, ``scene_write.matrix``), so a move or resize is a
size-neutral rewrite of the scene, the same shape as a text layout edit.

What has to hold, and is tested here:

* only WHOLE 2-D matrices before the node's picture triple are found: the
  ``1.0, 0.0`` pair the preview anchors on also sits in bytes that are no
  matrix (two of every three hits in a real Battle Select portrait node);
* a move adds dx/dy to every matrix of every node drawing the picture, and
  nothing else in the file changes;
* a resize scales the 2x2 about the picture's CENTRE, tilted banners included;
* the Write side resolves a ``picture:<rel>`` row through the extract's
  ``radium_images.txt``, and a card that has no picture there is a warning,
  never a write;
* the Scenes preview draws a pending picture edit.

Measured on stock Godzilla LE 1.16's Battle Select scene (cac32730...): 24
pictures, every one placed by nodes whose matrices pass the check, including
the banners' 0.797-scale tilt.
"""
import struct

import pytest

np = pytest.importorskip("numpy")
from PIL import Image                                               # noqa: E402

from pinball_decryptor.plugins.stern import (                       # noqa: E402
    engine, radium, scene_layout, scene_render, scene_write, text_layout)
from tests.test_stern_image_grow import _record                     # noqa: E402
from tests.test_stern_scene_render import (                         # noqa: E402
    _image_ref, _s_instance, _sprite_scene, _stage)
from tests.test_stern_text_colors import _FakeReader, _s            # noqa: E402

CARD = "/godzilla_le/assets/lcd/auto_loaded/cac32730/scene.radium"
BANNER_REL = "scene_textures/radimg_40x20_aaaa0001.png"
ICON_REL = "scene_textures/radimg_16x16_bbbb0002.png"


def _m_instance(name, x, y, ref, sx=1.0, rot=0.0):
    """A sprite node the way the machine writes one: name, flag words, a
    track (u32 key + a whole matrix), then the triple naming its picture."""
    import math
    c, s = math.cos(rot) * sx, math.sin(rot) * sx
    m = struct.pack("<16f", c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, x, y, 0, 1)
    return (_s(name) + struct.pack("<9I", *([1] * 9))
            + struct.pack("<I", 1) + m + ref)


def _scene(rot=0.0):
    """A 40x20 banner (shown 38x18) drawn by two nodes, a 16x16 icon by one.
    Returns ``(bytes, banner_off, icon_off)``."""
    head = bytearray(b"\x7f" * 8)
    head += _record(40, 20, 2, disp=(38, 18))
    banner = 8 + 36
    head += b"\x7f" * 4
    icon = len(head) + 36
    head += _record(16, 16, 4, rgba=(200, 30, 30, 255))
    tail = bytearray(_stage())
    tail += _m_instance("Banner", 100.0, 50.0, _image_ref(38, 18, 2),
                        sx=0.8, rot=rot)
    tail += _m_instance("Icon", 300.0, 60.0, _image_ref(16, 16, 4))
    tail += _m_instance("BannerAgain", 100.0, 400.0, _image_ref(38, 18, 2))
    return bytes(head) + bytes(tail), banner, icon


def _parse(data):
    imgs = engine.parse_radium_images(data)
    return imgs, radium.parse_glyph_tables(data, imgs)


def _apply(data, patches):
    buf = bytearray(data)
    for off, payload in patches:
        buf[off:off + len(payload)] = payload
    return bytes(buf)


def _matrices(data, off):
    imgs, tables = _parse(data)
    nodes = scene_layout.picture_layout_offsets(data, imgs, tables)[off]
    return [m for nd in nodes for _at, m in nd["tracks"]]


def _centre(m, w, h):
    return (m[12] + m[0] * w / 2 + m[4] * h / 2,
            m[13] + m[1] * w / 2 + m[5] * h / 2)


# ---------------------------------------------------------------------------
# where a picture's layout lives
# ---------------------------------------------------------------------------

def test_every_node_drawing_a_picture_is_found_with_its_matrix():
    data, banner, icon = _scene()
    imgs, tables = _parse(data)
    got = scene_layout.picture_layout_offsets(data, imgs, tables)
    assert sorted(got) == [banner, icon]
    assert [(nd["w"], nd["h"], len(nd["tracks"])) for nd in got[banner]] == \
        [(38, 18, 1), (38, 18, 1)]
    for nd in got[banner] + got[icon]:
        (at, m), = nd["tracks"]
        assert list(struct.unpack_from("<16f", data, at)) == m
    assert [m[12:14] for m in _matrices(data, banner)] == \
        [[100.0, 50.0], [100.0, 400.0]]


def test_a_lookalike_that_is_no_whole_matrix_is_never_listed():
    """The preview's own fixture carries only the ``1.0, 0.0, x, y`` quad
    the position is read from; nothing there is a matrix to rewrite."""
    head = bytearray(b"\x7f" * 8) + _record(40, 20, 2, disp=(38, 18))
    tail = _sprite_scene([]) + _s_instance(
        "Banner", 100.0, 50.0, image_ref=_image_ref(38, 18, 2))
    data = bytes(head) + tail
    imgs, tables = _parse(data)
    assert scene_layout.parse_scene_layout(data, imgs, tables)["sprites"]
    assert scene_layout.picture_layout_offsets(data, imgs, tables) == {}
    assert scene_layout.picture_layout_patches(
        data, imgs, {44: {"dx": 5}}, tables)[:2] == ([], 0)


# ---------------------------------------------------------------------------
# the patches
# ---------------------------------------------------------------------------

def test_a_move_shifts_every_node_of_that_picture_and_nothing_else():
    data, banner, icon = _scene()
    imgs, tables = _parse(data)
    patches, n, notes = scene_layout.picture_layout_patches(
        data, imgs, {banner: {"dx": 12, "dy": -7}}, tables)
    assert (n, notes, len(patches)) == (1, [], 2)
    assert all(len(p) == 64 for _o, p in patches)
    new = _apply(data, patches)
    assert len(new) == len(data)
    assert [m[12:14] for m in _matrices(new, banner)] == \
        [[112.0, 43.0], [112.0, 393.0]]
    assert _matrices(new, icon) == _matrices(data, icon)
    before = {s["name"]: (s["x"], s["y"]) for s in
              scene_layout.parse_scene_layout(data, imgs, tables)["sprites"]}
    after = {s["name"]: (s["x"], s["y"]) for s in
             scene_layout.parse_scene_layout(new, *_parse(new))["sprites"]}
    assert after["Icon"] == before["Icon"]
    assert after["Banner"] == pytest.approx(
        (before["Banner"][0] + 12, before["Banner"][1] - 7))


@pytest.mark.parametrize("rot", [0.0, -0.0875])
def test_a_resize_scales_about_the_centre_tilted_or_not(rot):
    data, banner, _icon = _scene(rot=rot)
    imgs, tables = _parse(data)
    patches, n, _notes = scene_layout.picture_layout_patches(
        data, imgs, {banner: {"size": 150}}, tables)
    assert n == 1
    old = _matrices(data, banner)
    new = _matrices(_apply(data, patches), banner)
    for a, b in zip(old, new):
        for i in (0, 1, 4, 5):
            assert b[i] == pytest.approx(a[i] * 1.5, abs=1e-5)
        assert _centre(b, 38, 18) == pytest.approx(_centre(a, 38, 18),
                                                   abs=1e-3)
        assert b[10] == 1.0 and b[15] == 1.0


def test_unknown_picture_and_neutral_edit_write_nothing():
    data, banner, _icon = _scene()
    imgs, tables = _parse(data)
    patches, n, notes = scene_layout.picture_layout_patches(
        data, imgs, {12345: {"dx": 3}, banner: {"dx": 0, "size": 100}},
        tables)
    assert (patches, n) == ([], 0)
    assert len(notes) == 1 and "12345" in notes[0]
    assert scene_layout.picture_layout_patches(b"junk", [], {1: {"dx": 1}})[
        :2] == ([], 0)


def test_scene_write_matrix_is_the_shape_that_is_read():
    """The matrix the mode screens write (emulator-proven) is the layout the
    finder accepts, so the two agree on which float is which."""
    m = scene_write.matrix(0.5, 0.5, 10.0, 20.0)
    m2 = scene_layout._picture_matrix(struct.unpack("<16f", m), 4, 4,
                                      1.0, 2.0, None)
    assert m2[12:14] == [11.0, 22.0] and m2[0] == 0.5


# ---------------------------------------------------------------------------
# the manifest row and the card side
# ---------------------------------------------------------------------------

def test_picture_rows_share_the_layout_manifest(tmp_path):
    key = text_layout.picture_key(BANNER_REL)
    assert key == "picture:" + BANNER_REL
    assert text_layout.picture_rel(key) == BANNER_REL
    assert text_layout.picture_rel("PICTURE: not a key") is None
    assert text_layout.row_label(key) == "picture radimg_40x20_aaaa0001.png"
    text_layout.set_layout(str(tmp_path), CARD, key, dx=5, size=120)
    text_layout.set_layout(str(tmp_path), CARD, "SELECT", dy=3)
    assert text_layout.load(str(tmp_path))[CARD] == {
        key: {"dx": 5.0, "dy": 0.0, "align": None, "size": 120},
        "SELECT": {"dx": 0.0, "dy": 3.0, "align": None, "size": None}}


def _project(tmp_path, banner, icon):
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True)
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        "%s\t%s\t%d\t800\t40\t20\t5\n%s\t%s\t%d\t256\t16\t16\t5\n"
        % (BANNER_REL, CARD, banner, ICON_REL, CARD, icon), encoding="utf-8")
    return str(tmp_path)


def test_the_write_moves_the_picture_on_the_card(tmp_path):
    data, banner, icon = _scene()
    assets = _project(tmp_path, banner, icon)
    text_layout.set_layout(assets, CARD, text_layout.picture_key(BANNER_REL),
                           dx=20, dy=10)
    msgs = []
    writes, n, overlays = engine._radium_layout_writes(
        _FakeReader({CARD: data}), assets,
        lambda m, lvl="info": msgs.append((lvl, m)), lambda: False)
    assert n == 1 and len(writes) == 2
    (_ib, (_node, ov)), = overlays.items()
    assert ov == dict(writes)
    new = _apply(data, writes)
    assert [m[12:14] for m in _matrices(new, banner)] == \
        [[120.0, 60.0], [120.0, 410.0]]
    assert any(lvl == "info" and "radimg_40x20_aaaa0001.png" in m
               and "moved +20,+10" in m for lvl, m in msgs)


def test_a_card_without_that_picture_is_a_warning_not_a_write(tmp_path):
    data, banner, icon = _scene()
    assets = _project(tmp_path, banner + 4, icon)     # another code version
    text_layout.set_layout(assets, CARD, text_layout.picture_key(BANNER_REL),
                           dx=20)
    msgs = []
    writes, n, _ov = engine._radium_layout_writes(
        _FakeReader({CARD: data}), assets,
        lambda m, lvl="info": msgs.append((lvl, m)), lambda: False)
    assert (writes, n) == ([], 0)
    assert any(lvl == "warning" and "left alone" in m for lvl, m in msgs)


def test_lines_and_pictures_of_one_scene_write_together(tmp_path):
    """A scene with no text is still a picture layout target (the text half
    used to stop the whole scene with 'no text could be read')."""
    data, banner, icon = _scene()
    assets = _project(tmp_path, banner, icon)
    text_layout.set_layout(assets, CARD, text_layout.picture_key(ICON_REL),
                           size=200)
    text_layout.set_layout(assets, CARD, "NOT IN THIS SCENE", dx=4)
    msgs = []
    writes, n, _ov = engine._radium_layout_writes(
        _FakeReader({CARD: data}), assets,
        lambda m, lvl="info": msgs.append((lvl, m)), lambda: False)
    assert n == 1 and len(writes) == 1
    (m,) = _matrices(_apply(data, writes), icon)
    assert (m[0], m[5]) == (2.0, 2.0) and m[12:14] == [292.0, 52.0]
    assert any("no text could be read" in m for _l, m in msgs)


# ---------------------------------------------------------------------------
# the preview
# ---------------------------------------------------------------------------

def test_the_preview_draws_a_pending_picture_edit(tmp_path):
    pic = tmp_path / "images" / "scene_textures"
    pic.mkdir(parents=True)
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(pic / "p.png")
    layout = {"stage": (100, 60, 30.0), "texts": [],
              "sprites": [{"name": "P", "x": 20, "y": 20,
                           "image": "scene_textures/p.png"}]}
    key = text_layout.picture_key("scene_textures/p.png")

    def box(edits):
        img = scene_render.render_layout(str(tmp_path), layout,
                                         layout_edits=edits)
        return Image.fromarray(np.asarray(img)[:, :, 0] > 128).getbbox()

    assert box(None) == (20, 20, 30, 30)
    assert box({key: {"dx": 30, "dy": -10}}) == (50, 10, 60, 20)
    assert box({key: {"size": 200}}) == (15, 15, 35, 35)
    assert box({"picture:scene_textures/other.png": {"dx": 30}}) == \
        (20, 20, 30, 30)
