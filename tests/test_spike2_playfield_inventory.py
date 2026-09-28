"""Both playfield views say how many switches, lamps and coils the title has.

PAD-238 (item 68 of the PAD-81 list): "displaying the total count of switches
and lights on all virtual playfield windows would be a great feature (even on
models with playfield artwork)". The schematic said switches only, worded as a
complaint about the artwork; the Field view said nothing until the game wrote a
lamp frame, and never the switch count.

What is pinned: ONE function spells the line for both views, from the tables,
and a missing table is said rather than printed as 0.
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


def test_the_field_line_gives_totals_and_what_the_artwork_places(pf,
                                                                 monkeypatch):
    rows = ([_led("playfield", 1, i) for i in range(10)]
            + [_led("Test/scaled_topper", 7, i) for i in range(30)])
    monkeypatch.setattr(pf, "DEV_ROWS", rows)
    monkeypatch.setattr(pf.coilmap, "load", lambda path: [{}] * 5)
    line = pf.inventory(switch_list=[_sw(i) for i in range(20)],
                        positioned=[_sw(i) for i in range(8)],
                        leds=rows[:10], fixtures=[{}] * 6, coils=[{}] * 5)
    assert line == ("demo_le: 20 switches (8 on the artwork) · "
                    "40 lamps (10 on the artwork, 6 inserts, 30 on toppers)"
                    " · 5 coils")


def test_a_missing_table_is_said_never_printed_as_zero(pf):
    line = pf.inventory(switch_list=[])
    assert "switches not known yet" in line
    assert "no lamp table" in line and "no coil table" in line
    assert " 0 " not in line


def test_the_schematic_bar_opens_with_the_same_line(pf):
    switches = [_sw(i) for i in range(12)]

    class Ctl:
        key_panel = None

    view = pf.Schematic(Ctl(), switches)
    same = pf.inventory(switch_list=switches)
    assert view.spec()["bar"].startswith(same)
    assert "no playfield artwork" in view.spec()["bar"]
