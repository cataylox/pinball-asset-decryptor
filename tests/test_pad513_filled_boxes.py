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
