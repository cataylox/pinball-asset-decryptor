"""tools/cgcpf_emu (PAD-274): CGC's Pulp Fiction on qemu-arm - the switch
map and its polarity, the shared io.bin layout, the ball model, the carve
and the picture - everything that can be checked without WSL.

The numbers are the game's own (pin 1.0.2, read from its disassembly):
the switch-name table at 0xea584, the opto flags it keeps at 0x456ee4, the
coils its procs fire (gameTroughReleaseProc fires 11, gameShootBallProc 10).
"""

import importlib.util
import pathlib
import re
import struct
import sys

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "cgcpf_emu"
sys.path.insert(0, str(RIG))


def _load(name):
    spec = importlib.util.spec_from_file_location("cgcpf_" + name, RIG / ("%s.py" % name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sw = _load("sw")
pfball = _load("pfball")
prepare = _load("prepare")
shot = _load("shot")


@pytest.fixture
def io(tmp_path):
    return sw.IO(str(tmp_path / "io.bin"))


# ------------------------------------------------------------- switches
def test_the_table_is_the_games_80_switches():
    # 10 banks of 8: 0-63 from the playfield board, 64-79 the cabinet bus
    assert len(sw.NAMES) == 80
    assert sw.NAMES[1] == "Trough 1" and sw.NAMES[22] == "Shooter"
    assert sw.NAMES[64] == "Start" and sw.NAMES[67] == "Coin Door"
    assert sw.NAMES[72] == "Coin Left" and sw.NAMES[79] == "Enter"


@pytest.mark.parametrize("given,num", [("coin left", 72), ("COIN_LEFT", 72),
                                       ("Trough 1", 1), ("22", 22), ("start", 64)])
def test_switches_by_name_or_number(given, num):
    assert sw.number(given) == num


def test_an_unknown_switch_is_refused():
    with pytest.raises(SystemExit):
        sw.number("tilt bob")


def test_home_is_a_full_trough_and_a_shut_coin_door(io):
    io.home()
    closed = {n for n in range(80) if io.closed(n)}
    assert closed == set(sw.TROUGH) | {sw.COIN_DOOR}


def test_the_wire_is_active_low_except_on_optos(io):
    io.home()
    # an ordinary switch closed = the input pulled low (bit set in io.bin)
    assert io.low(sw.COIN_DOOR)
    # a trough opto with a ball in its beam drives the input HIGH; the
    # game counts no ball from a low one (its switch kind 1 needs state 4)
    assert all(not io.low(n) for n in sw.TROUGH)
    # an empty subway / briefcase stack: beams clear, inputs low
    assert all(io.low(n) for n in (5, 6, 7, 8, 32, 33, 34, 35))


def test_optos_are_the_games_kind_1_switches():
    assert sw.OPTOS == set(range(0, 11)) | {28, 32, 33, 34, 35}


def test_io_offsets_match_the_shims_struct():
    """sw.py's offsets are struct pf_io in pfshim.c, field by field."""
    src = (RIG / "pfshim.c").read_text()
    body = re.search(r"struct pf_io \{(.*?)\};", src, re.S).group(1)
    sizes = {"char": 1, "uint8_t": 1, "uint32_t": 4}
    off, fields = 0, {}
    for typ, name, count in re.findall(r"(char|uint8_t|uint32_t)\s+(\w+)(?:\[([^\]]+)\])?;", body):
        n = eval(count) if count else 1
        size = sizes[typ]
        off = (off + size - 1) // size * size
        fields[name] = off
        off += size * n
    assert fields["xfers"] == sw.OFF_XFERS
    assert fields["sw"] == sw.OFF_SW
    assert fields["ext"] == sw.OFF_EXT
    assert fields["out"] == sw.OFF_OUT
    assert fields["fram_ops"] == sw.OFF_FRAM
    assert fields["type"] == sw.OFF_TYPE
    assert fields["cab_reads"] == sw.OFF_CAB
    assert off <= 4096 and sw.MAGIC == b"PFI2" and '"PFI2"' in src


def test_a_tap_opens_the_switch_again(io, monkeypatch):
    monkeypatch.setattr(sw.time, "sleep", lambda s: None)
    monkeypatch.setattr(sw, "IO", lambda: io)
    sw.main(["tap", "start", "40"])
    assert not io.closed(64)


def test_launch_takes_the_ball_off_the_shooter(io, monkeypatch):
    monkeypatch.setattr(sw.time, "sleep", lambda s: None)
    monkeypatch.setattr(sw, "IO", lambda: io)
    io.set(sw.SHOOTER, True)
    sw.main(["launch"])
    assert not io.closed(sw.SHOOTER) and not io.closed(sw.SHOOTER_UPPER)


def test_drain_refills_the_trough_from_the_eject_end(io, monkeypatch):
    monkeypatch.setattr(sw, "IO", lambda: io)
    io.home()
    pfball.set_trough(io, 2)
    sw.main(["drain"])
    assert pfball.trough_count(io) == 3


# ------------------------------------------------------------ the balls
def fire(io, coil, on=True):
    byte, b = coil
    v = io.m[sw.OFF_OUT + byte - 1]
    io.m[sw.OFF_OUT + byte - 1] = (v | (1 << b)) if on else (v & ~(1 << b))


def test_coils_sit_in_packet_bytes_20_to_22():
    assert pfball.coil(11) == (21, 3)        # seen firing on the rig
    assert pfball.TROUGH_COIL == (21, 3)
    assert pfball.SHOOTER_COIL == (21, 2)


def test_the_trough_coil_serves_one_ball_to_the_shooter_lane(io):
    io.home()
    said = []
    balls = pfball.Balls(io, said.append)
    fire(io, pfball.TROUGH_COIL)
    balls.step(10.0)
    # PWM: the bit flickers for the whole pulse - still one ball
    fire(io, pfball.TROUGH_COIL, False)
    balls.step(10.01)
    fire(io, pfball.TROUGH_COIL)
    balls.step(10.02)
    fire(io, pfball.TROUGH_COIL, False)
    assert pfball.trough_count(io) == 3 and not io.closed(sw.SHOOTER)
    balls.step(10.0 + pfball.LANE_DELAY + 0.01)
    assert io.closed(sw.SHOOTER)
    assert said == ["trough eject: 3 left", "ball in the shooter lane"]


def test_no_second_ball_while_the_lane_is_full(io):
    io.home()
    io.set(sw.SHOOTER, True)
    balls = pfball.Balls(io, lambda m: None)
    fire(io, pfball.TROUGH_COIL)
    balls.step(5.0)
    assert pfball.trough_count(io) == 4


def test_the_auto_plunger_puts_the_lane_ball_in_play(io):
    io.home()
    io.set(sw.SHOOTER, True)
    said = []
    balls = pfball.Balls(io, said.append)
    fire(io, pfball.SHOOTER_COIL)
    balls.step(1.0)
    assert not io.closed(sw.SHOOTER)
    balls.step(1.06)
    assert io.closed(sw.SHOOTER_UPPER)
    balls.step(1.2)
    assert not io.closed(sw.SHOOTER_UPPER)
    assert said[-1] == "ball in play"


# ------------------------------------------------------------ the carve
EXTENTS = """Level Entries         Logical          Physical Length Flags
 0/ 1   1/  1      0 - 888831   32961           888832
 1/ 1   1/ 29      0 -   6143  157696 -  163839   6144
 1/ 1   2/ 29   6144 -  38911  165888 -  198655  32768
 1/ 1   3/ 29  38912 -  69631  198656 -  229375  30720 Uninit
"""


def test_extents_take_the_leaves_and_skip_unwritten_ones(monkeypatch):
    out = {"stats": "Block size:               4096\n", "dump_extents /emmc.img": EXTENTS}
    monkeypatch.setattr(prepare, "debugfs", lambda img, off, cmd: out[cmd])
    ext, bs = prepare.extents("x.img", 0, "/emmc.img")
    assert bs == 4096
    assert ext == [(0, 6143, 157696), (6144, 38911, 165888)]


def test_mbr_partitions_are_read_from_the_table():
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xaa"
    struct.pack_into("<4xB3xII", mbr, 0x1BE, 0x0C, 2048, 131072)
    struct.pack_into("<4xB3xII", mbr, 0x1CE, 0x83, 133120, 6963200)
    parts = prepare.partitions(lambda off, n: bytes(mbr[off:off + n]))
    assert parts == [(1, 0x0C, 2048 * 512, 131072 * 512), (2, 0x83, 133120 * 512, 6963200 * 512)]


def test_a_nested_file_reads_through_its_extents(tmp_path, monkeypatch):
    bs = 4096
    img = tmp_path / "card.img"
    data = bytearray(bs * 8)
    data[bs * 5:bs * 6] = b"B" * bs            # logical block 0 lives at 5
    data[bs * 2:bs * 3] = b"A" * bs            # logical block 1 lives at 2
    img.write_bytes(bytes(data))
    monkeypatch.setattr(prepare, "extents", lambda i, o, p: ([(0, 0, 5), (1, 1, 2)], bs))
    f = prepare.Nested(str(img), 0, "/emmc.img")
    got = f.read(bs - 2, 4)
    assert got == b"BBAA"


# ---------------------------------------------------------- the picture
def test_the_picture_lays_the_three_buffers_over_each_other(tmp_path):
    w, h = 4, 2
    pitch = w * 2
    hdr = bytearray(4096)
    offs = [4096, 8192, 12288]
    struct.pack_into("<4s7I", hdr, 0, b"PFFB", w, h, pitch, 16, offs[0], 9, 3)
    struct.pack_into("<3I", hdr, 32, *offs)
    bufs = [bytearray(4096) for _ in offs]
    struct.pack_into("<H", bufs[0], 0, 0xF800)          # red, on screen
    struct.pack_into("<H", bufs[1], 2, 0x07E0)          # green, off screen
    struct.pack_into("<H", bufs[2], 0, 0x001F)          # blue under the red
    fb = tmp_path / "fb.bin"
    fb.write_bytes(bytes(hdr) + b"".join(bytes(b) for b in bufs))
    _, _, _, _, flips, raw = shot.read_frames(str(fb))
    px = struct.unpack("<%dH" % (w * h), raw[:w * h * 2])
    assert flips == 9 and px[0] == 0xF800 and px[1] == 0x07E0 and px[2] == 0
    front = shot.read_frames(str(fb), front_only=True)[5]
    assert struct.unpack_from("<H", front, 2)[0] == 0
    out = tmp_path / "s.png"
    shot.png(str(out), w, h, shot.to_rgb(w, h, pitch, 16, raw))
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------- scripts
@pytest.mark.parametrize("script", sorted(p.name for p in RIG.glob("*.sh")))
def test_scripts_are_lf_and_source_the_path_file(script):
    text = (RIG / script).read_bytes()
    assert b"\r" not in text
    if script != "cgcpfpath.sh":
        assert b"cgcpfpath.sh" in text


def test_nothing_kills_by_the_programs_name():
    # every slot's game is ./pin: stops go by this slot's root and marker
    for p in RIG.glob("*.sh"):
        code = "\n".join(l for l in p.read_text().splitlines() if not l.lstrip().startswith("#"))
        assert not re.search(r"pkill\s+(-\w+\s+)*pin\b", code), p.name


def test_the_hook_only_goes_over_this_builds_bytes():
    src = (RIG / "pfshim.c").read_text()
    assert "memcmp(p, h->orig, sizeof h->orig)" in src
    assert "0x5667c" in src
