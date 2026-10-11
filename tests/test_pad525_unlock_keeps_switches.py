"""PAD-525 (DragonRR): unticking "Unlock extracted images and text" dropped the color switch
of every game picture and game line of text, and ticking it again brought none back (he had
Black and white on 6,668 of them).  Now the switches are put aside while the box is off and
come back when it is ticked again, from Scenes or from the Images tab.  Locked, none of them
counts, and a switch left from an old pick still never wakes (PAD-345)."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

PIL = pytest.importorskip("PIL.Image")


def test_lock_and_unlock_switches_round_trip():
    data = {cp.STOCK_IMAGES_KEY: True, cp.TEXT_SLOTS_KEY: {"/g/s.radium#7": True}}
    cp.lock_switches(data, {"images/a.png": True, "images/b.png": False})
    assert cp.TEXT_SLOTS_KEY not in data
    assert data[cp.LOCKED_SWITCHES_KEY] == {
        "images": {"images/a.png": True, "images/b.png": False},
        "text": {"/g/s.radium#7": True}}
    assert cp.unlock_switches(data) == {"images/a.png": True, "images/b.png": False}
    assert data[cp.TEXT_SLOTS_KEY] == {"/g/s.radium#7": True}
    assert cp.LOCKED_SWITCHES_KEY not in data
    # nothing put aside: nothing comes back, and an empty lock leaves no key
    assert cp.unlock_switches(data) == {}
    data.pop(cp.TEXT_SLOTS_KEY)
    cp.lock_switches(data, {})
    assert cp.LOCKED_SWITCHES_KEY not in data


def test_scenes_unlock_off_and_on_keeps_the_switches(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open, CARD
    from tests.test_pad345_scenes_unlock_put_back import _setup
    folder, rel = _setup(tmp_path)
    d = str(folder)
    line = cp.text_rel(CARD, 7)
    data = staged_changes.load(d)
    data[cp.STOCK_IMAGES_KEY] = True
    data[cp.IMAGE_SLOTS_KEY] = {rel: True}
    data[cp.TEXT_SLOTS_KEY] = {line: True}
    staged_changes.save(d, data)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_color_unlocked", False)
        assert not cp.stock_images_unlocked(d)
        assert cp.stock_image_rels(d) == [] and cp.text_lines_on(d) == set()
        assert not staged_changes.load(d).get(cp.IMAGE_SLOTS_KEY)
        assert w.call("text_scenes.tree_color_unlocked", True)
        assert cp.stock_image_rels(d) == [rel]
        assert cp.text_lines_on(d) == {line}
        assert cp.LOCKED_SWITCHES_KEY not in staged_changes.load(d)
        w.call("text_scenes.close")


def test_images_tab_unlock_off_and_on_keeps_the_switches(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_images import _project, _set_folder, _wait, _settled, _by_rel, PLAIN
    assets, _reps = _project(tmp_path)
    line = cp.text_rel("/g/scene.radium", 3)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        _wait(w, _settled)
        if not w.run(lambda: w.window.service("images")._per_file_colour()):
            pytest.skip("this manufacturer corrects the files on the display")
        assert w.call("images.set_color_unlocked", True)
        assert w.call("images.set_color", PLAIN, True)
        cp.set_text_slot(assets, line, True)
        assert w.call("images.set_color_unlocked", False)
        w.drain()
        data = staged_changes.load(assets)
        assert "image_color_slots" not in data and cp.TEXT_SLOTS_KEY not in data
        assert _by_rel(w.state("images"))[PLAIN]["cl"] is True
        assert w.call("images.set_color_unlocked", True)
        w.drain()
        data = staged_changes.load(assets)
        assert data["image_color_slots"] == {PLAIN: True}
        assert data[cp.TEXT_SLOTS_KEY] == {line: True}
        assert cp.LOCKED_SWITCHES_KEY not in data
        assert _by_rel(w.state("images"))[PLAIN]["c"] is True


def test_a_picture_picked_while_locked_keeps_its_own_switch(tmp_path):
    """Ticking puts back only the game's own pictures: one replaced since is the user's."""
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open
    from tests.test_pad345_scenes_unlock_put_back import _setup
    folder, rel = _setup(tmp_path)
    d = str(folder)
    data = staged_changes.load(d)
    data[cp.LOCKED_SWITCHES_KEY] = {"images": {rel: True}}
    pick = os.path.join(str(tmp_path), "mine.png")
    PIL.new("RGBA", (4, 4), (1, 2, 3, 255)).save(pick)
    data["image"] = {rel: pick}
    staged_changes.save(d, data)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_color_unlocked", True)
        data = staged_changes.load(d)
        assert not data.get(cp.IMAGE_SLOTS_KEY)
        assert cp.LOCKED_SWITCHES_KEY not in data
        w.call("text_scenes.close")
