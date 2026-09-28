"""PAD-251: what a Spike 2 scene draws at a moment (scene_eval) and the picture of it
(scene_render.render_tree).

The old preview piled every state of a screen on top of each other, ignored scale and put
text against its node instead of inside its box.  What has to hold, and is tested here:

* a node draws when its last keyframe at or before the frame says so, with its last track and
  colour step, composed down the tree (transform AND tint);
* a labelled sprite rests on its first settled state unless pinned; an unlabelled one plays;
* the default still is the frame with the most elements on the glass;
* the renderer places a picture by its full affine (scale, tilt) and fades it by its tint;
* a line of text sits inside its rect: 2 px gutter, first baseline at the font size's declared
  ascent - on the real language screen that is the emulator's own pixel row;
* a font's glyph cells carry an outline margin, and the whole cell is drawn at the font's scale
  with the ink on the metrics (fontrender.cell_fit), where a cell that IS its box is untouched.
"""
import os

import pytest

np = pytest.importorskip("numpy")
from PIL import Image                                                  # noqa: E402

from pinball_decryptor.plugins.stern import (                          # noqa: E402
    fontrender, scene_eval as E, scene_render as R)


def N(nid, name, comps, kf=((1, 1),), tr=((1, (1, 0, 0, 1, 0, 0)),), col=()):
    return {"id": nid, "name": name, "kf": [list(k) for k in kf],
            "tr": [[f, list(m)] for f, m in tr],
            "col": [[f, list(m), list(a)] for f, m, a in col],
            "comps": [[1, c] for c in comps]}


def man(kids, objects, frames=10, labels=()):
    return {"v": 2, "stage": [200, 100, 30.0, [0, 0, 0, 1]],
            "root": {"frames": frames, "labels": [list(x) for x in labels], "kids": kids},
            "objects": {str(k): v for k, v in objects.items()}}


BMP = {"kind": "Bitmap", "w": 10, "h": 10, "tex": 1, "image": "scene_textures/red.png"}


def test_visibility_transform_and_tint_follow_the_timeline_and_compose():
    group = {"kind": "Sprite", "frames": 1, "labels": [],
             "kids": [N(3, "Pic", [9], tr=((1, (0.5, 0, 0, 0.5, 10, 0)),))]}
    m = man([N(1, "G", [2], kf=((1, 0), (3, 1), (8, 0)),
               tr=((1, (1, 0, 0, 1, 0, 0)), (4, (2, 0, 0, 2, 100, 50))),
               col=((3, (1, 1, 1, 0.5), (0, 0, 0, 0)),))],
            {2: group, 9: BMP})
    assert E.draw_list(m, 1) == [] and E.draw_list(m, 8) == []
    d3, = E.draw_list(m, 3)
    assert d3["m"] == (0.5, 0.0, 0.0, 0.5, 10.0, 0.0) and d3["mul"][3] == 0.5
    d5, = E.draw_list(m, 5)
    assert d5["m"] == (1.0, 0.0, 0.0, 1.0, 120.0, 50.0)          # parent (2x, +100,+50) then child
    assert d5["path"] == ["G", "Pic"]
    assert E.draw_list(m, 5, hidden={1}) == []


def test_a_labelled_sprite_rests_settled_unless_pinned_and_a_plain_one_plays():
    states = {"kind": "Sprite", "frames": 6, "labels": [["A", 1], ["B", 4]],
              "kids": [N(10, "Fade", [9],
                         col=((1, (1, 1, 1, 0), (0,) * 4), (2, (1, 1, 1, 1), (0,) * 4))),
                       N(11, "OnlyB", [9], kf=((1, 0), (4, 1)))]}
    loop = {"kind": "Sprite", "frames": 3, "labels": [],
            "kids": [N(12, "F1", [9], kf=((1, 1), (2, 0))), N(13, "F2", [9], kf=((1, 0), (2, 1)))]}
    m = man([N(1, "States", [2]), N(3, "Loop", [4])], {2: states, 4: loop, 9: BMP})
    names = lambda ds: [d["path"][-1] for d in ds]                       # noqa: E731
    assert names(E.draw_list(m, 1)) == ["Fade", "F1"]                    # A settled at its frame 2
    assert names(E.draw_list(m, 2)) == ["Fade", "F2"]                    # the loop plays
    assert names(E.draw_list(m, 1, pins={1: 4})) == ["Fade", "OnlyB", "F1"]
    assert [s[0] for s in E.seekable(m)] == [1]


def test_the_default_still_is_the_fullest_frame_on_the_glass():
    m = man([N(1, "In", [9], kf=((1, 1), (6, 0))),
             N(2, "Late", [9], kf=((1, 0), (4, 1))),
             N(3, "Off", [9], kf=((1, 1),), tr=((1, (1, 0, 0, 1, -500, 0)),))],
            {9: BMP})
    assert E.default_frame(m) == 4


def _red_project(tmp_path):
    d = tmp_path / "images" / "scene_textures"
    d.mkdir(parents=True)
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(d / "red.png")
    return str(tmp_path)


def test_the_renderer_places_by_the_whole_affine_and_fades_by_the_tint(tmp_path):
    assets = _red_project(tmp_path)
    m = man([N(1, "Big", [9], tr=((1, (2, 0, 0, 3, 50, 20)),)),
             N(2, "Half", [9], tr=((1, (1, 0, 0, 1, 150, 70)),),
               col=((1, (1, 1, 1, 0.5), (0,) * 4),))], {9: BMP})
    img = np.asarray(R.render_tree(assets, m, 1))
    red = img[..., 0] > 200
    ys, xs = np.where(red)
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (50, 69, 20, 49)   # 20 x 30
    assert 120 <= img[75, 155, 0] <= 135                                  # half faded


def test_a_tilt_turns_the_picture(tmp_path):
    assets = _red_project(tmp_path)
    import math
    c, s = math.cos(math.pi / 4), math.sin(math.pi / 4)
    m = man([N(1, "Tilt", [9], tr=((1, (c * 4, s * 4, -s * 4, c * 4, 100, 20)),))], {9: BMP})
    img = np.asarray(R.render_tree(assets, m, 1))
    ys, xs = np.where(img[..., 0] > 200)
    # a 40x40 square turned 45 degrees about its top-left corner spans ~56 px each way
    assert 52 <= xs.max() - xs.min() <= 60 and 52 <= ys.max() - ys.min() <= 60


def _glyphs(pad, scale, n=20):
    out = []
    for i in range(n):
        w, h = 30 + i * 3, 40 + (i % 5) * 4
        out.append({"w": w + 2 * pad, "h": h + 2 * pad, "rot": False,
                    "lw": round(w * scale), "lh": round(h * scale)})
    return out


def test_cell_fit_finds_the_outline_margin_and_leaves_a_plain_cell_alone():
    pad, scale = fontrender.cell_fit(_glyphs(16, 0.9))
    assert abs(pad - 16) <= 0.75 and abs(scale - 0.9) < 0.02
    assert fontrender.cell_fit(_glyphs(0, 1.0)) == (0.0, None)


# ---------------------------------------------------------------------------------------------
# the real Godzilla LE 1.16 scenes and the stock extract (skipped when absent)
# ---------------------------------------------------------------------------------------------
SCENES = os.environ.get("PAD_SCENE_DIR", r"c:\tmp\pad251")
PROJECT = os.environ.get("PAD_GZ_PROJECT", r"C:\Users\david\OneDrive\Desktop\gzho")
EMU_LANGUAGE = os.environ.get(
    "PAD_EMU_LANGUAGE", r"C:\Users\david\Documents\development\pad-triage\work\artifacts"
    r"\PAD-154\before_emulator_language.png")


def _manifest(name):
    from pinball_decryptor.plugins.stern import engine, radium, scene_tree
    path = os.path.join(SCENES, name + ".radium")
    if not os.path.isfile(path) or not os.path.isdir(PROJECT):
        pytest.skip("stock scene or extract not present")
    data = open(path, "rb").read()
    sc = scene_tree.parse(data)
    imgs = engine.parse_radium_images(data)
    tables = radium.parse_glyph_tables(data, imgs)
    rels = engine._radium_image_rels(PROJECT)
    off2rel = rels[[k for k in rels if name in k][0]]
    return E.manifest(sc, off2rel, E.font_sizes(sc, data, imgs, tables, off2rel))


def test_battle_select_shows_one_kaiju_per_state_and_its_title_on_the_glass():
    m = _manifest("cac32730")
    assert E.default_frame(m) == 45                        # OverlayFadeIn_End
    sel = [s for s in E.seekable(m) if s[1][-1] == "CharacterSelect_Instance"][0]
    for label, start in (("Ebirah", 1), ("Gigan", 16), ("Titan", 31)):
        drawn = E.draw_list(m, 45, pins={sel[0]: start + 3})
        bodies = {d["path"][2] for d in drawn if len(d["path"]) > 2
                  and d["path"][2].endswith("FullBody_instance")}
        assert bodies == {label + "FullBody_instance"}
    title = [d for d in E.draw_list(m, 45) if d["kind"] == "text"
             and d["text"] == "KAIJU BATTLE SELECT"][0]
    top = title["m"][5] + title["rect"][1]
    assert 50 <= top <= 60                                 # on the glass, not above it


def test_the_language_screen_text_lands_on_the_emulators_pixels():
    if not os.path.isfile(EMU_LANGUAGE):
        pytest.skip("emulator capture not present")
    m = _manifest("762a9b99")
    img = np.asarray(R.render_tree(PROJECT, m).convert("RGB")).astype(int)
    real = np.asarray(Image.open(EMU_LANGUAGE).convert("RGB")).astype(int)

    def box(a):
        sub = a[680:768, 40:960]
        ys, xs = np.where(sub.min(axis=2) > 200)
        return xs.min() + 40, ys.min() + 680, xs.max() + 40, ys.max() + 680

    ours, theirs = box(img), box(real)
    assert all(abs(a - b) <= 4 for a, b in zip(ours, theirs)), (ours, theirs)
