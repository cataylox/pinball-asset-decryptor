"""What a Spike 2 build does about 50 Hz mains, read off the binary (PAD-173).

The shapes here are the ones decoded from the real builds - see
``plugins/stern/mains_check.py`` for where each came from - assembled by hand
so the test needs no card and no 6 MB game binary:

  * the 57..63 Hz test both shapes end in,
  * the wait counter beside it, and
  * the arm that runs while the game has no reading yet, which is the whole
    difference: a plain return (asks again, the refusal comes) or
    ``mov r0,#2`` into flag_set (the question is answered, no refusal).
"""
import struct

import pytest

from pinball_decryptor.plugins.stern import mains_check as mc

BASE = 0x8000           # where the fake code is mapped
CODE_OFF = 0x1000       # ...and where it sits in the file

TEST_PAIR = struct.pack("<II", 0xe2433039, 0xe3530006)   # sub #57 / cmp #6
CMP_936 = struct.pack("<I", 0xe3530fea)                  # cmp r3, #0x3a8
MOV_R0_2 = struct.pack("<I", 0xe3a00002)                 # the give-up arm
RETURN = struct.pack("<I", 0xe28dd018)                   # add sp, sp, #0x18
NOP = struct.pack("<I", 0xe1a00000)                      # mov r0, r0


def _bls(at, target):
    """``bls target`` as it is encoded at address *at* (PC reads +8)."""
    imm = (target - (at + 8)) // 4
    return struct.pack("<I", 0x9a000000 | (imm & 0xffffff))


def _elf(code, base=BASE):
    """A little-endian ARM ELF with one PT_LOAD holding *code*."""
    ph = struct.pack("<8I", 1, CODE_OFF, base, base, len(code), len(code),
                     5, 0x1000)
    head = (b"\x7fELF\x01\x01\x01" + b"\0" * 9
            + struct.pack("<HHIIIIIHHHHHH",
                          2, 40, 1, base, 0x34, 0, 0x5000000,
                          52, 32, 1, 40, 0, 0))
    blob = head + ph
    blob += b"\0" * (CODE_OFF - len(blob))
    return blob + code


def _build(arm_first_word, gap_words=4):
    """A check whose "no reading yet" arm starts with *arm_first_word*.

    The arm sits AFTER the counter compare, which is how godzilla_pro 1.15.0
    is laid out; the distance is padded so the compare stays inside the
    module's search window either way.
    """
    # [0] the arm (branched to), then padding, the counter, its bls, the test
    arm = arm_first_word + NOP * 3
    pad = NOP * gap_words
    counter_at = BASE + len(arm) + len(pad)
    bls = _bls(counter_at + 4, BASE)
    return _elf(arm + pad + CMP_936 + bls + NOP + TEST_PAIR)


def test_a_build_that_keeps_asking_shows_the_refusal():
    assert mc.verdict_bytes(_build(RETURN)) == mc.SHOWS
    # ...and that is the case the tab says nothing about: the lock happens.
    assert mc.sentence("stranger_things_le", mc.SHOWS) == ""


def test_a_build_that_answers_itself_never_refuses():
    assert mc.verdict_bytes(_build(MOV_R0_2)) == mc.SKIPS
    said = mc.sentence("godzilla_pro", mc.SKIPS)
    assert "godzilla_pro" in said
    assert "once at power-up" in said
    assert "starts normally" in said


def test_a_build_with_no_check_at_all():
    assert mc.verdict_bytes(_elf(NOP * 64)) == mc.NONE
    said = mc.sentence("jurassic_park_the_pin", mc.NONE)
    assert "no mains check" in said
    assert "either mains" in said


def test_rubbish_is_unknown_not_a_crash():
    for blob in (b"", b"not an elf at all", b"\x7fELF" + b"\0" * 40):
        assert mc.verdict_bytes(blob) == mc.UNKNOWN
    # A check whose counter arm is not there at all: the shape is not one of
    # the two, and guessing would put a wrong sentence on the tab.
    assert mc.verdict_bytes(_elf(NOP * 8 + TEST_PAIR)) == mc.UNKNOWN
    assert mc.sentence("x", mc.UNKNOWN) == ""


def test_an_unreadable_card_is_not_an_exception(tmp_path):
    """The verdict decides a sentence; it must never be why a card cannot
    be run."""
    card = tmp_path / "not-a-card.raw"
    card.write_bytes(b"\0" * 4096)
    assert mc.verdict_card(str(card)) == (None, mc.UNKNOWN)
    assert mc.verdict_card(str(tmp_path / "gone.raw")) == (None, mc.UNKNOWN)


def test_the_stamp_is_what_a_cache_keys_on(tmp_path):
    card = tmp_path / "c.raw"
    card.write_bytes(b"\0" * 16)
    first = mc.cache_stamp(str(card))
    assert first and first[0] == 16
    assert mc.cache_stamp(str(tmp_path / "gone.raw")) is None


@pytest.mark.parametrize("gap", [0, 8, 40])
def test_the_arm_is_found_wherever_the_compiler_put_it(gap):
    assert mc.verdict_bytes(_build(MOV_R0_2, gap_words=gap)) == mc.SKIPS
    assert mc.verdict_bytes(_build(RETURN, gap_words=gap)) == mc.SHOWS
