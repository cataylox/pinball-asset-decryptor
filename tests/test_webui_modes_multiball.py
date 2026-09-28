"""Item 167 in the web Modes tab: the Multiball section is greyed with the port's reason until the
build is emulator-proven, the page gets the add-a-ball shot list, and the form's fields reach the
saved mode.json and come back."""

import json

from pinball_decryptor.plugins.stern import mode_project as MP
from tests.test_webui_modes import GODZILLA_CARD, _card_project, _project, _wait, preview_on  # noqa: F401
from tests.webui_harness import web_app


def test_multiball_is_greyed_until_proven_and_the_fields_round_trip(tmp_path, preview_on):
    proj = _card_project(tmp_path / "gz", GODZILLA_CARD)
    proven = "godzilla_pro-1.15" in MP.MULTIBALL_PROVEN
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        slug = w.call("modes.new")
        st = w.state("modes")
        assert st["dis"]["multiball"] is (not proven)
        if proven:
            assert "multiball" not in st["reasons"]
        else:
            assert st["reasons"]["multiball"].startswith(
                "Not on this game: The app has found how Godzilla Pro 1.15 serves the balls of a multiball")
        assert st["profile"]["ball_shots"][0] == "(none)" and "Maser target" in st["profile"]["ball_shots"]
        assert st["spin"]["balls"] == [2, 6] and st["spin"]["seconds"] == [0, 300]
        f = st["form"]
        assert f["multiball"] is False and f["balls"] == "3" and f["ball_save"] == "10"
        assert f["add_ball_shot"] == "(none)" and f["add_ball_max"] == "1"
        # PAD-228: the balls come when it starts, or on a shot the page lists (the Action button among them)
        assert f["mb_on_shot"] == "(when it starts)"
        assert st["profile"]["mb_on_shots"][0] == "(when it starts)" and "Action button" in st["profile"]["mb_on_shots"]

        # the edits save themselves into mode.json as the model's fields
        path = proj / "modes" / slug / "mode.json"
        w.call("ui.set", "modes", "f:multiball", True)
        w.call("ui.set", "modes", "f:balls", "4")
        w.call("ui.set", "modes", "f:ball_save", "20")
        w.call("ui.set", "modes", "f:add_ball_shot", "Maser target")
        w.call("ui.set", "modes", "f:add_ball_max", "2")
        w.call("ui.set", "modes", "f:seconds", "0")

        def saved():
            d = json.loads(path.read_text("utf-8"))
            return (d.get("multiball"), d.get("balls"), d.get("ball_save"), d.get("add_ball_shot"),
                    d.get("add_ball_max"), d.get("seconds")) == (True, 4, 20, "Maser target", 2, 0)
        assert _wait(w, saved)
        st = w.state("modes")
        if proven:
            assert st["status"] == "Ready to build."
        else:                                   # refused on the Mode page, with the reason there
            assert st["fix_pages"] == ["mode"]
            assert "A multiball of the mode's own is not on Godzilla Pro 1.15 yet" in st["status"]

        # reopening the mode shows the same fields
        w.call("modes.new")
        w.call("modes.select", slug, "form")
        f = w.state("modes")["form"]
        assert f["multiball"] is True and f["balls"] == "4" and f["ball_save"] == "20"
        assert f["add_ball_shot"] == "Maser target" and f["add_ball_max"] == "2" and f["seconds"] == "0"
        # (none) again means no add-a-ball shot in the file
        w.call("ui.set", "modes", "f:add_ball_shot", "(none)")
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("add_ball_shot") == "")
        # PAD-228: the balls on the Action button, and back to the start
        w.call("ui.set", "modes", "f:mb_on_shot", "Action button")
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("multiball_on_shot") == "Action button")
        w.call("modes.new")
        w.call("modes.select", slug, "form")
        assert w.state("modes")["form"]["mb_on_shot"] == "Action button"
        w.call("ui.set", "modes", "f:mb_on_shot", "(when it starts)")
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("multiball_on_shot") == "")


def test_ball_save_is_greyed_until_proven_and_its_fields_round_trip(tmp_path, preview_on):
    """PAD-225: a ball save when the mode starts, with no multiball - its own section on the Mode page."""
    proj = _card_project(tmp_path / "gz", GODZILLA_CARD)
    proven = "godzilla_pro-1.15" in MP.BALL_SAVE_PROVEN
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        slug = w.call("modes.new")
        st = w.state("modes")
        assert st["dis"]["ball_save"] is (not proven)
        if not proven:
            assert st["reasons"]["ball_save"].startswith(
                "Not on this game: The app has found how Godzilla Pro 1.15 saves a ball")
        assert st["spin"]["start_save_s"] == [1, 60]
        f = st["form"]
        assert f["start_save"] is False and f["start_save_s"] == "10"

        path = proj / "modes" / slug / "mode.json"
        w.call("ui.set", "modes", "f:start_save", True)
        w.call("ui.set", "modes", "f:start_save_s", "15")
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("start_ball_save") == 15)
        st = w.state("modes")
        if proven:
            assert st["status"] == "Ready to build."
        else:
            assert st["fix_pages"] == ["mode"]
            assert "A ball save of the mode's own is not on Godzilla Pro 1.15 yet" in st["status"]

        w.call("modes.new")
        w.call("modes.select", slug, "form")
        f = w.state("modes")["form"]
        assert f["start_save"] is True and f["start_save_s"] == "15"
        # unticked: no ball save in the file, and the seconds shown go back to 10 on the next open
        w.call("ui.set", "modes", "f:start_save", False)
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("start_ball_save") == 0)
