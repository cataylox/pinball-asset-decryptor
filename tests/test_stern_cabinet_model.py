"""Which model a Spike 2 machine is, read off the game binary (PAD-519).

The choice logic runs on a stubbed classifier; the real reading - finding the twelve codes and
running the game's own classifier on them - runs on David's cards when they are there
(PAD_SPIKE2_IMG_DIR, else D:\\Pinball\\images\\Stern\\spike2) and skips elsewhere.
"""
import faulthandler
import os

import pytest

from pinball_decryptor.plugins.stern import cabinet_model as cm

IMG_DIR = os.environ.get("PAD_SPIKE2_IMG_DIR", r"D:\Pinball\images\Stern\spike2")

_TABLE = {
    "codes": [(2, "05"), (2, "08"), (2, None), (3, "I0"), (3, "06"), (3, "0A"),
              (4, "I2"), (4, "I9"), (4, "09"), (6, "I3"), (6, "I4"), (6, "0B")],
    "globals": list(range(12)), "classifier": 0, "builtin": "I2"}


def _stub(monkeypatch, answers, table=_TABLE):
    monkeypatch.setattr(cm, "find_table", lambda blob: table)
    monkeypatch.setattr(cm, "classify", lambda blob, t, codes: {
        c: answers[c] for c in codes if c in answers})


def test_a_premium_le_build_offers_each_class_by_its_first_code(monkeypatch):
    _stub(monkeypatch, {
        "05": (2, True, False), "08": (2, True, False),
        "I0": (3, False, False), "06": (3, True, False), "0A": (3, True, False),
        "I2": (4, False, False), "I9": (4, True, False), "09": (4, True, False),
        "I3": (6, False, False), "I4": (6, True, False), "0B": (6, True, False),
        "999": (5, False, False)})
    ed = cm.editions_bytes(b"x")
    assert ed == {"built": "Premium",
                  "choices": [("Premium", "I2"), ("LE", "I0"), ("SLE", "I3")]}


def test_a_pro_build_has_nothing_to_pick(monkeypatch):
    """A Pro build answers Pro for every code and flags the Premium/LE ones as the other
    family (its "PRE/LE CODE PRESENT ON PRO GAME"): one class, so no choice."""
    table = dict(_TABLE, builtin="J5", codes=[
        (2, "J5"), (2, "J8"), (2, "08"), (3, "J6"), (3, "06"), (3, "0A"),
        (4, "J7"), (4, "J9"), (4, "09"), (6, None), (6, None), (6, "0B")])
    _stub(monkeypatch, {"J5": (2, False, False), "J8": (2, True, False),
                        "08": (2, True, False), "J6": (2, False, True),
                        "J7": (2, False, True), "999": (2, False, False)}, table)
    assert cm.editions_bytes(b"x") == {"built": "Pro", "choices": []}


def test_a_build_with_no_wildcard_names_the_emulators_own_record(monkeypatch):
    """John Wick 1.02 has no "999" in its reader: the emulator's record reads as the
    unknown-model word, Premium/LE, and every class stays on the list."""
    table = dict(_TABLE, builtin=None)
    _stub(monkeypatch, {"I0": (3, False, False), "I2": (4, False, False),
                        "999": (5, False, False)}, table)
    ed = cm.editions_bytes(b"x")
    assert ed["built"] == "Premium/LE"
    assert ed["choices"] == [("Premium", "I2"), ("LE", "I0")]


def test_not_a_game_binary_is_empty():
    assert cm.editions_bytes(b"not an elf") == {"built": "", "choices": []}
    assert cm.find_table(b"") is None


def test_an_unreadable_card_is_empty_never_an_error(tmp_path):
    card = tmp_path / "x.raw"
    card.write_bytes(b"\0" * 4096)
    assert cm.editions_card(str(card)) == (None, {"built": "", "choices": []})


@pytest.fixture
def _no_faulthandler():
    """unicorn services guest memory through the host's fault machinery, and on Windows
    faulthandler prints each handled access violation as a "fatal exception" (same as
    test_spike2_masterdir.py and test_stern_audio_tail.py)."""
    was = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        yield
    finally:
        if was:
            faulthandler.enable()


def _card(name):
    path = os.path.join(IMG_DIR, name)
    if not os.path.isfile(path):
        pytest.skip("card not here: %s" % path)
    return path


@pytest.mark.parametrize("card, built, choices", [
    ("batman-1_14_0.Release.8G.sdcard.raw", "Premium",
     [("Premium", "I2"), ("LE", "I0"), ("SLE", "I3")]),
    ("munsters_le-1_28_0.Release.8G.sdcard.raw", "Premium",
     [("Premium", "L3"), ("LE", "L2")]),
    ("star_wars_pro-1_31_0.Release.8G.sdcard.raw", "Pro", []),
])
def test_real_builds(card, built, choices, _no_faulthandler):
    _title, ed = cm.editions_card(_card(card))
    assert ed == {"built": built, "choices": choices}
