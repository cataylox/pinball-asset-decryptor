"""PAD-514 (DragonRR): "I have increased red on both red sliders to max but left blue and
green alone. There is no change to the colour of the text ... In the fonts tab add a color
wheel and brightness controls for text colors ... Give them the facility to save and load
text colours as you have done in profiles."

A colour profile bends the colours a line already has: white is already full red, so his
red sliders left the white ":10" white.  A line can now have a colour of its own instead (a
``text_colour`` scene edit from the Font bar): it is drawn in exactly that colour, in the
preview and by the Write, and the profile does not reach it.  A font whose letters carry
their own colours gets its own copy of the font with them in that colour (PAD-451's way).
Saved colours are small files, one each, as saved profiles are.
"""
import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.plugins.stern import (
    engine, scene_edit as X, scene_eval as E, scene_tree as T, text_colour as TC)
from tests.test_pad438_text_colour_profile import (
    CARD, DARK, GREEN, TITLE, _data, _drawn, _man, _project, _text)
from tests.test_stern_text_colors import _FakeReader

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

RED = [1.0, 0.1647, 0.102]                       # #ff2a1a
#: his "My profile": Middle shades red 10.00 (1 / gamma), Color level red 4.00
HIS = cp.Profile(name="My profile", gamma=(0.1, 1.0, 1.0), gain=(4.0, 1.0, 1.0))


def _own(rgb=RED, node=TITLE, **kw):
    return dict({"op": "text_colour", "node": node, "rgb": list(rgb)}, **kw)


def test_white_letters_cannot_be_turned_red_by_the_profile():
    """His screenshot: red maxed on both sliders, green and blue at 1.00, and the white
    ":10" stays white; with green and blue turned down it goes red."""
    assert TC.corrected(HIS, [1.0, 1.0, 1.0]) == [1.0, 1.0, 1.0]
    down = cp.Profile(name="x", gain=(1.0, 0.0, 0.0))
    assert TC.corrected(down, [1.0, 1.0, 1.0]) == [1.0, 0.0, 0.0]


def test_a_plain_line_with_its_own_colour_is_drawn_in_it_not_the_profile(tmp_path):
    a = _project(tmp_path, prof=HIS)
    man = _man(_data((1, 1, 1)))
    ops, written = TC.line_ops(a, CARD, man, [_own()])
    assert ops == [{"op": "line_colour", "node": TITLE, "rgb": RED}]
    assert written[TITLE]["base_rgb"] == [1.0, 1.0, 1.0]
    assert _drawn(X.apply_manifest(man, ops)[0])["rgba"][:3] == pytest.approx(RED)
    # whether its switch is on or off, the preview's Individual files switch off, or the game
    # line still locked: it is the line's own colour, not the profile's
    assert TC.line_ops(a, CARD, man, [_own()], bake=False)[0] == ops
    locked = _project(tmp_path / "locked", prof=HIS, unlocked=False)
    assert TC.line_ops(locked, CARD, man, [_own()])[0] == ops
    # the last one counts
    assert TC.line_ops(a, CARD, man, [_own([0, 0, 1]), _own()])[0] == ops


def test_a_styled_line_takes_it_in_every_step_of_its_track_keeping_its_opacity(tmp_path):
    a = _project(tmp_path, prof=DARK)
    fade = [{"op": "tint", "node": TITLE, "mul": GREEN + [0.5]}]
    man = X.apply_manifest(_man(_data((1, 1, 1))), fade)[0]
    _n, o = _text(man)
    o["styled"] = True
    ops, _w = TC.line_ops(a, CARD, man, fade + [_own()])
    (op,) = ops
    assert "rgb" not in op
    assert op["col"][0][1] == pytest.approx(RED + [0.5])      # the tint's colour gone, not its fade
    assert _drawn(X.apply_manifest(man, ops)[0])["mul"][:3] == pytest.approx(RED)


def test_a_shared_text_takes_it_in_the_track_and_its_shadow_keeps_its_look(tmp_path):
    a = _project(tmp_path, prof=DARK)
    shadow = {"op": "shadow", "node": TITLE, "id": X.FIRST_ADDED_ID, "dx": 4, "dy": 4,
              "mul": [0, 0, 0, 0.6]}
    man = X.apply_manifest(_man(), [shadow])[0]
    before = _drawn(man, "Title_Shadow")
    ops, _w = TC.line_ops(a, CARD, man, [shadow, _own()])
    by = {op["node"]: op for op in ops}
    assert by[TITLE]["rgb"] == [1.0, 1.0, 1.0]
    after = X.apply_manifest(man, ops)[0]
    line = _drawn(after)
    assert [line["rgba"][i] * line["mul"][i] for i in range(3)] == pytest.approx(RED)
    sh = _drawn(after, "Title_Shadow")
    assert [sh["rgba"][i] * sh["mul"][i] for i in range(4)] == pytest.approx(
        [before["rgba"][i] * before["mul"][i] for i in range(4)], abs=1e-4)


def test_its_own_colour_off_gives_back_the_profile_and_a_built_card_its_base(tmp_path):
    a = _project(tmp_path, prof=DARK)
    ops, written = TC.line_ops(a, CARD, _man(), [_own()])
    TC.remember(a, CARD, written)
    built = _man(_data(RED))                                 # the project read off that card
    assert TC.line_ops(a, CARD, built, [_own()])[0] == ops
    # Default: the profile again, worked out from the colour the game shipped
    back, _w = TC.line_ops(a, CARD, built, [])
    assert back == [{"op": "line_colour", "node": TITLE,
                     "rgb": pytest.approx(TC.corrected(DARK, GREEN), abs=1e-4)}]


def test_the_write_puts_its_own_colour_in_place(tmp_path):
    """A scene whose only edit is a line's own colour is written, in place, and the profile
    switched on for that line does not go into it."""
    a = _project(tmp_path, prof=HIS, ops=[_own()])
    data = _data()
    engine._LINES_SAID.v = {}
    ov, msgs = {}, []
    writes, n, whole = engine._scene_tree_plan(
        _FakeReader({CARD: data}), a, lambda m, lvl="info": msgs.append((lvl, m)),
        lambda: False, False, ov)
    assert (n, whole) == (1, {}) and writes
    new = bytearray(data)
    for off, b in writes:
        new[off:off + len(b)] = b
    assert len(new) == len(data)
    back = E.manifest(T.parse(bytes(new)))
    assert _drawn(back)["rgba"][:3] == pytest.approx(RED, abs=1e-5)
    assert not [m for lvl, m in msgs if lvl == "warning"]


def test_the_edit_is_a_marker_the_scene_edits_pass_by():
    man = _man()
    got, notes = X.apply_manifest(man, [_own()])
    assert notes == [] and got == man
    sc = T.parse(_data())
    assert X.apply_scene(sc, [_own()], names=X.names_of(man)) == (0, [])
    assert T.serialize(sc) == _data()
    assert X.describe(_own()) == "colored #ff2a1a"


def test_brightness_darkens_the_colour_picked():
    assert TC.shade([1.0, 0.5, 0.0], 100) == [1.0, 0.5, 0.0]
    assert TC.shade([1.0, 0.5, 0.0], 50) == [0.5, 0.25, 0.0]
    assert TC.shade([1.0, 0.5, 0.0], 0) == [0.0, 0.0, 0.0]
    assert TC.shade([1.0, 0.5, 0.0], 400) == [1.0, 0.5, 0.0]


# ---------------------------------------------------------------------------------------------
# a font whose letters carry their own colours (Godzilla's orange GameFont_Secondary)
# ---------------------------------------------------------------------------------------------
def test_a_coloured_font_line_gets_its_own_copy_in_its_own_colour(tmp_path):
    from pinball_decryptor.plugins.stern import dds, font_copy as FC
    from tests.test_pad451_line_own_font import (
        CARD as FCARD, MINE, ORANGE, SIZE, _atlases, _gf, _man as fman, _project as fproj,
        font_scene)
    a = fproj(tmp_path, slots=(MINE,))                       # its profile switch on, too
    man = fman()
    fonts = {"gf": _gf()}
    blue = [0.1, 0.3, 1.0]
    ops, written = TC.line_ops(a, FCARD, man, [_own(blue, node=MINE)], fonts=fonts)
    (op,) = ops
    assert op["op"] == "line_font" and op["mul"] is None and written == {MINE: {"font": True}}
    prof = cp._from_dict(op["profile"])
    assert prof.saturation == 0.0                            # its light and shade kept
    # its brightest (the solid orange here) is the colour itself
    got = prof.apply_array(np.asarray([[ORANGE]], np.uint8))[0, 0].astype(int)
    assert np.abs(got - np.round(np.asarray(blue) * 255)).max() <= 2
    sc = T.parse(font_scene())
    assert X.apply_scene(sc, ops, a, {}) == (1, [])
    mine = FC.fonts_of(T.parse(T.serialize(sc)))[1][1]
    for _tid, (w, h, _fmt, _n, blob) in mine.pages.items():
        px = dds.decode_bc3(blob, w, h)[..., :3].reshape(-1, 3).astype(int)
        assert np.abs(px - np.round(np.asarray(blue) * 255)).max() <= 6   # BC3 end points
    assert SIZE in {t.body["font"] for t in sc.objects.values() if t.kind == "Text"}


# ---------------------------------------------------------------------------------------------
# saved colours (one file each, as saved profiles are)
# ---------------------------------------------------------------------------------------------
def test_saved_colours_are_files_listed_by_name(tmp_path):
    d = tmp_path / "Text colors"
    d.mkdir()
    TC.save_colour_file(str(d / "Kaiju red.txt"), "#FF2A1A", 80)
    (d / "by hand.txt").write_text("#00ff00\n", encoding="utf-8")
    (d / "notes.txt").write_text("not a colour at all\n", encoding="utf-8")
    (d / "pic.png").write_bytes(b"\x89PNG")
    assert TC.read_colour_file(str(d / "Kaiju red.txt")) == ("#ff2a1a", 80)
    assert TC.saved_colours([str(d), str(d), str(tmp_path / "missing")]) == [
        ("by hand", str(d / "by hand.txt"), "#00ff00", 100),
        ("Kaiju red", str(d / "Kaiju red.txt"), "#ff2a1a", 80)]
    with pytest.raises(ValueError):
        TC.save_colour_file(str(d / "bad.txt"), "red")


# ---------------------------------------------------------------------------------------------
# the Font bar (webui/text_scenes_tree.py)
# ---------------------------------------------------------------------------------------------
def test_the_font_bar_gives_a_line_its_own_colour_saves_and_loads_it(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import CARD as SCENE, _seed, _open, _tv, _wait
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _data((1, 1, 1)))
    d = str(folder)
    cp.store_asset_profile(d, HIS)
    keep = tmp_path / "kept"
    keep.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_select", TITLE)

        def colour():
            return ((_tv(w).get("props") or {}).get("font") or {}).get("colour") or {}
        assert _wait(w, lambda: colour().get("hex") == "#ffffff")
        assert colour()["own"] is False
        assert w.call("text_scenes.tree_text_colour", TITLE, "#FF2A1A", 100)
        assert X.ops_for(d, SCENE)[-1] == _own(pick="#ff2a1a", bright=100)
        assert _wait(w, lambda: colour().get("own") is True)
        assert colour()["hex"] == "#ff2a1a"
        # the preview draws it, and Layers says what it is
        tman = lambda: w.window.service("text").scenes._tman       # noqa: E731
        assert _wait(w, lambda: [round(v, 3) for v in _drawn(tman())["rgba"][:3]]
                     == [round(v, 3) for v in RED])
        lay = next(l for l in _tv(w)["layers"] if l["id"] == TITLE)
        assert "colored #ff2a1a" in lay["edits"]
        # the same colour again is no edit; darker is
        assert not w.call("text_scenes.tree_text_colour", TITLE, "#ff2a1a", 100)
        assert w.call("text_scenes.tree_text_colour", TITLE, "#ff2a1a", 50)
        assert [op["op"] for op in X.ops_for(d, SCENE)].count("text_colour") == 1
        assert _wait(w, lambda: colour().get("hex") == "#80150d")
        # Save a copy, listed under Saved; Load gives it to the line
        w.window.remember_browse_dir("text_colour", str(keep))
        w.window.ask_save = lambda *a, **k: str(keep / k["initialfile"])
        assert w.call("text_scenes.tree_text_colour_save", "#00ff00", 100)
        assert _wait(w, lambda: [c["pick"] for c in colour().get("saved") or []] == ["#00ff00"])
        saved = colour()["saved"][0]
        assert w.call("text_scenes.tree_text_colour_use", TITLE, saved["path"])
        assert _wait(w, lambda: colour().get("hex") == "#00ff00")
        assert not w.call("text_scenes.tree_text_colour_use", TITLE, str(tmp_path / "x.txt"))
        # Default: its own colour off (one undo step brings it back)
        assert w.call("text_scenes.tree_text_colour", TITLE, None)
        assert _wait(w, lambda: colour().get("own") is False)
        assert not any(op["op"] == "text_colour" for op in X.ops_for(d, SCENE))
        assert w.call("text_scenes.tree_undo")
        assert _wait(w, lambda: colour().get("own") is True)
