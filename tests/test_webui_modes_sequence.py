"""PAD-314 in the web Modes tab: a mode started by shots made in order, and one ended by any shot that
does not score. The form's fields reach the saved mode.json and come back, and the Scoring page's
"Ends early when hit" list now sits under Ends on with the new entry."""

import json

from pinball_decryptor.plugins.stern import mode_project as MP
from tests.test_webui_modes import GODZILLA_CARD, _card_project, _project, _wait, preview_on  # noqa: F401
from tests.webui_harness import web_app


def test_the_sequence_and_the_end_shot_round_trip(tmp_path, preview_on):
    proj = _card_project(tmp_path / "gz", GODZILLA_CARD)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        slug = w.call("modes.new")
        st = w.state("modes")
        f = st["form"]
        assert f["starts_kind"] == "shot" and f["seq_reset_any"] is False
        assert all(f["seq_shot_%d" % i] == "(no more shots)" for i in range(8))
        assert f["end_shot"] == "(no shot)" and st["end_shots_on"] == []
        assert st["profile"]["end_shots"] == ["(no shot)", MP.END_SHOT_OTHERS, "(these shots)"]

        path = proj / "modes" / slug / "mode.json"
        w.call("ui.set", "modes", "f:starts_kind", "sequence")
        for i, shot in enumerate(["Left ramp", "Right ramp", "Left ramp", "Right ramp", "Building"]):
            w.call("ui.set", "modes", "f:seq_shot_%d" % i, shot)
        w.call("ui.set", "modes", "f:seq_reset_any", True)
        w.call("ui.set", "modes", "f:end_shot", MP.END_SHOT_OTHERS)

        def saved():
            d = json.loads(path.read_text("utf-8"))
            return (d.get("starts_on"), d.get("start_sequence"), d.get("sequence_reset_any"), d.get("end_shot")) == \
                ("sequence", ["Left ramp", "Right ramp", "Left ramp", "Right ramp", "Building"], True, MP.END_SHOT_OTHERS)
        assert _wait(w, saved)
        st = w.state("modes")
        assert st["status"] == "Ready to build."
        spec = MP.ModeSpec.from_json(json.loads(path.read_text("utf-8")))
        text = MP.runtime_cfg(spec, slug)
        assert "starts_on      sequence" in text and text.count("trigger_seq    0x") == 5
        assert "trigger_seq_reset" in text and "end_shot" in text and "\ntrigger " not in text

        # a sequence of one is refused, on the Mode page
        for i in range(1, 5):
            w.call("ui.set", "modes", "f:seq_shot_%d" % i, "(no more shots)")
        assert _wait(w, lambda: "Pick at least two shots, in order" in (w.state("modes")["status"] or ""))
        assert w.state("modes")["fix_pages"] == ["mode"]

        # reopening the mode shows the same fields
        w.call("ui.set", "modes", "f:seq_shot_1", "Right ramp")
        assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
        w.call("modes.new")
        w.call("modes.select", slug, "form")
        f = w.state("modes")["form"]
        assert f["starts_kind"] == "sequence" and f["seq_reset_any"] is True
        assert (f["seq_shot_0"], f["seq_shot_1"], f["seq_shot_2"]) == ("Left ramp", "Right ramp", "(no more shots)")
        assert f["end_shot"] == MP.END_SHOT_OTHERS

        # the multi-select: (these shots) + ticks save a list; a tick-less pick is refused on the Mode page
        w.call("ui.set", "modes", "f:end_shot", "(these shots)")
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("end_shot") == [])
        assert "Tick a shot that ends the mode" in w.state("modes")["status"]
        assert w.state("modes")["fix_pages"] == ["mode"]
        w.call("ui.set", "modes", "endshot:Building", True)
        w.call("ui.set", "modes", "endshot:Godzilla target", True)
        w.call("ui.set", "modes", "endshot:Building", True)          # already on: no change
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("end_shot") == ["Building", "Godzilla target"])
        st = w.state("modes")
        assert st["status"] == "Ready to build." and st["end_shots_on"] == ["Building", "Godzilla target"]
        w.call("ui.set", "modes", "endshot:Building", False)
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("end_shot") == ["Godzilla target"])
        w.call("modes.new")
        w.call("modes.select", slug, "form")
        st = w.state("modes")
        assert st["form"]["end_shot"] == "(these shots)" and st["end_shots_on"] == ["Godzilla target"]
        # a mode saved before the list form, with one name, opens as a pick of that one
        d = json.loads(path.read_text("utf-8"))
        d["end_shot"] = "Maser target"
        path.write_text(json.dumps(d), "utf-8")
        w.call("modes.new")
        w.call("modes.select", slug, "form")
        st = w.state("modes")
        assert st["form"]["end_shot"] == "(these shots)" and st["end_shots_on"] == ["Maser target"]
        w.call("ui.set", "modes", "f:end_shot", MP.END_SHOT_OTHERS)
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("end_shot") == MP.END_SHOT_OTHERS)

        # back to its shot: the sequence is kept in the file but not written to the card
        w.call("ui.set", "modes", "f:starts_kind", "shot")
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("starts_on") == "shot")
        spec = MP.ModeSpec.from_json(json.loads(path.read_text("utf-8")))
        assert spec.start_sequence == ["Left ramp", "Right ramp"]
        assert "trigger_seq" not in MP.runtime_cfg(spec, slug)
