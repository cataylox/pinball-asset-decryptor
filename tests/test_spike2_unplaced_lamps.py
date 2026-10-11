"""PAD-517: lamps the device table names on a picture but places nowhere.

"Speakers Expression Lights rings are missing on games with playfield artwork"
(peanuts, 2026-10-11: Deadpool, D&D, Godzilla, Bond, Jaws, John Wick). Those
titles point SPEAKER 1-R .. 23-B at `System/TestMode/spike_2_speaker_panel_
cropped` and leave x, y, w, h zero - the places live in the part text, as
`rect:...` - and devicexy refused every one for its size, so cablights never
saw a speaker row. The artwork-less titles (Venom, Rush) point the same rows at
the shared empty string and always had them.

Measured over the latest card of every title (53): 17 artwork titles gain all
69 speaker channels, a few gain backpanel GI or topper lamps, and not one gains
or loses a switch, a coil or its layout picture.
"""
import os
import struct
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

import cablights                                   # noqa: E402
import devicexy                                    # noqa: E402

STRIDE = devicexy.STRIDE
BIAS = devicexy.VA_BIAS
PF = b"playfield"
PANEL = b"System/TestMode/spike_2_speaker_panel_cropped"
TABLE = 0x2000


def _blob(recs):
    """A binary holding `recs` as one run at a true stride.

    Each rec is (image, cls, (x, y, w, h), name, part): image None points at
    the shared empty string (an artwork-less record), part None leaves the
    field null. Names go in the PREVIOUS slot (devicexy.NAME_OFF)."""
    buf = bytearray(0x4000)
    at = [0x0010]

    def string(raw):
        off = at[0]
        buf[off:off + len(raw) + 1] = raw + b"\x00"
        at[0] += len(raw) + 1
        return off + BIAS

    empty = string(b"")
    images = {}
    for i, (img, cls, rect, name, part) in enumerate(recs):
        rec = TABLE + i * STRIDE
        if img is None:
            img_va = empty
        else:
            img_va = images.get(img) or images.setdefault(img, string(img))
        struct.pack_into("<I", buf, rec + 0x00, img_va)
        struct.pack_into("<hh", buf, rec + 0x04, 10, i)          # group, index
        struct.pack_into("<hh", buf, rec + 0x08, cls, 2)
        struct.pack_into("<hhhh", buf, rec + 0x10, *rect)
        if part is not None:
            struct.pack_into("<I", buf, rec + 0x1C, string(part))
        struct.pack_into("<I", buf, rec + devicexy.NAME_OFF,
                         string(name.encode()))
    # the empty string is found by how often it is pointed at
    for i in range(devicexy.BLANK_MIN_REFS):
        struct.pack_into("<I", buf, 0x3800 + i * 4, empty)
    return bytes(buf)


def _records(tmp_path, recs):
    p = tmp_path / "game.bin"
    p.write_bytes(_blob(recs))
    d, cstr = devicexy.load(str(p))
    return sorted(devicexy.records(d, cstr), key=lambda r: r["va"])


def _placed(n, cls=1, name="SW"):
    return [(PF, cls, (40 + k, 300 + k, 20, 20), "%s %d" % (name, k), None)
            for k in range(n)]


def _speakers(n, part=b"rect:320,126,30,30,56,126,30,30#part:511-1135-00"):
    out = []
    for k in range(n):
        out.append((PANEL, 3, (0, 0, 0, 0),
                    "SPEAKER %d-%s" % (k // 3 + 1, "GRB"[k % 3]), part))
    return out


def test_speaker_lamps_on_the_panel_picture_are_read(tmp_path):
    """The report: Godzilla's 69 SPEAKER rows, which the size test refused."""
    recs = _records(tmp_path, _placed(5) + _speakers(6))
    spk = [r for r in recs if r["name"].startswith("SPEAKER")]
    assert [r["name"] for r in spk] == ["SPEAKER 1-G", "SPEAKER 1-R",
                                        "SPEAKER 1-B", "SPEAKER 2-G",
                                        "SPEAKER 2-R", "SPEAKER 2-B"]
    assert all(r["kind"] == "led" and r["image"] == PANEL.decode() for r in spk)
    assert all((r["x"], r["y"], r["w"], r["h"]) == (0, 0, 0, 0) for r in spk)
    # and the placed playfield is still the layout
    assert devicexy.layout_image(recs) == "playfield"


def test_a_part_text_listing_many_rects_is_still_text(tmp_path):
    """Bond's SPEAKER 23-B points at 216 characters of rects."""
    long_part = b"rect:" + b",".join(b"61,846,20,20" for _ in range(16)) + \
        b"#part:112-5034-WW"
    assert len(long_part) > devicexy.TEXT_MAX
    recs = _records(tmp_path, _placed(5) + _speakers(5) +
                    _speakers(1, part=long_part))
    assert sum(1 for r in recs if r["name"].startswith("SPEAKER")) == 6


def test_an_unplaced_switch_or_coil_is_refused(tmp_path):
    """The same shape carries Bond's cabinet switches; a new switch row would
    move every swelf id after it, so only lamps are taken."""
    for cls in (1, 2):
        rows = _placed(5) + [(PANEL, cls, (0, 0, 0, 0), "COIN DOOR %d" % k,
                              None) for k in range(5)]
        recs = _records(tmp_path, rows)
        assert [r["name"] for r in recs] == ["SW %d" % k for k in range(5)]


def test_an_unplaced_lamp_on_the_layout_picture_is_dropped(tmp_path):
    """D&D's LEFT/RIGHT GI sit on its own layout drawing with no rect: kept,
    they would be markers at 0, 0 on the artwork."""
    rows = _placed(5) + [(PF, 3, (0, 0, 0, 0), "LEFT GI-%d" % k, None)
                         for k in range(4)] + _speakers(3)
    recs = _records(tmp_path, rows)
    assert not any(r["name"].startswith("LEFT GI") for r in recs)
    assert sum(1 for r in recs if r["name"].startswith("SPEAKER")) == 3


def test_unplaced_lamps_do_not_join_short_runs_into_a_table(tmp_path):
    """Star Wars ELG: a lone blank switch between unplaced lamps was never a
    run of four, and must not become part of one."""
    rows = (_placed(5) + _speakers(3) +
            [(None, 1, (0, 0, 0, 0), "STRAY SWITCH", None)] + _speakers(3))
    recs = _records(tmp_path, rows)
    assert "STRAY SWITCH" not in [r["name"] for r in recs]
    assert sum(1 for r in recs if r["name"].startswith("SPEAKER")) == 6


def test_the_rows_round_trip_and_become_a_speaker_ring(tmp_path):
    """device_xy.txt to cablights: node 7, the board at group 10 in the
    title's directory (Godzilla LE), a ring of pixels."""
    recs = _records(tmp_path, _placed(5) + _speakers(6))
    p = tmp_path / "device_xy.txt"
    p.write_text(devicexy.text("godzilla_le", recs, None, 313, 710),
                 newline="")
    rows = devicexy.read_table(str(p))
    boards = {7: {"type": "ws2812node", "group": 10,
                  "name": "Backbox Speaker Lights"}}
    secs, left = cablights.sections(rows, {}, boards)
    assert left == []
    assert [(S["role"], S["node"], len(S["pixels"])) for S in secs] == \
        [(cablights.SPEAKER, 7, 2)]


def test_the_reader_revision_moved_so_cached_tables_are_rebuilt():
    """A table cached by revision 2 names the same binary and would be served
    for ever without the speaker rows."""
    assert devicexy.READER_REV >= 3
