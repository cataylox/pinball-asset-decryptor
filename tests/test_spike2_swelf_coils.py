"""Item 167: the SWELF titles' coils reach the rig's device table, so its ball feeder sees the trough eject.

devicexy.py finds no device records on the SWELF generation (Aerosmith, Avengers, Batman, Guardians,
Iron Maiden, Mando, Rush, Stranger Things, Sword of Rage), nor any coil on Foo Fighters' older 48-byte
records, so their device_xy.txt held no coil and a game there asked for balls the rig never served.
swelf.coils() reads the coils out of the same device table the switch walk reads; mktables.py appends
them once. Desk only: synthetic coils, and the real ELFs when this
machine has them.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu")
if RIG not in sys.path:
    sys.path.insert(0, RIG)

import coilmap  # noqa: E402
import mktables  # noqa: E402
import swelf  # noqa: E402

COILS = [("RIGHT FLIPPER", 8, 0), ("TROUGH", 8, 1), ("AUTO PLUNGER", 8, 4), ("RIGHT EJECT", 9, 1)]


def test_coil_lines_parse_to_the_bus_address(tmp_path, monkeypatch):
    monkeypatch.setattr(swelf, "coils", lambda elf, title: list(COILS))
    lines = swelf.coil_lines("game", "aerosmith_le")
    p = tmp_path / "device_xy.txt"
    p.write_text("# aerosmith_le device positions\n" + "\n".join(lines) + "\n")
    coils = coilmap.load(str(p))
    assert coilmap.eject_address(coils) == (8, 1)
    assert coilmap.address(coils, coilmap.AUTO_PLUNGER) == (8, 4)
    assert coilmap.address(coils, "RIGHT EJECT") == (9, 1)


def test_mktables_appends_once_and_leaves_a_table_with_coils_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(swelf, "coils", lambda elf, title: list(COILS))
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF")
    p = tmp_path / "device_xy.txt"
    header = "# aerosmith_le device positions, from the game binary.\n# 0 records (), 0 on the playfield image.\n"
    p.write_text(header)
    said = []
    mktables._swelf_coils(str(p), str(elf), "aerosmith_le", said.append)
    text = p.read_text()
    assert text.startswith(header) and sum(1 for x in text.splitlines() if x.startswith("coil")) == 4
    assert said and "4 coil(s)" in said[0]
    mktables._swelf_coils(str(p), str(elf), "aerosmith_le", said.append)
    assert p.read_text() == text and len(said) == 1          # idempotent
    gz = tmp_path / "gz.txt"
    gz.write_text("coil      TROUGH   260   613   20   20    6     1  -      playfield\n")
    mktables._swelf_coils(str(gz), str(elf), "godzilla_pro", said.append)
    assert "item 167" not in gz.read_text()                   # a table with coils is never touched


ELFS = r"C:\tmp\pad_generic\elfs"


@pytest.mark.parametrize("key, title", [("aerosmith_le-1.15", "aerosmith_le"), ("batman-1.13", "batman"),
                                        ("stranger_things_le-1.12", "stranger_things_le"),
                                        ("rush_le-1.18", "rush_le"), ("foo_fighters_le-1.04", "foo_fighters_le")])
def test_the_real_device_tables_name_the_trough_on_node_8(key, title):
    elf = os.path.join(ELFS, key + ".0.elf")
    if not os.path.isfile(elf):
        pytest.skip("game program not present: %s" % elf)
    got = {name: (node, index) for name, node, index in swelf.coils(elf, title)}
    assert got["TROUGH"] == (8, 1) and got["AUTO PLUNGER"] == (8, 4)
