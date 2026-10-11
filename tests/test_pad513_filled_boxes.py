"""PAD-513 (DragonRR): Scenes marked boxes the game never fills as "filled in by the game".

On Godzilla's Tank Attack Multiball start screen every T of TANK ATTACK (a letter to a box)
read as filled with a stray, unused " T!" of the game program's, and the MULTIBALL title with
a MULTIBALL the game shows elsewhere; the Tank Attack code names only the instruction line on
that screen.  A line the game never reads and a single letter are no stand-ins, and on a
screen whose text boxes a mode's code names, matching words count only on those boxes or for
that mode's own lines."""

import pytest

from tests.test_gui_scene_editor import _tv
from tests.test_pad485_game_line_in_scenes import _project, _wait
from tests.webui_harness import web_app

pytest.importorskip("PIL")


def test_rules_an_unused_line_or_a_letter_fills_nothing():
    from pinball_decryptor.webui import text_rules as R
    rows = [{"path": "/g/game", "original": " T!", "replacement": ""},
            {"path": "/g/game", "original": "STRAY", "replacement": "", "unused": True},
            {"path": "/g/game", "original": "MULTIBALL", "replacement": ""},
            {"path": "/g/game", "original": "GIGAN JACKPOT!", "replacement": "",
             "modes": ["cmode_battle_vs_megalon_and_gigan_mb"]},
            {"path": "/g/s/scene.radium", "original": "TANK", "replacement": ""}]
    idx = R.filled_index(rows)
    assert "T" not in idx and "STRAY" not in idx and "TANK" not in idx
    assert idx["MULTIBALL"] == [("MULTIBALL", [])]
    assert idx["GIGAN JACKPOT"][0][0] == "GIGAN JACKPOT!"


def test_rules_a_placeholder_is_the_games_to_fill():
    """Round 2: words that only hold a place - a score, a count, a line of instructions -
    are written over by the game; a name with an X in it is not one."""
    from pinball_decryptor.webui import text_rules as R
    for s in ("XXX,XXX,XXX", "XXXXXXXXXX", "X,XXX,XXX", "00", "0", "LINE 1 INSTRUCTIONS",
              "Line 2", "LINE12", "INSTRUCTIONS ", "AWARDS +XX FLIPS",
              "COLLECT XX MORE TO START TANK ATTACK MULTIBALL"):
        assert R.is_placeholder(s), s
    for s in ("PLANET X", "DESTROY X MORE TANKS", "EXXON", "MULTIBALL", "LINE", "1,000,000",
              "BRIDGE ATTACK", ""):
        assert not R.is_placeholder(s), s


def _score_scene():
    """The synthetic scene with its title reading XXX,XXX,XXX, as a score box does."""
    from tests.test_stern_scene_tree import FLAG, bitmap, cls, fs, node, sprite, text, texture, u32, u64, u8
    kids = [
        node(50, "Art", [u32(1) + cls(1, "Bitmap") + u32(FLAG | 12) + bitmap(3, 16, 8, texture(21, 16, 8))]),
        node(53, "Score", [u32(1) + cls(3, "Text") + u32(FLAG | 13) + text(5, "XXX,XXX,XXX", (9, 7))]),
    ]
    root = sprite(2, "", 20, kids, labels=[("Start", 1), ("End", 20)])
    return (u8(1) + u64(0) + u64(0) + u32(1360) + u32(768) + fs(30.0) + fs(0.2, 0.2, 0.2, 1.0) + root)


def _layers(w):
    return {l["name"] + str(l["depth"]): l["filled"] for l in _tv(w)["layers"]}


def _open(w, folder):
    w.run(lambda: w.window.write_assets_var.set(str(folder)))
    w.call("ui.select_tab", "scenes")
    w.call("text_scenes.select", "/g/scene1")
    _wait(w, lambda: (w.state("text_scenes").get("frames") or []) != [])


def test_a_screen_whose_boxes_a_mode_names_keeps_its_own_words(tmp_path):
    """The scene's two KAIJU titles match the game's KAIJU, a line no mode reads.  With no
    mode naming the screen both read as filled, as before; once the battle vs Gigan's code
    names the screen with its Award_Textbox.Title, only that box is filled."""
    gigan = "cmode_battle_vs_gigan"
    from pinball_decryptor.plugins.stern import engine
    plain = tmp_path / "plain"
    plain.mkdir()
    folder = _project(plain, {"original": "KAIJU"}, two=True)
    with web_app(plain, mfr="stern") as w:
        _open(w, folder)
        layers = _layers(w)
        assert layers["Title0"] == layers["Title1"] == {"line": "KAIJU", "modes": []}
        w.call("text_scenes.close")
    named = tmp_path / "named"
    named.mkdir()
    folder = _project(named, {"original": "KAIJU"}, two=True)
    engine._program_modes_read(str(folder), {gigan: ["g/scene1"]},
                               {gigan: {"g/scene1": ["Award_Textbox.Title"]}})
    with web_app(named, mfr="stern") as w:
        _open(w, folder)
        layers = _layers(w)
        assert layers["Title0"] is None                     # the screen's own words
        assert layers["Title1"] == {"line": "KAIJU", "modes": []}
        assert layers["Art0"] is None
        w.call("text_scenes.close")


def test_godzilla_le_116_modes_name_the_boxes_they_fill():
    """Round 2 (DragonRR: "Have you checked elsewhere?").  Read from the stock card, the
    boxes each mode names with a screen.  Bridge Attack's super jackpot intro fills BRIDGE,
    ATTACK and MULTIBALL (lines 3424-3426, so they show in the player's language); its
    MULTIBALL box sits 0x228 bytes on in the function and was missed.  The other Tank Attack
    screen names Title_Instance by the tail of "SwitchMeter.Title_Instance".  DragonRR's
    Tank Attack start screen still names only its instruction line."""
    from tests.test_pad470_text_modes import LE116, _program
    from pinball_decryptor.plugins.stern import progtext
    raw = _program(LE116)
    ctx = {}
    progtext.enumerate_program_strings(raw, modes=True, ctx=ctx)
    tank = "687f744516db566f57937aa3345db2e82c3e10ea/"
    bridge = ctx["boxes"]["cmode_bridge_attack_multiball"][
        "fb84341a4f335f98b218a0a03136f3c1e6d88a29/7ec20395bac789edbbc33befe4eed2e0dd589de5"]
    assert bridge == ["Bridge_Textbox.Bridge_Instance", "Attack_Textbox.Attack_Instance",
                      "Multiball_Textbox.Mulitball_Instance"]
    boxes = ctx["boxes"]["cmode_tank_attack_multiball"]
    assert boxes[tank + "bf1c6b2c10e0e4d88a62b43abed5a21fc6b07a63"] == ["Title_Instance",
                                                                       "Line1_Instance"]
    assert boxes[tank + "4567f96cb9de3e97ef274b7cec9e74f7ddd8298b"] == ["Line1_Instance"]


def test_a_score_placeholder_is_marked_with_no_line_to_name(tmp_path):
    """A box reading XXX,XXX,XXX is filled in by the game (its score), with no line of the
    game's text and no mode to name."""
    from pinball_decryptor.core import text_manifest
    from tests.test_gui_scene_editor import _seed
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _score_scene())
    text_manifest.save(str(folder), [
        {"path": "/g/scene1/scene.radium", "original": "XXX,XXX,XXX", "replacement": ""},
        {"path": "/g/game", "original": "TILT", "replacement": "", "budget": 4, "fixed": True}])
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        layers = _layers(w)
        assert layers["Score0"] == {"line": None, "modes": []}
        assert layers["Art0"] is None
        w.call("text_scenes.close")
