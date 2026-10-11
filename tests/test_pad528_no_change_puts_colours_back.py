"""PAD-528 (DragonRR): "NO CHANGE does something ... I was actually relying on being able to
apply no change to all images and text."

With every picture built Black and white, No change applied to all of them (Apply to all,
All images) changed nothing on the next build: a staging whose profiles all change nothing
skipped the game's own pictures and clips altogether, so each kept the Black and white an
earlier build had baked into it.  No change now puts each one back to its own colors, from
its ``.orig/`` snapshot (a game picture or clip) or its kept uncorrected copy (a built
picture), the way switching it off does; one no build has touched is still left alone.
"""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes, staged_originals
from tests.test_pad335_unlock_game_pictures import _ramp, _slot
from tests.test_pad345_scenes_unlock_put_back import BUILT, _built_project
from tests.test_pad345_scenes_unlock_put_back import _ramp as _ramp_of

PIL = pytest.importorskip("PIL.Image")

BW = cp.Profile(name="Black and white", saturation=0.0)
NO_CHANGE = cp.Profile(name="No change")


def _pixels(f):
    return PIL.open(f).convert("RGB").tobytes()


def _unlocked_game_picture(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    d = str(proj)
    f, slot = _slot(proj, "stock.png")
    cp.set_asset_slot(d, "images", "stock.png", True)
    data = staged_changes.load(d)
    data[cp.STOCK_IMAGES_KEY] = True
    staged_changes.save(d, data)
    return d, f, slot


@pytest.mark.parametrize("how", ["files", "own"])
def test_no_change_puts_a_game_picture_built_black_and_white_back(tmp_path, how):
    from pinball_decryptor.core.image_slots import pictures_due, stage_replacements
    d, f, slot = _unlocked_game_picture(tmp_path)
    # Black and white: the individual files profile (All images), or the picture's own with
    # the individual files profile No change (Apply to all)
    if how == "files":
        cp.store_asset_profile(d, BW)
    else:
        cp.store_asset_profile(d, NO_CHANGE)
        cp.store_own_profile(d, "images", "stock.png", BW)
    assert stage_replacements({"stock.png": slot}, {}, assets_dir=d) == (1, [])
    assert _pixels(f) == BW.apply_image(_ramp()).tobytes()
    # then No change, the same way
    if how == "files":
        cp.store_asset_profile(d, NO_CHANGE)
    else:
        cp.store_own_profile(d, "images", "stock.png", NO_CHANGE)
    assert not cp.any_asset_active(d)
    assert pictures_due({"stock.png": slot}, {}, assets_dir=d) == 1
    assert stage_replacements({"stock.png": slot}, {}, assets_dir=d) == (1, [])
    assert _pixels(f) == _ramp().tobytes()
    # the next build keeps it as it is
    assert pictures_due({"stock.png": slot}, {}, assets_dir=d) == 0
    assert stage_replacements({"stock.png": slot}, {}, assets_dir=d) == (1, [])
    assert _pixels(f) == _ramp().tobytes()


def test_no_change_leaves_a_game_picture_no_build_touched_alone(tmp_path):
    from pinball_decryptor.core.image_slots import pictures_due, stage_replacements
    d, f, slot = _unlocked_game_picture(tmp_path)
    cp.store_asset_profile(d, NO_CHANGE)
    assert pictures_due({"stock.png": slot}, {}, assets_dir=d) == 0
    assert stage_replacements({"stock.png": slot}, {}, assets_dir=d) == (0, [])
    assert staged_originals.snapshot_path(d, "stock.png") is None
    assert _pixels(f) == _ramp().tobytes()


def test_no_change_puts_a_built_picture_back_to_its_own_copy(tmp_path):
    from pinball_decryptor.core.image_slots import pictures_due, stage_replacements
    d, f, slot = _built_project(tmp_path)
    cp.set_asset_slot(d, "images", BUILT, True)
    cp.store_asset_profile(d, BW)
    assert stage_replacements({BUILT: slot}, {}, assets_dir=d) == (1, [])
    assert _pixels(f) == BW.apply_image(_ramp_of((72, 6))).tobytes()
    cp.store_asset_profile(d, NO_CHANGE)
    assert pictures_due({BUILT: slot}, {}, assets_dir=d) == 1
    assert stage_replacements({BUILT: slot}, {}, assets_dir=d) == (1, [])
    got = PIL.open(f)
    assert got.size == (72, 6)                         # the user's, not Stern's
    assert got.convert("RGB").tobytes() == _ramp_of((72, 6)).tobytes()
    # its copy is kept: a profile picked later starts from it
    assert _pixels(cp.uncorrected_path(d, BUILT)) == _ramp_of((72, 6)).tobytes()


def test_no_change_puts_a_game_clip_built_black_and_white_back(tmp_path, monkeypatch):
    from pinball_decryptor.core import video_slots
    proj = tmp_path / "proj"
    proj.mkdir()
    d = str(proj)
    seen = []

    def fake_stage(slot, rep, **kw):
        seen.append(kw.get("colour"))
        with open(slot.abs_path, "wb") as f:
            f.write(b"black and white")
        return True, "ok"

    monkeypatch.setattr(video_slots, "stage_replacement", fake_stage)
    monkeypatch.setattr(video_slots, "_clip_bitrate", lambda p: None)
    monkeypatch.setattr(video_slots, "_slot_keyint", lambda p: 0)
    f = proj / "stock.mp4"
    f.write_bytes(b"stock")
    slot = video_slots.VideoSlot(rel_path="stock.mp4", abs_path=str(f),
                                 ext=".mp4", info=None, size=5, probed=False)
    staged_changes.save(d, {"video_color_stock": True,
                            "video_color_slots": {"stock.mp4": True}})
    cp.store_asset_profile(d, BW)
    stage = dict(slots_by_rel={"stock.mp4": slot},
                 assignments={"stock.mp4": video_slots.STOCK_SOURCE}, assets_dir=d)
    with cp.forced(False):
        assert video_slots.stage_replacements(**stage) == (1, [])
    assert seen == [BW] and f.read_bytes() == b"black and white"
    cp.store_asset_profile(d, NO_CHANGE)
    with cp.forced(False):
        # a copy back, not a conversion
        assert video_slots.conversions_due(**stage) == ({}, frozenset())
        assert video_slots.stage_replacements(**stage) == (1, [])
    assert seen == [BW] and f.read_bytes() == b"stock"
    assert staged_originals.snapshot_path(d, "stock.mp4") is None
    # put back: the next build leaves it alone
    with cp.forced(False):
        assert video_slots.stage_replacements(**stage) == (0, [])
    assert f.read_bytes() == b"stock"


def test_the_app_stages_the_game_clips_to_put_back(tmp_path):
    """MainWindow._video_staging hands over a game clip switched on with No change only where
    an earlier build re-encoded it."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "pinball_decryptor", "app.py"), encoding="utf-8") as fh:
        src = fh.read()
    body = src[src.index("    def _video_staging(self"):]
    body = body[:body.index("\n    def ", 10)]
    assert "any_asset_active" not in body
    assert "staged_originals.has_snapshot(assets_dir, rel)" in body


# ---------------------------------------------------------------------------------------------
# "Please make sure that this can also be done with font colour changes": the Font bar's
# Apply to all lines of text, for a line's own color and for Default
# ---------------------------------------------------------------------------------------------
CARD2 = "/g/scene2/scene.radium"


def _two_scenes(folder):
    """The PAD-471 scene (white letters: each line's color its own), and a copy of it as a
    second scene."""
    import json
    from tests.test_pad451_line_own_font import _man
    from tests.test_pad471_all_text_lines import _white_font
    from tests.test_pad451_line_own_font import CARD
    _white_font(folder)
    tree = folder / "images" / "scene_textures" / "scene_tree.json"
    tree.write_text(json.dumps({CARD: _man(), CARD2: _man()}), encoding="utf-8")


def _colours(a):
    from pinball_decryptor.plugins.stern import scene_edit as X, text_colour as TC
    return {card: {n: op["pick"] for n, op in TC.own_colours(ops).items()}
            for card, ops in X.load(a).items() if TC.own_colours(ops)}


def test_the_font_bar_gives_every_line_this_lines_color_and_undoes_as_one_step(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open
    from tests.test_pad451_line_own_font import CARD, MINE, OTHER
    from tests.test_pad471_all_text_lines import _added
    folder = tmp_path / "proj"
    folder.mkdir()
    _two_scenes(folder)
    a = str(folder)
    added = _added(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_select", MINE)
        # locked: only the line added in Scenes is not, and it is not this one
        assert w.call("text_scenes.tree_text_colour", MINE, "#FF2A1A", 80)
        w.answers.append("no")
        assert w.call("text_scenes.tree_text_colour_all", MINE) is False
        q = w.asked[-1]
        assert q["title"] == "Apply to all lines of text"
        assert "all 1 of them" in q["message"] and "#ff2a1a at 80% brightness" in q["message"]
        assert _colours(a) == {CARD: {MINE: "#ff2a1a"}}
        # unlocked: every line of both scenes
        assert w.call("text_scenes.tree_color_unlocked", True)
        w.answers.append("yes")
        assert w.call("text_scenes.tree_text_colour_all", MINE) is True
        assert "all 5 of them" in w.asked[-1]["message"]
        assert "4 of them change, in 2 scenes" in w.asked[-1]["message"]
        every = {MINE: "#ff2a1a", OTHER: "#ff2a1a"}
        assert _colours(a) == {CARD: {**every, added: "#ff2a1a"}, CARD2: every}
        # asked again: nothing left to change
        n = len(w.asked)
        assert w.call("text_scenes.tree_text_colour_all", MINE) is False
        assert len(w.asked) == n
        # one Undo puts both scenes back; Redo again
        assert w.call("text_scenes.tree_undo")
        assert _colours(a) == {CARD: {MINE: "#ff2a1a"}}
        assert w.call("text_scenes.tree_redo")
        assert _colours(a) == {CARD: {**every, added: "#ff2a1a"}, CARD2: every}
        # Default on this line, then for all: every line's own color off
        assert w.call("text_scenes.tree_text_colour", MINE, None)
        w.answers.append("yes")
        assert w.call("text_scenes.tree_text_colour_all", MINE) is True
        assert "goes back to Default" in w.asked[-1]["message"]
        assert _colours(a) == {}
        log = [l["text"] for l in w.run(w.window.log_history)]
        assert any("Font text color Default applied to all 5 lines of text" in t for t in log)


def test_the_font_bar_offers_it():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "pinball_decryptor", "webui", "static", "js", "tabs",
                           "scene_fonts.js"), encoding="utf-8") as f:
        src = f.read()
    assert 'call("text_scenes.tree_text_colour_all", id)' in src
    assert "Apply to all lines of text…" in src
