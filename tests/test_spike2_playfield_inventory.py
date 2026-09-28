"""Both playfield views say how many switches, lamps and coils the title has.

PAD-238 (item 68 of the PAD-81 list): "displaying the total count of switches
and lights on all virtual playfield windows would be a great feature (even on
models with playfield artwork)". The schematic said switches only, worded as a
complaint about the artwork; the Field view said nothing until the game wrote a
lamp frame, and never the switch count.

David, on the first cut (a bar over the playfield): "we shouldn't be making the
virtual playfield area more busy for this feature" - the counts and the live
rates the status strip used to carry now sit in a folded accordion at the head
of the side panel.

What is pinned: ONE function gives the rows for both views, from the tables;
a missing table is said rather than printed as 0; neither view puts the counts
on the playfield; and the status line carries no rates.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)


def _led(image, group, index):
    return {"kind": "led", "image": image, "group": group, "index": index,
            "name": "L%d_%d" % (group, index), "x": 0, "y": 0}


def _sw(i):
    return {"id": i, "num": i, "node": 1, "bit": i % 8, "name": "SW%d" % i}


@pytest.fixture
def pf(monkeypatch):
    pf = pytest.importorskip("playfield")
    monkeypatch.setattr(pf, "GAME", "demo_le")
    monkeypatch.setattr(pf, "load_switch_list", lambda *a, **k: [])
    monkeypatch.setattr(pf, "DEV_ROWS", [])
    monkeypatch.setattr(pf.coilmap, "load", lambda path: [])
    return pf


def test_the_field_rows_give_totals_and_what_the_artwork_places(pf,
                                                                monkeypatch):
    rows = ([_led("playfield", 1, i) for i in range(10)]
            + [_led("Test/scaled_topper", 7, i) for i in range(30)])
    monkeypatch.setattr(pf, "DEV_ROWS", rows)
    monkeypatch.setattr(pf.coilmap, "load", lambda path: [{}] * 5)
    got = pf.inventory(switch_list=[_sw(i) for i in range(20)],
                       positioned=[_sw(i) for i in range(8)],
                       leds=rows[:10], fixtures=[{}] * 6, coils=[{}] * 5)
    assert got == [
        ["Switches", "20", "8 on the artwork"],
        ["Lamps", "40", "10 on the artwork, 6 inserts, 30 on toppers"],
        ["Coils", "5", ""],
    ]


def test_a_missing_table_is_said_never_printed_as_zero(pf):
    got = pf.inventory(switch_list=[])
    assert got == [["Switches", "not known yet", ""],
                   ["Lamps", "no table", ""],
                   ["Coils", "no table", ""]]


def test_the_schematic_gives_the_same_rows_and_keeps_them_off_its_bar(pf):
    switches = [_sw(i) for i in range(12)]

    class Ctl:
        key_panel = None

    view = pf.Schematic(Ctl(), switches)
    spec = view.spec()
    assert spec["info"] == pf.inventory(switch_list=switches)
    assert spec["bar"].startswith("no playfield artwork")
    assert "12" not in spec["bar"] and "switches" not in spec["bar"]


def test_the_status_line_carries_no_rates_only_the_live_rows_do(pf,
                                                                monkeypatch):
    """The schematic's tick with no emulator: before, the status strip said
    "no emulator ..."; now that is a Live row and the strip is left for what
    the last press said."""
    switches = [_sw(i) for i in range(4)]

    class Ctl:
        key_panel = None

        def poll_switches(self, view, frame):
            pass

        def state_status(self):
            return None

    monkeypatch.setattr(pf, "LED_PATH", os.path.join(ROOT, "no-such-padled"))
    view = pf.Schematic(Ctl(), switches)
    frame = view.tick(0)
    assert view.status == "" and "status" not in frame
    assert frame["live"][0][:2] == ["Emulator", "not running"]
    assert view.live == frame["live"]
