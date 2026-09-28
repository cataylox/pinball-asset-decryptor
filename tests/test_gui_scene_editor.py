"""Scenes window: the scene EDITOR (PAD-251), driven through the calls the canvas and its
side panel make (webui/text_scenes_tree.py, ``text_scenes.tree_*``).

A scene the project has a tree for (``scene_tree.json``) is drawn from that tree and edited in
place: pick an element, drag it (a glass move turned into the node's own units), resize it from
a corner (about its middle), tint it, hide it, re-layer it, add a line of text, undo, put it
back.  Every edit lands in ``scene_edits.json``, is drawn at once, and is listed on the Write
tab as a pending change.
"""

import json
import os
import time

import pytest

from tests.webui_harness import web_app

pytest.importorskip("numpy")
pytest.importorskip("PIL")

CARD = "/g/scene1/scene.radium"


def _seed(folder):
    """A project with one scene the editor can draw: the synthetic scene of
    tests/test_stern_scene_tree.py, its manifest, PNGs for its pictures."""
    from PIL import Image
    from pinball_decryptor.plugins.stern import scene_eval, scene_tree
    from tests.test_stern_scene_tree import scene
    sc = scene_tree.parse(scene())
    tex = folder / "images" / "scene_textures"
    tex.mkdir(parents=True)
    tex2rel = {}
    rows = []
    for tid, t in sc.textures.items():
        rel = "scene_textures/pic_%d.png" % tid
        Image.new("RGBA", (t["w"], t["h"]), (200, 40, 40, 255)).save(
            str(folder / "images" / rel))
        tex2rel[t["data_off"]] = rel
        rows.append("%s\t%s\t%d\t%d\t%d\t%d\t5" % (rel, CARD, t["data_off"], len(t["blob"]),
                                                   t["w"], t["h"]))
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        + "\n".join(rows) + "\n", encoding="utf-8")
    man = scene_eval.manifest(sc, tex2rel)
    (tex / "scene_tree.json").write_text(json.dumps({CARD: man}), encoding="utf-8")
    return man


def _wait(w, pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _open(w, folder):
    def _set():
        w.window.write_assets_var.set(str(folder))
    w.run(_set)
    text = w.window.service("text")
    assert w.run(text.open_scene_browser, str(folder)) is True
    w.call("text_scenes.select", "/g/scene1")
    assert _wait(w, lambda: (w.state("text_scenes").get("frames") or []) != [])
    return text.scenes


def _tv(w):
    return w.state("text_scenes")["tree_view"]


def _ops(folder):
    from pinball_decryptor.plugins.stern import scene_edit
    return scene_edit.ops_for(str(folder), CARD)


def test_the_editor_draws_the_tree_and_edits_it(tmp_path):
    from pinball_decryptor.webui import write_scan
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        sb = _open(w, folder)
        st = w.state("text_scenes")
        assert st["tree"] is True
        tv = _tv(w)
        assert tv["stage"] == [1360, 768] and tv["frames"] == 20
        assert [m["label"] for m in tv["moments"]][1:] == ["Start (frame 1)", "End (frame 20)"]
        names = [h["name"] for h in tv["hits"]]
        assert "Art" in names and "Title" in names
        art = next(h for h in tv["hits"] if h["name"] == "Art")

        # pick it: its box and size show
        assert w.call("text_scenes.tree_select", art["id"])
        p = _tv(w)["props"]
        assert p["name"] == "Art" and p["scale"] == 100 and p["kind"] == "Bitmap"
        x0, y0 = p["x"], p["y"]

        # a drag of (30, -10) glass pixels: the Art node is scaled 0.8 on the glass, so its
        # own units are the same (its parent is the root) - and it lands 30, -10 away
        assert w.call("text_scenes.tree_move", art["id"], 30, -10)
        assert _ops(folder) == [{"op": "move", "node": art["id"], "dx": 30.0, "dy": -10.0}]
        p = _tv(w)["props"]
        assert (p["x"], p["y"]) == (x0 + 30, y0 - 10)

        # a corner drag to 150 %: about the middle, so the middle stays put
        mid = (p["x"] + p["w"] / 2.0, p["y"] + p["h"] / 2.0)
        assert w.call("text_scenes.tree_scale", art["id"], 1.5)
        p = _tv(w)["props"]
        assert p["scale"] == 150
        assert abs(p["x"] + p["w"] / 2.0 - mid[0]) <= 1 and abs(p["y"] + p["h"] / 2.0 - mid[1]) <= 1

        # width and height apart: a stretch, about the middle too
        assert w.call("text_scenes.tree_set_size", art["id"], 300, None)
        p = _tv(w)["props"]
        assert (p["scale"], p["scale_y"]) == (300, 150)
        assert w.call("text_scenes.tree_set_size", art["id"], 150, None)
        assert _tv(w)["props"]["scale"] == 150

        # tint, hide, re-layer
        assert w.call("text_scenes.tree_tint", art["id"], "#3366ff", 50)
        p = _tv(w)["props"]
        assert p["tint"] == "#3366ff" and p["alpha"] == 50
        title = next(h for h in _tv(w)["hits"] if h["name"] == "Title")["id"]
        assert w.call("text_scenes.tree_order", title, "back")
        assert w.call("text_scenes.tree_visible", title, False)
        assert all(h["id"] != title for h in _tv(w)["hits"])
        assert w.call("text_scenes.tree_visible", title, True)
        assert any(h["id"] == title for h in _tv(w)["hits"])

        # add a line of text in the selected line's font; it is selected and drawn
        assert w.call("text_scenes.tree_select", title)
        assert w.call("text_scenes.tree_add_text", "HELLO THERE")
        tv = _tv(w)
        assert tv["props"]["added"] and tv["props"]["kind"] == "Text"
        assert any(h["name"] == "PAD_Text" for h in tv["hits"])
        added = tv["props"]["id"]

        # the Write tab lists the scene's edits and notices a change
        write = w.window.service("write")
        fp = w.run(write._fingerprint)
        rows = w.run(lambda: write_scan.pending_rows(
            w.window, w.window.current_mfr, str(folder), grow_on=True, direct=False))
        rows = [r for r in rows if r[2] == "Pending (scene edit)"]
        assert rows and "5 edit(s)" in rows[0][0]

        # undo drops the last edit (the added text), remove on an added node drops it too
        assert w.call("text_scenes.tree_undo")
        assert not any(h["name"] == "PAD_Text" for h in _tv(w)["hits"])
        assert w.run(write._fingerprint) != fp
        assert w.call("text_scenes.tree_reset", art["id"])
        assert [op["op"] for op in _ops(folder)] == ["order"]
        assert added not in [n["id"] for n in _tv(w)["layers"]]

        # the moment: a label seeks the root timeline
        assert w.call("text_scenes.tree_moment", "f:20")
        assert _tv(w)["frame"] == 20
        w.call("text_scenes.close")
        assert sb is not None


def test_a_scene_without_a_tree_keeps_the_old_preview(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    os.remove(str(folder / "images" / "scene_textures" / "scene_tree.json"))
    with web_app(tmp_path, mfr="stern") as w:
        def _set():
            w.window.write_assets_var.set(str(folder))
        w.run(_set)
        text = w.window.service("text")
        assert w.run(text.open_scene_browser, str(folder)) is True
        w.call("text_scenes.select", "/g/scene1")
        w.drain()
        assert not w.state("text_scenes").get("tree")
        w.call("text_scenes.close")
