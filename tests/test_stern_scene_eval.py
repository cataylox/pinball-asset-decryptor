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


def test_the_selections_layers_compose_to_the_same_picture(tmp_path):
    """The editor moves a selection's own pixels while it is dragged: render_tree(split=)
    draws what is under it, it and what is over it apart, and the scene composed from the three
    is the plain render to the pixel (premultiplied "over" is associative)."""
    assets = _red_project(tmp_path)
    m = man([N(1, "Back", [9], tr=((1, (6, 0, 0, 6, 10, 10)),)),
             N(2, "Mid", [9], tr=((1, (4, 0, 0, 4, 40, 30)),),
               col=((1, (0.2, 1, 1, 0.6), (0,) * 4),)),
             N(3, "Front", [9], tr=((1, (3, 0, 0, 3, 55, 40)),),
               col=((1, (1, 1, 1, 0.5), (0,) * 4),))], {9: BMP})
    draws = E.draw_list(m, 1)
    for bg in (None, R.BACKGROUND_NAMES[-1]):
        plain = np.asarray(R.render_tree(assets, m, 1, background=bg)).astype(int)
        got = R.render_tree(assets, m, 1, background=bg, draws=draws, split={1})
        assert np.abs(np.asarray(got["full"]).astype(int) - plain).max() == 0
    sel = np.asarray(got["sel"])
    ys, xs = np.where(sel[..., 3] > 0)
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (40, 79, 30, 69)     # Mid alone
    assert np.asarray(got["over"])[..., 3].max() > 0 and got["under"].mode == "RGB"


def test_a_long_idle_loop_settles_without_drawing_every_frame():
    """A labelled sprite rests where most of it is on the glass within its first label's span;
    a 2,460-frame idle loop (a Godzilla attract scene took 93 s to open) is sampled, and a
    labelled sprite inside another is settled once per place, not once per frame tried."""
    import time
    inner = {"kind": "Sprite", "frames": 5000, "labels": [["Idle", 1], ["Out", 4990]],
             "kids": [N(20, "Blink", [9], kf=[(f, f % 2) for f in range(1, 4990, 7)])]}
    outer = {"kind": "Sprite", "frames": 3000, "labels": [["Loop", 1], ["End", 2990]],
             "kids": [N(10, "Inner%d" % i, [4]) for i in range(6)]}
    m = man([N(1, "Attract", [2])], {2: outer, 4: inner, 9: BMP}, frames=40)
    t = time.time()
    rest = E.default_frame(m)
    draws = E.draw_list(m, rest)
    assert time.time() - t < 5.0
    assert 1 <= rest <= 40 and draws and all(d["path"][-1] == "Blink" for d in draws)



def test_a_line_wraps_in_its_box_where_its_flag_says_and_breaks_at_newlines():
    """DragonRR's Battle Select: the machine draws "USE FLIPPERS TO / CHANGE BATTLE" on two
    lines inside a box too narrow for one; the preview drew one long line.  A Text whose first
    flag byte is set wraps at its rect's width (at spaces; a too-long word stays whole), every
    Text breaks at a \\n, and a manifest from before the flags were recorded wraps a box tall
    enough for two lines."""
    measure = len
    assert R.text_lines("USE FLIPPERS TO CHANGE MONSTER", 16, True, measure) == \
        ["USE FLIPPERS TO", "CHANGE MONSTER"]
    assert R.text_lines("USE FLIPPERS TO CHANGE MONSTER", 16, False, measure) == \
        ["USE FLIPPERS TO CHANGE MONSTER"]
    assert R.text_lines("PARTICIPATE IN\nLOCAL TOURNAMENTS!", 99, False, measure) == \
        ["PARTICIPATE IN", "LOCAL TOURNAMENTS!"]
    assert R.text_lines("A SUPERCALIFRAGILISTIC B", 5, True, measure) == \
        ["A", "SUPERCALIFRAGILISTIC", "B"]
    assert R._wraps({"flags": [1, 1]}, 30, 36) and not R._wraps({"flags": [0, 0]}, 300, 36)
    assert R._wraps({}, 82, 36) and not R._wraps({}, 51, 36)       # older manifests


def test_the_manifest_carries_a_texts_flags_to_the_draw():
    from pinball_decryptor.plugins.stern import scene_tree
    from tests.test_stern_scene_tree import scene
    sc = scene_tree.parse(scene())
    m = E.manifest(sc, {})
    assert m["v"] == E.MANIFEST_VERSION >= 3
    texts = [o for o in m["objects"].values() if o.get("kind") == "Text"]
    assert texts and all(isinstance(o.get("flags"), list) and len(o["flags"]) == 2 for o in texts)
    draws = [d for d in E.draw_list(m, 1) if d["kind"] == "text"]
    assert draws and all("flags" in d for d in draws)


def test_battle_select_wraps_its_instructions_like_the_machine():
    """On the real card (skipped without it): the two instruction lines each take two rows
    inside their boxes, as DragonRR's emulator screenshot shows."""
    import json
    proj = r"C:\tmp\pad251\projL"
    path = os.path.join(proj, "images", "scene_textures", "scene_tree.json")
    if not os.path.isfile(path):
        pytest.skip("needs the PAD-251 Godzilla project copy")
    trees = json.load(open(path, encoding="utf-8"))
    man = next((m for c, m in trees.items() if "cac32730" in c), None)
    if man is None or man.get("v", 0) < 3:
        pytest.skip("the project copy's manifest predates the text flags")
    draws = E.draw_list(man, E.default_frame(man))
    fonts = fontrender.load_fonts(proj)
    for want in ("USE FLIPPERS TO CHANGE MONSTER", "USE ACTION BUTTON TO SELECT"):
        d = next(x for x in draws if x["kind"] == "text" and x["text"] == want)
        img = np.asarray(R.render_tree(proj, man, draws=[d], fonts=fonts))
        ys = np.where(img[..., :3].max(axis=2).max(axis=1) > 120)[0]
        rows = np.split(ys, np.where(np.diff(ys) > 4)[0] + 1)
        assert len(rows) == 2, (want, [(r[0], r[-1]) for r in rows])
        assert 30 <= rows[1][0] - rows[0][0] <= 42          # one declared line (36) apart


def test_a_straight_alpha_replacement_is_premultiplied_like_the_write_does(tmp_path):
    """DragonRR: a replaced picture with a soft white edge drew a solid white halo in the
    Scenes preview (and not while dragged). Card pictures are premultiplied and the renderer
    blends them so; an editor's PNG has straight alpha, which the Write premultiplies
    (engine._premultiply_like_stock) - the preview now does the same, and leaves card
    pictures as they are."""
    assets = _red_project(tmp_path)
    glow = np.zeros((10, 10, 4), np.uint8)
    glow[..., :3] = 255                      # white...
    glow[..., 3] = 20                        # ...but nearly transparent
    Image.fromarray(glow, "RGBA").save(os.path.join(assets, "images", "scene_textures", "red.png"))
    m = man([N(1, "Glow", [9], tr=((1, (4, 0, 0, 4, 20, 20)),))], {9: BMP})
    img = np.asarray(R.render_tree(assets, m, 1))
    assert img[40, 40].max() < 40                               # a faint glow, not a white box
    stock = np.zeros((10, 10, 4), np.uint8)
    stock[..., 0] = stock[..., 3] = 200                        # premultiplied: RGB <= A
    pic = Image.fromarray(stock, "RGBA")
    assert R._premultiplied(pic, "k", {}) is pic               # a card picture is untouched


def test_a_sprite_that_slides_in_rests_where_it_stops_on_the_screen():
    """DragonRR: the HUD's power meter drew half off the screen. Its sprite's first label
    span is its entrance (sliding in from the left); the game holds it at a later label
    (Energy Meter Onscreen). A sprite still hanging off the screen at its first span's best
    frame rests on the first later label where it holds still, further on the screen."""
    slide = [(f, (1, 0, 0, 1, -300 + 70 * (f - 1), 10)) for f in range(1, 5)] + [(5, (1, 0, 0, 1, 10, 10))]
    meter = {"kind": "Sprite", "frames": 8, "labels": [["Enter Start", 1], ["Onscreen", 5], ["Exit", 7]],
             "kids": [N(10, "Bar", [9], tr=slide)]}
    big = dict(BMP, w=100, h=20)
    m = man([N(1, "Meter", [2])], {2: meter, 9: big}, frames=3)
    d, = E.draw_list(m, 1)
    assert E.outline(d)[0][0] == 10                        # at rest where the game keeps it
    # a sprite whose first span is already on the screen keeps the first-span rule
    held = {"kind": "Sprite", "frames": 6, "labels": [["A", 1], ["B", 4]],
            "kids": [N(10, "Bar", [9], tr=((1, (1, 0, 0, 1, 20, 10)), (4, (1, 0, 0, 1, 90, 10))))]}
    m2 = man([N(1, "Meter", [2])], {2: held, 9: big}, frames=3)
    d, = E.draw_list(m2, 1)
    assert E.outline(d)[0][0] == 20


def test_an_entrance_rests_where_it_leads_and_plays_from_its_start():
    """DragonRR: Battle Select never showed the selected kaiju's tile in colour, and the
    Godzilla logo showed only its first flame. A sprite whose first label begins an entrance
    (FadeIn / Reveal / Enter ...) rests on the first later label that is not part of it (or
    the entrance's own end); Play runs the entrance from its start and holds there."""
    frames = [N(10 + i, "F%d" % i, [9], kf=((1, 0), (i + 1, 1), (i + 2, 0)) if i < 9 else ((1, 0), (10, 1)))
              for i in range(10)]
    logo = {"kind": "Sprite", "frames": 10, "labels": [["LogoReveal_Start", 1], ["LogoReveal_End", 10]],
            "kids": frames}
    m = man([N(1, "Logo", [2])], {2: logo, 9: BMP}, frames=12)
    assert E.entrance_rest(logo) == (1, 10)
    assert [d["path"][-1] for d in E.draw_list(m, 1)] == ["F9"]                    # at rest: whole
    assert [d["path"][-1] for d in E.draw_list(m, 1, play=True)] == ["F0"]         # playing
    assert [d["path"][-1] for d in E.draw_list(m, 5, play=True)] == ["F4"]
    assert [d["path"][-1] for d in E.draw_list(m, 12, play=True)] == ["F9"]        # holds
    picker = {"labels": [["Ebirah_FadeIn_Start", 1], ["Ebirah_FadeIn_End", 4],
                         ["Ebirah_Selected_Start", 5], ["Ebirah_Selected_End", 9]]}
    assert E.entrance_rest(picker) == (1, 5)
    states = {"labels": [["Locked", 1], ["Completed", 2], ["Tokyo", 3]]}
    assert E.entrance_rest(states) is None                                          # not an entrance


def test_a_peeked_layer_in_a_hidden_sprite_is_drawn_alone():
    """DragonRR (PAD-284): picking the Gigan text box, which sits in a body the game has off
    at this moment, drew the whole body - its picture and every other layer in it.  The
    sprites it sits in are only its way in (*through*); peeking the body draws all of it."""
    body = {"kind": "Sprite", "frames": 1, "labels": [],
            "kids": [N(20, "Art", [9]), N(21, "Textbox", [9]), N(22, "Glow", [9])]}
    states = {"kind": "Sprite", "frames": 2, "labels": [["A", 1], ["B", 2]],
              "kids": [N(10, "BodyA", [9], kf=((1, 1), (2, 0))),
                       N(11, "BodyB", [3], kf=((1, 0), (2, 1)))]}
    m = man([N(1, "Select", [2])], {2: states, 3: body, 9: BMP})
    names = lambda ds: [d["path"][-1] for d in ds]                       # noqa: E731
    assert names(E.draw_list(m, 1)) == ["BodyA"]
    worlds = {}
    got = E.draw_list(m, 1, show=21, force={1, 11, 21}, through={1, 11}, worlds=worlds)
    assert names(got) == ["BodyA", "Textbox"]
    assert 21 in worlds and 20 not in worlds and 22 not in worlds
    assert names(E.draw_list(m, 1, show=11, force={1, 11})) == ["BodyA", "Art", "Textbox", "Glow"]
    # a sprite the timeline draws anyway is drawn whole, through or not
    assert names(E.draw_list(m, 1, pins={1: 2}, show=21, force={1, 11, 21},
                             through={1, 11})) == ["Art", "Glow", "Textbox"]


def test_a_peeked_sprite_unveils_the_layers_hidden_with_their_eye():
    """DragonRR (PAD-289): picking a sprite shows every layer in it, those hidden with their
    eye too.  The eye keeps the layer's own timeline in ``_kf``; *unveil* draws by that."""
    art = N(20, "Art", [9], kf=((1, 0),))
    art["_kf"] = [[1, 1]]                               # hidden with its eye
    body = {"kind": "Sprite", "frames": 1, "labels": [], "kids": [art, N(21, "Textbox", [9])]}
    m = man([N(1, "Body", [3]), N(2, "Over", [9])], {3: body, 9: BMP})
    names = lambda ds: [d["path"][-1] for d in ds]                       # noqa: E731
    assert names(E.draw_list(m, 1)) == ["Textbox", "Over"]
    assert names(E.draw_list(m, 1, show=1)) == ["Over", "Textbox"]
    assert names(E.draw_list(m, 1, show=1, unveil={20})) == ["Over", "Art", "Textbox"]


def test_battle_select_peeks_the_gigan_text_box_alone():
    m = _manifest("cac32730")
    by = {}
    parents = {}

    def walk(kids, par):
        for n in kids:
            by.setdefault(n["name"], []).append(n["id"])
            parents[n["id"]] = par
            for _s, oid in n["comps"]:
                o = m["objects"].get(str(oid)) or {}
                walk(o.get("kids") or (), n["id"])
    walk(m["root"]["kids"], None)
    box = by["Gigan_Textbox_instance"][0]
    up, p = set(), parents[box]
    while p is not None:
        up.add(p)
        p = parents[p]
    got = E.draw_list(m, 45, show=box, force=up | {box}, through=up)
    plain = E.draw_list(m, 45)
    assert len(got) == len(plain) + 1 and got[-1]["node"] == box
