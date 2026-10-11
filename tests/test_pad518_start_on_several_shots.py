"""PAD-518: a mode started by the hits of up to three shots counted together, up to 999 of them.

The owner's ask: "count up to 120 bumper hits", on three bumper switches. mode_file.c already counts every hit
of any shot in the `trigger` line's bits toward its count; the Modes tab took one shot and 1-20 hits. Now
``start_or`` names up to two more shots whose bits go into the same `trigger` line, and the count goes to 999.

The runtime half compiles mode_file.c for the HOST against test_spike2_mode_roster.py's stub of the SDK calls,
so it runs wherever an ELF C compiler is (skips otherwise).
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_spike2_mode_roster import _run, harness  # noqa: E402,F401  (harness is a fixture)

from pinball_decryptor.plugins.stern import mode_from_card as MFC  # noqa: E402
from pinball_decryptor.plugins.stern import mode_project as MP  # noqa: E402
from tests.test_webui_modes import GODZILLA_CARD, _card_project, _project, _wait, preview_on  # noqa: E402,F401
from tests.webui_harness import web_app  # noqa: E402

BOND = "james_bond_le_1_06"
BUMPERS = ("Left pop bumper", "Right pop bumper", "Pop bumper exit")


def _bond(**kw):
    p = MP.profile(BOND)
    spec = MP.blank_spec(p, "BUMPER FRENZY")
    for k, v in kw.items():
        setattr(spec, k, v)
    return p, spec


def test_three_bumpers_and_120_hits_reach_one_trigger_line():
    p, spec = _bond(start_shot=BUMPERS[0], start_or=list(BUMPERS[1:]), start_count=120)
    assert MP.validate(spec) == []
    shots = dict(p.shots)
    line = [ln for ln in MP.runtime_cfg(spec, "bumper_frenzy").splitlines() if ln.startswith("trigger ")]
    assert line == ["trigger        0x%08x 120" % (shots[BUMPERS[0]] | shots[BUMPERS[1]] | shots[BUMPERS[2]])]


def test_a_mode_with_no_other_shots_writes_the_file_it_always_did():
    p, spec = _bond(start_shot=BUMPERS[0], start_count=3)
    line = [ln for ln in MP.runtime_cfg(spec, "b").splitlines() if ln.startswith("trigger ")]
    assert line == ["trigger        0x%08x 3" % dict(p.shots)[BUMPERS[0]]]
    assert MP.start_shots(spec) == [BUMPERS[0]]


def test_the_start_shot_named_again_counts_once():
    _p, spec = _bond(start_shot=BUMPERS[0], start_or=[BUMPERS[0], BUMPERS[1]])
    assert MP.start_shots(spec) == [BUMPERS[0], BUMPERS[1]]


def test_the_checks():
    def words(**kw):
        return " ".join(MP.validate(_bond(**kw)[1]))
    assert words(start_count=999) == ""
    assert "up to 999 shots to start" in words(start_count=1000)
    assert "up to 2 more shots" in words(start_or=list(BUMPERS))
    assert "up to 2 more shots" in words(start_or="Left pop bumper")
    assert "'Nowhere' is not a shot this game has" in words(start_or=["Nowhere"])
    assert words(start_also=[["Left orbit", 500]]) == ""             # "and also" shots go to 999 too
    assert "1 to 999 times" in words(start_also=[["Left orbit", 1000]])


def test_the_other_shots_follow_a_retarget_by_name():
    _p, spec = _bond(start_shot=BUMPERS[0], start_or=[BUMPERS[1], "Nowhere"])
    out, dropped = MP.retarget(spec, MP.profile(BOND))
    assert out.start_or == [BUMPERS[1]] and "Nowhere" in dropped
    out, dropped = MP.retarget(spec, MP.GODZILLA_PRO_1_15)            # Pro 1.15 has no pop bumpers
    assert out.start_or == [] and BUMPERS[1] in dropped


def test_a_card_mode_file_gives_back_all_three_shots():
    p, spec = _bond(start_shot=BUMPERS[0], start_or=list(BUMPERS[1:]), start_count=120)
    got, lost = MFC.recover_spec(MP.runtime_cfg(spec, "bumper_frenzy"), p)
    assert MP.start_shots(got) == list(BUMPERS) and got.start_count == 120
    assert "it starts on" not in lost


def test_the_runtime_counts_the_hits_of_all_three_together(harness, tmp_path):
    cfg = "name BUMPERS\ntrigger 0x7 120\nseconds 5\nshots 0x8\naward 100\n"
    hits = []
    for i in range(119):
        hits += ["shot", ("0x1", "0x2", "0x4")[i % 3]]
    out = _run(harness, tmp_path, cfg, *hits)
    assert "BUMPERS trigger 119 of 120 (player 1)" in out and "BUMPERS START" not in out
    out = _run(harness, tmp_path, cfg, *hits, "shot", "0x4")
    assert "BUMPERS trigger 120 of 120 (player 1)" in out and "BUMPERS START (trigger shot)" in out


def test_the_form_round_trips_the_other_shots(tmp_path, preview_on):
    proj = _card_project(tmp_path / "gz", GODZILLA_CARD)        # Pro 1.15: its three spinners stand in
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        slug = w.call("modes.new")
        st = w.state("modes")
        assert (st["form"]["start_or_0"], st["form"]["start_or_1"]) == ("(no other shot)", "(no other shot)")
        assert st["spin"]["start_count"] == [1, 999]
        path = proj / "modes" / slug / "mode.json"
        w.call("ui.set", "modes", "f:start_shot", "Left spinner")
        w.call("ui.set", "modes", "f:start_or_0", "Top spinner")
        w.call("ui.set", "modes", "f:start_or_1", "Right spinner")
        w.call("ui.set", "modes", "f:start_count", "120")

        def saved():
            d = json.loads(path.read_text("utf-8"))
            return (d.get("start_shot"), d.get("start_or"), d.get("start_count")) ==                 ("Left spinner", ["Top spinner", "Right spinner"], 120)
        assert _wait(w, saved)
        assert w.state("modes")["status"] == "Ready to build."
        w.call("modes.new")
        w.call("modes.select", slug, "form")
        f = w.state("modes")["form"]
        assert (f["start_or_0"], f["start_or_1"], f["start_count"]) == ("Top spinner", "Right spinner", "120")
        w.call("ui.set", "modes", "f:start_or_0", "(no other shot)")
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("start_or") == ["Right spinner"])
