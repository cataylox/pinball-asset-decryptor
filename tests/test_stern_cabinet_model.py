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


def test_a_class_with_a_title_of_its_own_offers_its_alternate_code(monkeypatch):
    """Elvira 1.13: the LE's alternate "X2" is where "ELVIRA'S BLOOD RED KISS LE" comes in, so
    it is an edition of its own; the other alternates stay off the list."""
    table = dict(_TABLE, titles={cm.LE: "ELVIRA'S BLOOD RED KISS LE"},
                 title="ELVIRA'S HOUSE OF HORRORS PRE", builtin="J2", codes=[
                     (2, None), (2, "05"), (2, "08"), (3, "J1"), (3, "X2"), (3, "0A"),
                     (4, "J2"), (4, "04"), (4, "09"), (6, "J3"), (6, "J4"), (6, "0B")])
    _stub(monkeypatch, {
        "05": (2, True, False), "08": (2, True, False),
        "J1": (3, False, False), "X2": (3, True, False), "0A": (3, True, False),
        "J2": (4, False, False), "04": (4, True, False), "09": (4, True, False),
        "J3": (6, False, False), "J4": (6, True, False), "0B": (6, True, False),
        "999": (5, False, False)}, table)
    assert cm.editions_bytes(b"x")["choices"] == [
        ("Premium", "J2"), ("LE", "J1"), ("Elvira's Blood Red Kiss LE", "X2"), ("SLE", "J3")]


def test_an_editions_name_is_the_games_title_in_ordinary_case():
    assert cm._edition_name("JURASSIC PARK: 30TH ANNIVERSARY LE") == \
        "Jurassic Park: 30th Anniversary LE"
    assert cm._edition_name("GODZILLA: 70TH ANNIVERSARY") == "Godzilla: 70th Anniversary"


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
    ("elvira3-1_13_0.Release.16G.sdcard.raw", "Premium",
     [("Premium", "J2"), ("LE", "J1"), ("Elvira's Blood Red Kiss LE", "X2"), ("SLE", "J3")]),
    ("godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "Premium",
     [("Premium", "T7"), ("Godzilla: 70th Anniversary", "T8"), ("LE", "T6")]),
])
def test_real_builds(card, built, choices, _no_faulthandler):
    _title, ed = cm.editions_card(_card(card))
    assert ed == {"built": built, "choices": choices}
