"""PAD-540 (DragonRR): "click on the line that tells the user how many edits have been done,
pop out a window ... click on the edit in the list and connect to the scene and auto select
the item in that scene ... allowed the user to reset an edit.  This MUST be undoable."

The "N edits, not written yet" line opens the list of edits in the scene list's place: every
scene's edits, the selected scene's first.  Picking one goes to its scene and selects what it
changed; Reset takes that one edit back on its own scene, as one undo step there.
"""

import json

import pytest

from tests.test_gui_scene_editor import CARD, _ops, _open, _seed, _tv, _wait
from tests.webui_harness import web_app

pytest.importorskip("numpy")
pytest.importorskip("PIL")

CARD2 = "/g/scene2/scene.radium"


def test_without_takes_what_an_added_node_had_with_it():
    from pinball_decryptor.plugins.stern import scene_edit
    ops = [{"op": "move", "node": 1, "dx": 1, "dy": 0},
           {"op": "add_text", "parent": None, "index": 0, "id": 900, "name": "Mine",
            "text": "HI", "x": 0, "y": 0, "like": 3, "rgba": [1, 1, 1, 1]},
           {"op": "move", "node": 900, "dx": 4, "dy": 4},
           {"op": "shadow", "node": 900, "id": 902, "dx": 2, "dy": 2, "mul": [0, 0, 0, .5]},
           {"op": "tint", "node": 902, "mul": [1, 0, 0, 1]},
           {"op": "visible", "node": 2, "on": False}]
    # a plain edit goes on its own
    assert scene_edit.without(ops, 0) == ops[1:]
    assert scene_edit.without(ops, 5) == ops[:5]
    # an added line takes its move, its drop shadow and the shadow's own tint with it
    assert scene_edit.without(ops, 1) == [ops[0], ops[5]]
    # the shadow alone: its tint goes too, the line stays
    assert scene_edit.without(ops, 3) == ops[:3] + [ops[5]]
    assert scene_edit.without(ops, 9) == ops


def _two_scenes(folder):
    """The editor's synthetic scene twice: /g/scene1 and /g/scene2."""
    man = _seed(folder)
    tex = folder / "images" / "scene_textures"
    (tex / "scene_tree.json").write_text(json.dumps({CARD: man, CARD2: man}), encoding="utf-8")
    rows = (tex / "radium_images.txt").read_text(encoding="utf-8").splitlines()
    more = [r.replace(CARD, CARD2).replace("scene_textures/pic_", "scene_textures/two_pic_")
            for r in rows[1:]]
    for r in more:
        rel = r.split("\t")[0]
        src = folder / "images" / rel.replace("two_pic_", "pic_")
        (folder / "images" / rel).write_bytes(src.read_bytes())
    (tex / "radium_images.txt").write_text("\n".join(rows + more) + "\n", encoding="utf-8")
    return man


def test_the_list_goes_to_an_edit_and_resets_one_as_an_undo_step(tmp_path):
    from pinball_decryptor.plugins.stern import scene_edit
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _two_scenes(folder)
    by_name = {n["name"]: n["id"] for n in scene_edit._man_index(man).values()
               for n in [n[0]]}
    art, title = by_name["Art"], by_name["Title"]
    scene_edit.add(str(folder), CARD2, {"op": "move", "node": title, "dx": 7, "dy": 0})
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        st = lambda: w.state("text_scenes")                          # noqa: E731
        assert w.call("text_scenes.tree_move", art, 5, 0)
        assert w.call("text_scenes.tree_visible", title, False)
        assert st().get("edit_list") is None                          # shut until asked for
        assert w.call("text_scenes.edit_list", True)
        got = st()["edit_list"]
        assert [(g["card"], g["here"], g["d"]) for g in got] == [
            (CARD, True, "/g/scene1"), (CARD2, False, "/g/scene2")]
        assert [(e["name"], e["what"]) for e in got[0]["edits"]] == [
            ("Art", "moved +5,+0"), ("Title", "hidden in game")]
        assert [(e["i"], e["name"]) for e in got[1]["edits"]] == [(0, "Title")]

        # an edit on the other scene: its scene, with what it moved selected
        assert w.call("text_scenes.edit_list_pick", CARD2, 0)
        assert _wait(w, lambda: st()["sel"] == "/g/scene2" and _tv(w)["card"] == CARD2)
        assert _tv(w)["sel"] == title
        assert [g["card"] for g in st()["edit_list"]] == [CARD2, CARD]    # now on top

        # Reset the first scene's hide from here: it goes back there and drops only that
        hide = st()["edit_list"][1]["edits"][1]
        assert not w.call("text_scenes.edit_list_reset", CARD, 1, "stale")   # list changed
        assert w.call("text_scenes.edit_list_reset", CARD, 1, hide["sig"])
        assert _wait(w, lambda: st()["sel"] == "/g/scene1")
        assert _ops(folder) == [{"op": "move", "node": art, "dx": 5, "dy": 0}]
        lay = {l["id"]: l for l in _tv(w)["layers"]}
        assert not lay[title]["hidden"] and not lay[title]["view_off"]   # its eye opened
        assert [len(g["edits"]) for g in st()["edit_list"]] == [1, 1]
        assert _tv(w)["edits"] == 1

        # Undo puts it back, eye and all; Redo takes it off again
        assert w.call("text_scenes.tree_undo")
        assert _ops(folder)[-1] == {"op": "visible", "node": title, "on": False}
        lay = {l["id"]: l for l in _tv(w)["layers"]}
        assert lay[title]["hidden"] and lay[title]["view_off"]
        assert [len(g["edits"]) for g in st()["edit_list"]] == [2, 1]
        assert w.call("text_scenes.tree_redo")
        assert len(_ops(folder)) == 1

        # the other scene's edit is untouched; the list shuts again
        assert scene_edit.ops_for(str(folder), CARD2) == [
            {"op": "move", "node": title, "dx": 7, "dy": 0}]
        assert w.call("text_scenes.edit_list", False)
        assert st().get("edit_list") is None
        w.call("text_scenes.close")
