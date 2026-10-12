"""PAD-534 (DragonRR): Godzilla's Planet X map points at the bridge with a south-pointing
triangle the game draws turned 48 degrees.  The Scenes panel's Turn box read 0 (it counts only
the user's own turn) and the Images tab showed the picture unturned with no word of the scene
it is in, so the link from the scene looked like it landed on the wrong picture.  The Scenes
panel now says how the game turns or mirrors a layer, and the Images preview names the
scene(s) a picture is in and how the game turns it there."""

import json
import math
import time

import pytest

from tests.test_gui_scene_editor import CARD, _open, _seed, _tv
from tests.webui_harness import web_app

pytest.importorskip("numpy")
pytest.importorskip("PIL")


def _turned(deg):
    r = math.radians(deg)
    return [round(math.cos(r), 5), round(math.sin(r), 5), round(-math.sin(r), 5), round(math.cos(r), 5)]


def _seed_turned(folder, deg=48.0):
    """The editor's synthetic scene with its Art picture turned *deg* clockwise by the game."""
    man = _seed(folder)
    art = next(n for n in man["root"]["kids"] if n["name"] == "Art")
    for e in art["tr"]:
        s = math.hypot(e[1][0], e[1][1])
        e[1][:4] = [round(v * s, 5) for v in _turned(deg)]
    tree = folder / "images" / "scene_textures" / "scene_tree.json"
    tree.write_text(json.dumps({CARD: man}), encoding="utf-8")
    rel = next(o for o in man["objects"].values() if o.get("kind") == "Bitmap")["image"]
    return "images/" + rel


def test_turn_of_reads_a_turn_and_a_mirror():
    from pinball_decryptor.plugins.stern.scene_eval import turn_of
    assert turn_of((1, 0, 0, 1, 5, 5)) == (0.0, False)
    assert turn_of(_turned(48) + [0, 0]) == (48.0, False)
    assert turn_of([v * 0.44 for v in _turned(-45)] + [0, 0]) == (-45.0, False)
    assert turn_of((-1, 0, 0, -1, 0, 0)) == (180.0, False)
    assert turn_of((-1, 0, 0, 1, 0, 0)) == (0.0, True)             # flipped left to right
    assert turn_of((1, 0, 0, -1, 0, 0)) == (180.0, True)           # flipped top to bottom


def test_the_scenes_panel_says_how_the_game_turns_a_picture(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed_turned(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert w.call("text_scenes.tree_select", art)
        p = _tv(w)["props"]
        assert p["rotate"] == 0
        assert p["game_turn"] == {"deg": 48.0, "mirrored": False}
        # the user's own turn goes on top; the game's stays what it ships
        assert w.call("text_scenes.tree_rotate", art, 90)
        p = _tv(w)["props"]
        assert p["rotate"] == 90 and p["game_turn"] == {"deg": 48.0, "mirrored": False}
        # a layer the game draws upright says nothing
        title = next(h for h in _tv(w)["hits"] if h["name"] == "Title")["id"]
        assert w.call("text_scenes.tree_select", title)
        assert _tv(w)["props"]["game_turn"] is None
        w.call("text_scenes.close")


def _preview_scenes(w, rel, want):
    end = time.time() + 20
    while time.time() < end:
        w.drain()
        got = (w.state("images").get("preview") or {}).get("scenes") or ""
        if want in got:
            return got
        time.sleep(0.05)
    return (w.state("images").get("preview") or {}).get("scenes") or ""


def test_the_images_preview_names_the_scene_and_the_games_turn(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    rel = _seed_turned(folder)
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(str(folder)))
        w.call("images.scan")
        im = w.window.service("images")
        end = time.time() + 20
        while time.time() < end and rel not in w.run(lambda: dict(im._by_rel)):
            time.sleep(0.05)
        assert w.call("images.select", rel)
        got = _preview_scenes(w, rel, "where")
        assert got.startswith("In scene ")
        assert got.endswith(", where the game draws it turned 48° clockwise")


def test_a_picture_drawn_upright_names_only_its_scene(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    rel = _seed_turned(folder, 0.0)
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(str(folder)))
        w.call("images.scan")
        im = w.window.service("images")
        end = time.time() + 20
        while time.time() < end and rel not in w.run(lambda: dict(im._by_rel)):
            time.sleep(0.05)
        assert w.call("images.select", rel)
        end = time.time() + 20
        while time.time() < end and w.run(lambda: bool(im._turns_busy) or not im._turns):
            time.sleep(0.05)
        w.drain()
        got = w.state("images")["preview"]["scenes"]
        assert got.startswith("In scene ") and "turned" not in got
