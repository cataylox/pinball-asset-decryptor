"""PAD-227: more than one thing to meet before a mode starts.

- ``trigger_also <shots> <count>`` in a mode file (tools/spike2_emu/modes/sdk/mode_file.c): another shot
  to hit as well as the trigger line's, in any order, in one ball.
- ``after ball|game <name>``: the mode's shots only count once another of the card's modes has started
  for this player this ball (or game).
- mode_project: the ``start_also`` / ``after`` / ``after_when`` fields, their checks, and the lines
  ``runtime_cfg`` writes for them.

The runtime half compiles mode_file.c for the HOST against test_spike2_mode_roster.py's stub of the SDK
calls, so it runs wherever an ELF C compiler is (skips otherwise).
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_spike2_mode_roster import _run, harness  # noqa: E402,F401  (harness is a fixture)

from pinball_decryptor.plugins.stern import mode_project as MP  # noqa: E402

ALSO = "name KAIJU\ntrigger 0x1 2\ntrigger_also 0x2 1\nseconds 5\nshots 0x4\naward 100\n"


def test_the_mode_waits_for_its_other_shot(harness, tmp_path):
    out = _run(harness, tmp_path, ALSO, "shot", "0x1", "shot", "0x1", "shot", "0x2")
    assert "unknown key" not in out
    assert "KAIJU: its trigger is met - waiting for its other shots (player 1)" in out
    assert out.index("waiting for its other shots") < out.index("KAIJU START (trigger shot)")


def test_the_other_shot_may_come_first(harness, tmp_path):
    out = _run(harness, tmp_path, ALSO, "shot", "0x2", "shot", "0x1", "shot", "0x1")
    assert "KAIJU: also 00000000_00000002 1 of 1 (player 1)" in out
    assert "KAIJU START (trigger shot)" in out
    assert "waiting" not in out


def test_the_end_of_a_ball_clears_the_other_shots(harness, tmp_path):
    out = _run(harness, tmp_path, ALSO, "shot", "0x2", "ball_end", "shot", "0x1", "shot", "0x1")
    assert "START" not in out
    assert "waiting for its other shots" in out


def test_each_player_keeps_their_own_counts(harness, tmp_path):
    out = _run(harness, tmp_path, ALSO, "shot", "0x2", "player", "2", "shot", "0x1", "shot", "0x1")
    assert "START" not in out


def test_a_second_start_needs_every_shot_again(harness, tmp_path):
    out = _run(harness, tmp_path, ALSO, "shot", "0x2", "shot", "0x1", "shot", "0x1", "tick", "400",
               "shot", "0x1", "shot", "0x1")
    assert out.count("KAIJU START") == 1
    assert "KAIJU END (time ran out)" in out
    assert out.index("KAIJU END") < out.index("waiting for its other shots")


def test_three_other_shots_all_count(harness, tmp_path):
    cfg = ("name KAIJU\ntrigger 0x1 1\ntrigger_also 0x2 1\ntrigger_also 0x10 2\ntrigger_also 0x20 1\n"
           "seconds 5\nshots 0x4\naward 100\n")
    out = _run(harness, tmp_path, cfg, "shot", "0x1", "shot", "0x2", "shot", "0x10", "shot", "0x20")
    assert "START" not in out
    out = _run(harness, tmp_path, cfg, "shot", "0x1", "shot", "0x2", "shot", "0x10", "shot", "0x20", "shot", "0x10")
    assert "KAIJU START (trigger shot)" in out


GATE = "name MECHA\ntrigger 0x1 1\nseconds 5\nshots 0x4\naward 100\nafter %s KAIJU RUSH\n"
FIRST = "name KAIJU RUSH\ntrigger 0x8 1\nseconds 1\nshots 0x4\naward 100\n"


def test_after_game_waits_for_the_other_mode(harness, tmp_path):
    out = _run(harness, tmp_path, GATE % "game", "shot", "0x1", "shot", "0x8", "tick", "200", "ball_end",
               "shot", "0x1", mode1=FIRST)
    assert "unknown key" not in out
    assert "\"MECHA\": starts only after KAIJU RUSH has run this game" in out
    assert "MECHA: shot not counted - KAIJU RUSH has not run this game (player 1)" in out
    assert out.index("KAIJU RUSH START") < out.index("KAIJU RUSH END") < out.index("MECHA START (trigger shot)")


def test_after_ball_is_forgotten_at_the_end_of_the_ball(harness, tmp_path):
    out = _run(harness, tmp_path, GATE % "ball", "shot", "0x8", "tick", "200", "ball_end", "shot", "0x1",
               mode1=FIRST)
    assert "KAIJU RUSH START" in out
    assert "MECHA START" not in out
    assert "MECHA: shot not counted - KAIJU RUSH has not run this ball (player 1)" in out
    out = _run(harness, tmp_path, GATE % "ball", "shot", "0x8", "tick", "200", "shot", "0x1", mode1=FIRST)
    assert "MECHA START (trigger shot)" in out


def test_a_shot_while_the_other_mode_runs_starts_it_once_that_one_ends(harness, tmp_path):
    out = _run(harness, tmp_path, GATE % "ball", "shot", "0x8", "shot", "0x1", "tick", "200", "shot", "0x1",
               mode1=FIRST)
    assert "MECHA not started (trigger shot): KAIJU RUSH is running" in out
    assert out.index("KAIJU RUSH END") < out.index("MECHA START (trigger shot)")


def test_after_a_mode_the_card_does_not_have_never_starts(harness, tmp_path):
    out = _run(harness, tmp_path, GATE % "game", "shot", "0x1", "shot", "0x1")
    assert out.count("MECHA: after KAIJU RUSH - no mode of that name on this card, so it never starts") == 1
    assert "MECHA START" not in out


# ---- mode.json -> the runtime file ---------------------------------------------------------
def _spec(**kw):
    return MP.ModeSpec(title=MP.GODZILLA_PRO_1_15.key, **kw)


def test_a_mode_with_nothing_more_writes_the_file_it_always_did():
    text = MP.runtime_cfg(_spec(), "kaiju")
    assert "trigger_also" not in text and "\nafter " not in text


def test_the_other_shots_and_the_mode_before_reach_the_runtime_file():
    spec = _spec(start_also=[["Left ramp", 2], ["Building", 1]], after="KAIJU RUSH", after_when="ball")
    assert MP.validate(spec) == []
    lines = MP.runtime_cfg(spec, "mecha").splitlines()
    assert "trigger_also   0x00100000 2" in lines
    assert "trigger_also   0x00400000 1" in lines
    assert "after          ball KAIJU RUSH" in lines


def test_an_event_start_keeps_its_other_shots():
    spec = _spec(start_also=[["Left ramp", 1]], starts_on="event ball_start")
    p = MP.GODZILLA_PRO_1_15
    if "ball_start" not in p.events:
        pytest.skip("Pro 1.15 has no ball_start event")
    text = MP.runtime_cfg(spec, "mecha")
    assert "starts_on      event ball_start" in text and "trigger_also   0x00100000 1" in text


@pytest.mark.parametrize("also, words", [
    ([["Nowhere", 1]], "has no shot called 'Nowhere'"),
    ([["Left ramp", 0]], "1 to 20 times"),
    ([["Left ramp", 1]] * 4, "up to 3"),
    ("Left ramp", "up to 3"),
])
def test_bad_other_shots_are_named(also, words):
    problems = " ".join(MP.validate(_spec(start_also=also)))
    assert words in problems


def test_a_mode_cannot_wait_for_itself():
    problems = " ".join(MP.validate(_spec(name="MECHA", after="MECHA")))
    assert "cannot wait for itself" in problems
    problems = " ".join(MP.validate(_spec(after="KAIJU RUSH", after_when="week")))
    assert "this ball or this game" in problems


def test_the_other_shots_follow_a_retarget_by_name():
    spec = _spec(start_also=[["Left ramp", 2], ["Nowhere", 1]])
    out, dropped = MP.retarget(spec, MP.GODZILLA_PRO_1_15)
    assert out.start_also == [["Left ramp", 2]]
    assert "Nowhere" in dropped


def test_missing_after_names_a_mode_the_project_lacks():
    modes = [("1_kaiju", _spec(name="KAIJU RUSH")), ("2_mecha", _spec(name="MECHA", after="GHIDORAH"))]
    assert MP.after_problems(modes) == {"2_mecha": ["MECHA starts only after GHIDORAH, and no mode is called that."]}
    modes[1] = ("2_mecha", _spec(name="MECHA", after="KAIJU RUSH"))
    assert MP.after_problems(modes) == {}
