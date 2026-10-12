"""PAD-533: a mode's own call longer than every carrier still goes on the card on James Bond LE 1.06.

A swapped call (item 163) rides a stock request, and the build left off any call longer than its
carrier's record, on the belief that the carrier's descriptor cuts the voice at its own length. James
Bond LE 1.06 has one call carrier over 10 s, so a tester's mode of five 10-15 s film calls kept one and
the others played silent. The emulator showed that game plays a swapped record to its end (an 18 s call
on a 9.89 s carrier, a 20 s one on 14.77 s, both whole), so there such a call now takes the longest
carrier. Fast: fake records, no card."""
import wave

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_write as MW


def _wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\0\0" * int(44100 * seconds))
    return str(path)


def _rec(idx, seconds, chan=1):
    return {"idx": idx, "length": int(44100 * seconds), "chan": chan, "findkey": bytes([idx & 0xff]) * 8}


@pytest.fixture
def card(monkeypatch):
    """Carriers 900 / 901 / 902 play records 1 / 2 / 3 (3.0, 2.0, 1.0 s, mono); 10..12 other mono sounds."""
    params = [_rec(1, 3.0), _rec(2, 2.0), _rec(3, 1.0), _rec(10, 0.5), _rec(11, 2.5), _rec(12, 1.5)]
    carrier = {900: 1, 901: 2, 902: 3}
    monkeypatch.setattr(MW, "request_record", lambda elf, head, params, sites, request, mask: carrier[request])
    return {"elf": b"", "head": b"", "params": params, "sites": [], "mask": 0, "byidx": {p["idx"]: p for p in params},
            "located": {}, "by_mode": {}}


def _place(ctx, tmp_path, slug, cue, seconds, long_ok, edits, grows, mine, said):
    s = {"slug": slug, "name": slug.upper(), "key": "call:" + cue, "music": False, "swap": True,
         "wav": _wav(tmp_path / ("%s_%s.wav" % (slug, cue)), seconds), "candidates": [900, 901, 902],
         "request": 900}
    if long_ok:
        s["long_ok"] = True
    return E._mode_shared_sound(s, "%s's %s call" % (slug, cue), ctx, edits, grows, mine,
                                str(tmp_path / "work"), lambda m, *a: said.append(m))


def test_elsewhere_a_call_longer_than_every_carrier_is_still_left_out(card, tmp_path):
    said = []
    got = _place(card, tmp_path, "bon_appetit", "output_000a", 4.0, False, {}, {}, set(), said)
    assert got is None and "no carrier takes it" in said[-1]


def test_long_calls_take_the_longest_free_carrier_each_and_grow_to_their_own_length(card, tmp_path):
    edits, grows, mine, said = {}, {}, set(), []
    got = [_place(card, tmp_path, "bon_appetit", cue, secs, True, edits, grows, mine, said)
           for cue, secs in (("output_000a", 4.5), ("output_004a", 4.0), ("output_001a", 2.8))]
    assert all(g is not None for g in got) and not any("not put" in m for m in said)
    # longest first: 4.5 s takes the 3.0 s carrier, 4.0 s the 2.0 s one, and 2.8 s (which the 3.0 s
    # one would hold, but the mode has it already) the 1.0 s one
    assert [g["request"] for g in got] == [900, 901, 902]
    # each record grows to hold its whole call, not its carrier's length
    assert [grows[g["idx"]][1] for g in got] == [int(44100 * 4.5), int(44100 * 4.0), int(44100 * 2.8)]
    assert "this game plays it whole" in said[0]
    # another mode shares the carriers: its long call takes the longest again, on a host of its own
    other = _place(card, tmp_path, "diamond_death_threat", "crem18", 5.0, True, edits, grows, mine, said)
    assert other["request"] == 900 and other["idx"] not in [g["idx"] for g in got]
    # a fourth call of the first mode has no carrier left in it, as before
    assert _place(card, tmp_path, "bon_appetit", "output_002a", 3.5, True, edits, grows, mine, said) is None
    assert "taken by the mode's other sounds" in said[-1]


def test_a_call_that_fits_still_takes_the_shortest_carrier_that_holds_it(card, tmp_path):
    said = []
    got = _place(card, tmp_path, "film", "short", 1.5, True, {}, {}, set(), said)
    assert got["request"] == 901 and "plays it whole" not in said[-1]


def test_only_the_proven_title_takes_long_calls():
    assert MW.long_calls(MP.profile("james_bond_le_1_06"))
    assert not MW.long_calls(MP.profile("godzilla_le_1_16"))
    assert not MW.long_calls(None)


def test_bond_le_calls_are_marked_long_ok_and_the_music_is_not():
    from pinball_decryptor.plugins.stern import mode_sounds as MS
    c = MS.carriers("james_bond_le", "1.06")
    entries = [{"slug": "a", "name": "A", "key": "call:x", "swap": True, "music": False, "wav": "x.wav"},
               {"slug": "a", "name": "A", "key": "music", "swap": True, "music": True, "wav": "m.wav"}]
    kept, dropped = MW._share_swapped(entries, c, [], long_ok=True)
    assert not dropped and kept[0].get("long_ok") and not kept[1].get("long_ok")


def test_try_it_counts_only_the_mode_files_as_mode_files(tmp_path, monkeypatch):
    """A set of code modes alone carries no mode file; stock.cfg, clips.cfg and sounds.cfg beside them are
    not mode files (any of them used to refuse the set: "the set's mode files [...] do not match")."""
    from pinball_decryptor.plugins.stern import code_modes as CM
    monkeypatch.setattr(CM, "profile_for", lambda project, code: MP.profile("james_bond_le_1_06"))
    stage = tmp_path / ("set" + E.OVERRIDE_MODES_SUFFIX)
    stage.mkdir()
    (stage / "game.port").write_text("game james_bond_le\nversion 1.06\n", encoding="utf-8")
    listed = {"modes": {"dir": str(stage), "files": ["pad_mode.so", "long_calls.assets", "sounds.cfg",
                                                     "stock.cfg", "clips.cfg", "game.port"]}, "files": []}
    got = MW._tryit_set_from_manifest(str(tmp_path), [], [("long_calls", None)], str(tmp_path / "set"), listed,
                                      (0, 0, 0), E)
    assert got.mode_files == [] and got.codes == ["long_calls"]
