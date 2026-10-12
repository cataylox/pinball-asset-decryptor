"""PAD-533: a mode's own call longer than every carrier still goes on the card, whole.

A swapped call (item 163) rides a stock request whose DESCRIPTOR declares how long the voice plays,
so a call longer than its carrier's record was left off the card: James Bond LE 1.06 has one call
carrier over 10 s, and a tester's mode of five 10-15 s film calls kept one. On a title whose port
names the game's descriptor resolver, such a call now takes the longest carrier and the build
writes the carrier's descriptor - naming the call's record, declaring its length - into sounds.cfg,
which the runtime hands the game while the mode's swap is armed. Fast: fake records, no card."""
import struct
import wave

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import sound_modes as SMo

MASK = 0xE0001FFF                     # the key mask of Godzilla LE 1.16 and James Bond LE 1.06
#: Godzilla LE 1.16's one-sound descriptor of sid 2578, as its resolver hands it out (test_pad494_sound_modes)
D2578 = bytes.fromhex("0501016e4a050001000002000307000b0000009ef94b2c17645a7811010300096e7b6158e294bef6570e10"
                      "e21037cd2029966fd533cc2fac585ffc45be8a1800a4a343aa6cf0744564fddc3042d1364c")


def _key(payload_hex, sid):
    return E._play_key(bytes.fromhex(payload_hex), sid, MASK)


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


def test_without_the_resolver_a_call_longer_than_every_carrier_is_still_left_out(card, tmp_path):
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
    assert [g["long"] for g in got] == [True, True, True]
    assert [g["carrier_len"] for g in got] == [int(44100 * 3.0), int(44100 * 2.0), int(44100 * 1.0)]
    # each record grows to hold its whole call, not its carrier's length
    assert [grows[g["idx"]][1] for g in got] == [int(44100 * 4.5), int(44100 * 4.0), int(44100 * 2.8)]
    assert "a play of its own length" in said[0]
    # another mode shares the carriers: its long call takes the longest again, on a host of its own
    other = _place(card, tmp_path, "diamond_death_threat", "crem18", 5.0, True, edits, grows, mine, said)
    assert other["request"] == 900 and other["long"] and other["idx"] not in [g["idx"] for g in got]
    # a fourth call of the first mode has no carrier left in it, as before
    assert _place(card, tmp_path, "bon_appetit", "output_002a", 3.5, True, edits, grows, mine, said) is None
    assert "taken by the mode's other sounds" in said[-1]


def test_a_call_that_fits_still_takes_the_shortest_carrier_that_holds_it(card, tmp_path):
    said = []
    got = _place(card, tmp_path, "film", "short", 1.5, True, {}, {}, set(), said)
    assert got["request"] == 901 and got["long"] is False


def test_the_carriers_descriptor_names_the_calls_record_and_declares_its_length(tmp_path, monkeypatch):
    """The sounds.cfg line: sound id 2578 is the carrier's only one; its descriptor names our record
    and declares the call's own length, keyed by the record the mode's swap arms."""
    slot, ours = _key("9ef94b2c17645a78", 2578), _key("6f31228f15c03a10", 2547)
    monkeypatch.setattr(MW, "request_sids", lambda elf, head, request: [2578])
    monkeypatch.setattr(E, "_desc_key_mask", lambda params, sites: MASK)
    gr, img = tmp_path / "game", tmp_path / "image.bin"
    gr.write_bytes(b"\0" * 16)
    img.write_bytes(b"\0" * 16)
    secs = 12.5
    wav = _wav(tmp_path / "call.wav", secs)
    params = [{"idx": 46, "length": int(44100 * secs) + 4096, "grown": True, "findkey": ours}]
    used = [{"slug": "bon_appetit", "name": "BON APPETIT", "key": "call:output_000a", "swap": True, "long": True,
             "request": 1057, "idx": 46, "carrier_idx": 46, "carrier_len": int(44100 * 9.8), "wav": wav,
             "stock_key": slot.hex(), "our_key": ours.hex()},
            {"slug": "bon_appetit", "name": "BON APPETIT", "key": "call:fits", "swap": True, "long": False,
             "request": 1071, "idx": 47, "wav": wav}]
    said = []
    lines = E._mode_long_call_lines(str(gr), str(img), params, [], used, lambda m, *a: said.append(m),
                                    found=[(2578, 0x1000, D2578)])
    assert len(lines) == 1                                     # the call that fits needs none
    kind, sid, key, desc = lines[0].split("\t")
    assert (kind, int(sid), key) == ("call", 2578, ours.hex())
    d = bytes.fromhex(desc)
    assert E._play_key(E._op11_payloads(d)[0][1], 2578, MASK) == ours
    declared = struct.unpack_from("<I", d, 3)[0] & 0xFFFFFF
    assert declared == int(44100 * secs) * 4000 // 44100       # 12.5 s, in 1/4000 s
    assert d[27:] == D2578[27:]                                # the rest of the script is the game's
    assert "plays its whole length on request 1057" in said[-1]


def test_a_long_call_whose_carrier_cannot_be_read_says_it_is_cut(tmp_path, monkeypatch):
    monkeypatch.setattr(MW, "request_sids", lambda elf, head, request: [2578, 2579])
    monkeypatch.setattr(E, "_desc_key_mask", lambda params, sites: MASK)
    gr, img = tmp_path / "game", tmp_path / "image.bin"
    gr.write_bytes(b"\0" * 16)
    img.write_bytes(b"\0" * 16)
    used = [{"name": "BON APPETIT", "key": "call:output_000a", "long": True, "request": 1057, "idx": 46,
             "carrier_len": int(44100 * 9.8), "wav": _wav(tmp_path / "c.wav", 1.0), "stock_key": "00" * 8,
             "our_key": "11" * 8}]
    said = []
    assert E._mode_long_call_lines(str(gr), str(img), [], [], used, lambda m, *a: said.append(m),
                                   found=[(2578, 0, D2578)]) == []
    assert "plays only its first 9.80 s" in said[-1] and "2 sound ids" in said[-1]


def test_the_lines_join_the_music_modes_file_or_make_one_of_their_own(tmp_path):
    assert E._with_long_calls("", [], str(tmp_path / "a")) == ""
    alone = E._with_long_calls("", ["call\t1\t%s\t05" % ("00" * 8)], str(tmp_path / "a"))
    text = open(alone, encoding="utf-8").read()
    assert text.splitlines()[-1].startswith("call\t1\t") and "setting" not in text and "only" not in text.split()
    music = tmp_path / "m" / SMo.CFG_NAME
    music.parent.mkdir()
    music.write_text(SMo.cfg_text(0x1000, 2, [(2, 5, b"\x05" * 8)], False), encoding="utf-8")
    both = E._with_long_calls(str(music), ["call\t1\t%s\t05" % ("00" * 8)], str(tmp_path / "b"))
    lines = open(both, encoding="utf-8").read().splitlines()
    assert lines[1].startswith("setting\t") and lines[2].startswith("sound\t2\t5\t") and lines[-1].startswith("call\t")


def test_bond_106_is_a_long_call_title_and_a_port_without_the_resolver_is_not():
    assert MW.long_calls(MP.profile("james_bond_le_1_06")) and MW.long_calls(MP.profile("james_bond_pro_1_06"))
    assert MW.long_calls(MP.profile("godzilla_le_1_16"))
    assert not MW.long_calls(MP.profile("jaws_le_1_02"))


def test_the_runtime_reads_call_lines_and_plays_them_only_while_the_swap_is_armed():
    from pathlib import Path
    src = (Path(MW.__file__).resolve().parents[3] / "tools" / "spike2_emu" / "modes" / "sdk"
           / "pad_mode_runtime.c").read_text(encoding="utf-8")
    assert 'str_eq(f[0], "call")' in src
    assert "static struct sndc *sndc_live(unsigned id)" in src
    assert "key_is(swaps[k].ours, sndc[i].ours)" in src          # keyed on the armed swap's record
    assert "if (!n_sndm && !n_sndc)" in src                      # a card with long calls alone wraps
