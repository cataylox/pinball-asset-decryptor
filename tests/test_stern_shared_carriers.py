"""Shared sound carriers (hud-layers): a swapped sound picks its carrier and a HOST record at build time.

A mode's own call or music rides a stock request (a carrier) and is swapped in for its own play
(item 163). Several modes' sounds now share one carrier, each as a grown copy of its own host record,
so the carriers stop capping how many sounds the modes carry. Fast: fake records, no card."""
import wave

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import mode_sounds as MS
from pinball_decryptor.plugins.stern import mode_write as MW


def _wav(path, seconds, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\0\0" * channels * int(44100 * seconds))
    return str(path)


def _rec(idx, seconds, chan=1, key=None):
    return {"idx": idx, "length": int(44100 * seconds), "chan": chan,
            "findkey": key or bytes([idx & 0xff]) * 8}


@pytest.fixture
def card(monkeypatch):
    """Carriers 900 / 901 / 902 play records 1 / 2 / 3 (3.0, 2.0, 1.0 s, mono); 903 cannot be located;
    records 10..14 are other mono sounds, 20 a stereo one."""
    params = [_rec(1, 3.0), _rec(2, 2.0), _rec(3, 1.0), _rec(10, 0.5), _rec(11, 2.5), _rec(12, 1.5),
              _rec(13, 4.0), _rec(14, 2.5), _rec(20, 2.0, chan=2)]
    carrier = {900: 1, 901: 2, 902: 3}

    def request_record(elf, head, params, sites, request, mask):
        if request not in carrier:
            raise MW.ModeWriteError("request %d names 16 records, not one sound record" % request)
        return carrier[request]
    monkeypatch.setattr(MW, "request_record", request_record)
    ctx = {"elf": b"", "head": b"", "params": params, "sites": [], "mask": 0, "byidx": {p["idx"]: p for p in params},
           "located": {}, "by_mode": {}}
    return ctx


def _place(ctx, tmp_path, slug, cue, seconds, cands, edits=None, grows=None, mine=None, said=None):
    s = {"slug": slug, "name": slug.upper(), "key": "call:" + cue, "music": False, "swap": True,
         "wav": _wav(tmp_path / ("%s_%s.wav" % (slug, cue)), seconds), "candidates": cands, "request": cands[0]}
    log = (lambda m, *a: said.append(m)) if said is not None else (lambda *a, **k: None)
    return E._mode_shared_sound(s, "%s's %s call" % (slug, cue), ctx,
                                edits if edits is not None else {}, grows if grows is not None else {},
                                mine if mine is not None else set(), str(tmp_path / "work"), log)


def test_two_modes_share_a_carrier_each_with_its_own_host_record(card, tmp_path):
    edits, grows, mine = {}, {}, set()
    a = _place(card, tmp_path, "ghidorah", "won", 2.5, [900, 901, 902], edits, grows, mine)
    b = _place(card, tmp_path, "meltdown", "won", 2.8, [900, 901, 902], edits, grows, mine)
    assert a["request"] == b["request"] == 900                      # one carrier, two modes
    assert a["idx"] == 1 and a["carrier_idx"] == 1                  # the first takes the carrier's own
    assert b["carrier_idx"] == 1 and b["idx"] not in (1, 20)        # the second another mono record
    assert b["idx"] == 11                                           # the longest no longer than 3.0 s (lowest idx)
    # each grown copy is as long as the carrier's record: its descriptor says how long the play is
    assert grows[1][1] == grows[11][1] == int(44100 * 3.0)
    assert set(edits) == {1, 11}


def test_a_mode_never_uses_one_carrier_twice(card, tmp_path):
    edits, grows, mine = {}, {}, set()
    a = _place(card, tmp_path, "meltdown", "lit", 0.8, [900, 901, 902], edits, grows, mine)
    b = _place(card, tmp_path, "meltdown", "jackpot", 0.8, [900, 901, 902], edits, grows, mine)
    c = _place(card, tmp_path, "meltdown", "cool", 0.8, [900, 901, 902], edits, grows, mine)
    # best fit: each takes the shortest carrier that still holds it (1.0 s, then 2.0 s, then 3.0 s)
    assert [a["request"], b["request"], c["request"]] == [902, 901, 900]
    said = []
    d = _place(card, tmp_path, "meltdown", "add", 0.8, [900, 901, 902, 903], edits, grows, mine, said)
    assert d is None and "no carrier takes it" in said[0] and "could not be located" in said[0]


def test_a_call_takes_the_shortest_carrier_that_holds_it(card, tmp_path):
    got = _place(card, tmp_path, "maser", "barrage", 1.5, [900, 901, 902])
    assert got["request"] == 901                                    # 2.0 s: not the 3.0 s one


def test_a_call_longer_than_a_carriers_record_takes_a_longer_one(card, tmp_path):
    said = []
    got = _place(card, tmp_path, "oxygen", "won", 2.5, [902, 901, 900], said=said)
    assert got["request"] == 900 and not any("not put" in m for m in said)   # 1.0 s and 2.0 s are too short
    none = _place(card, tmp_path, "maser", "long", 3.5, [900, 901, 902], said=said)
    assert none is None and "record is 3.00 s" in said[-1]


def test_a_host_never_holds_two_sounds_or_a_replaced_one():
    params = [_rec(1, 3.0), _rec(11, 2.5), _rec(12, 1.5), _rec(13, 4.0), _rec(20, 2.0, chan=2), _rec(30, 2.9)]
    pc = params[0]
    clen = pc["length"]
    assert E._mode_host_record(pc, clen, params, mine={1}, audio_edits={}) == 30
    assert E._mode_host_record(pc, clen, params, mine={1}, audio_edits={30: "x.wav"}) == 11
    assert E._mode_host_record(pc, clen, params, mine={1, 11, 12, 30}, audio_edits={}) is None   # 13 too long, 20 stereo


def test_the_swap_names_the_carriers_key_not_the_hosts(tmp_path):
    """The game looks up the CARRIER's record key when it plays the request: a sound on another host
    swaps the carrier's key for its own appended one."""
    carrier = {"idx": 1, "findkey": b"C" * 8}                                   # not grown: its key as it is
    host = {"idx": 11, "grown": True, "stock_findkey": b"H" * 8, "findkey": b"N" * 8}
    own_host = {"idx": 2, "grown": True, "stock_findkey": b"S" * 8, "findkey": b"O" * 8}
    used = [{"key": "call:won", "swap": True, "idx": 11, "carrier_idx": 1, "request": 900},
            {"key": "call:lost", "swap": True, "idx": 2, "carrier_idx": 2, "request": 901}]
    E._mode_swap_keys(used, [carrier, host, own_host], lambda *a, **k: None)
    assert (used[0]["stock_key"], used[0]["our_key"]) == ((b"C" * 8).hex(), (b"N" * 8).hex())
    assert (used[1]["stock_key"], used[1]["our_key"]) == ((b"S" * 8).hex(), (b"O" * 8).hex())


def test_the_swap_titles_calls_are_shared_and_godzilla_premium_music_keeps_its_beds():
    le = MS.carriers("godzilla_le", "1.16")
    assert MS.swapped(le, "call") and not MS.swapped(le, "music") and le.beds
    pro = MS.carriers("godzilla_pro", "1.16")
    assert MS.swapped(pro, "music") and pro.music[-1] == 123       # its random one last
    assert MS.swap_candidates(le, "call", taken=[le.calls[0]], rank=1)[0] == le.calls[2]
    assert MS.swap_candidates(le, "call", taken=le.calls) == []
