"""core/rigslot.py: which emulator rig the app drives, and the board it shows.

The rig side is tests/test_spike2_rig_slots.py; this is the app's half - the
environment its rig commands carry, the board as the Emulate tab reads it,
and the rig an app launched for a triage ticket claims for itself.
"""
import json
import os
import time

import pytest

from pinball_decryptor.core import rigslot


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_BOARD_WIN", str(tmp_path))
    for k in ("PAD_SLOT", "PAD_LABEL", "PAD_TICKET"):
        monkeypatch.delenv(k, raising=False)
    rigslot._claimed.clear()
    yield tmp_path
    rigslot._claimed.clear()


def _put(d, name, rec, age=0):
    p = os.path.join(str(d), name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    if age:
        t = time.time() - age
        os.utime(p, (t, t))


def test_an_ordinary_install_changes_nothing(board):
    assert rigslot.slot() == 0
    assert rigslot.rig_env() == []
    assert rigslot.title_tag() == ""
    rows = rigslot.board()
    assert [r["slot"] for r in rows] == [0, 1, 2, 3, 4]
    assert not any(r["holder"] or r["run"] for r in rows)
    assert rows[0]["mine"] and not rows[1]["mine"]


def test_a_rig_and_a_label_ride_on_every_command(board, monkeypatch):
    monkeypatch.setenv("PAD_SLOT", "2")
    monkeypatch.setenv("PAD_TICKET", "PAD-231")
    assert rigslot.rig_env() == ["PAD_SLOT=2", "PAD_LABEL=PAD-231"]
    assert rigslot.title_tag() == "rig 2: PAD-231"
    monkeypatch.setenv("PAD_LABEL", "item/48")      # an explicit label wins
    assert rigslot.rig_env()[1] == "PAD_LABEL=item/48"


def test_the_board_reads_holders_runs_and_stale_runs(board):
    now = int(time.time())
    _put(board, "slot-1.lock", {"slot": 1, "who": "item/48", "what": "godzilla run",
                                "distro": "Ubuntu", "taken": now - 600})
    _put(board, "slot-1.run", {"slot": 1, "game": "godzilla_pro", "label": "item/48",
                               "started": now - 300})
    _put(board, "slot-3.run", {"slot": 3, "game": "turtles_pro", "started": now - 900},
         age=400)
    _put(board, "slot-2.lock", "not a record")
    rows = {r["slot"]: r for r in rigslot.board(now=now)}
    assert rows[1]["holder"] == "item/48" and rows[1]["doing"] == "godzilla run"
    assert 595 <= rows[1]["held_s"] <= 605
    assert rows[1]["run"]["game"] == "godzilla_pro" and not rows[1]["run"]["stale"]
    assert rows[3]["run"]["stale"]
    assert rows[2]["holder"] == "" and rows[2]["run"] is None    # junk ignored
    assert rows[1]["colour"] == rigslot.COLOURS[1]


def test_a_ticket_app_claims_a_free_rig_and_gives_it_back(board, monkeypatch):
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    _put(board, "slot-1.lock", {"slot": 1, "who": "item/48"})
    assert rigslot.claim_for_ticket() == 2
    assert os.environ["PAD_SLOT"] == "2"
    rec = json.loads(open(os.path.join(str(board), "slot-2.lock")).read())
    assert rec["who"] == "PAD-7" and rec["what"] == "app"
    rigslot.release_claimed()
    assert not os.path.exists(os.path.join(str(board), "slot-2.lock"))
    assert os.path.exists(os.path.join(str(board), "slot-1.lock"))   # not ours
    monkeypatch.delenv("PAD_SLOT")


def test_release_never_removes_a_lock_someone_else_took_over(board, monkeypatch):
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    assert rigslot.claim_for_ticket() == 1
    _put(board, "slot-1.lock", {"slot": 1, "who": "item/48"})     # replaced
    rigslot.release_claimed()
    assert os.path.exists(os.path.join(str(board), "slot-1.lock"))
    monkeypatch.delenv("PAD_SLOT")


def test_no_ticket_or_a_chosen_rig_claims_nothing(board, monkeypatch):
    assert rigslot.claim_for_ticket() == 0
    assert not os.listdir(str(board))
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    monkeypatch.setenv("PAD_SLOT", "3")
    assert rigslot.claim_for_ticket() == 3
    assert not os.listdir(str(board))


def test_every_rig_held_leaves_the_app_on_the_main_rig(board, monkeypatch):
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    for n in range(1, rigslot.SLOTS_MAX + 1):
        _put(board, "slot-%d.lock" % n, {"slot": n, "who": "x"})
    assert rigslot.claim_for_ticket() == 0
    assert "PAD_SLOT" not in os.environ


def test_the_colours_match_the_playfield_band():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "tools", "spike2_emu", "pfpage", "pf.css"),
              encoding="utf-8") as fh:
        css = fh.read()
    for n, c in enumerate(rigslot.COLOURS):
        assert "--rig-%d: %s" % (n, c) in css
