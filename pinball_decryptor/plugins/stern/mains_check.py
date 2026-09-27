"""WHAT A SPIKE 2 BUILD DOES ABOUT 50 Hz MAINS - read off the game binary.

The Emulate tab's Power row can put the machine on 50 Hz with a US CPU board,
which is the setup a US game refuses to run on: "THIS MACHINE WILL NOT OPERATE
IN THIS COUNTRY".  The emulator sets that up faithfully (run_game.sh's
PAD_MAINS_HZ, hwshim's PAD_FACTORY_HZ) and no longer presses past the refusal
(PAD-173).  WHETHER THE REFUSAL COMES IS THE GAME'S OWN DECISION, and the
builds do not agree - which is why a user picked the lock, saw his game start
anyway, and reported it twice (Sam, PAD-149 and PAD-173).

THE CHECK, decoded from stranger_things_le 1.12.0 (0x23996c) and confirmed on
godzilla_pro 1.15.0 (0x4ed698).  Both end in the same test of the frequency
the game measured:

    sub r3, r3, #0x39      e2433039      measured - 57
    cmp r3, #6             e3530006      ...in 57..63 ?

and both reach it only once the game's own power sampler has its readings
(375 warm-up ticks and 24 good samples).  The difference is the arm that runs
while it does NOT have them, and that arm is everything:

    stranger_things_le 1.12.0   cmp r3,#0x3a8 / bls -> a plain return
                                It asks again on the next tick, and ~16 s in
                                it has the readings, fails the test and puts
                                the refusal on the glass.  MEASURED: the
                                refusal appeared and the game then ignored
                                every service button.
    godzilla_pro 1.15.0         cmp r3,#0x3a8 / bls -> mov r0,#2 / bl flag_set
                                Flag 2 is "the mains question is answered", so
                                the FIRST tick without readings ends the check
                                for the run.  MEASURED with PAD_PEEK: the
                                check ran once 3.3 s in with 10 of the 375
                                readings, flag 2 went up in the same instant,
                                and the game booted to attract on 50 Hz with a
                                US board.  Slowing the node-bus bring-up right
                                down did not move it.

And two titles carry no check at all - jurassic_park_the_pin 1.05.0 and
star_wars_elg 1.10.0, both home machines, which is the honest answer to "why
does my Jurassic Park still start?".  Measured across David's 57-card library.

So this module answers, for one card, WHICH OF THE THREE a title is, straight
off the binary: no run, no rig, no WSL.  The Emulate tab says it beside the
Power row rather than letting the app promise a lock the game will not give.
"""
import os
import struct

#: the game measures nothing about the mains: no check in the binary
NONE = "none"
#: the check is there and keeps asking until it can answer (the refusal comes)
SHOWS = "shows"
#: the check is there but the first tick without readings ends it (no refusal)
SKIPS = "skips"
#: the binary could not be read, or its check does not match either shape
UNKNOWN = "unknown"

#: sub r3,r3,#0x39 / cmp r3,#6 - the 57..63 Hz test both shapes end in
_TEST = struct.pack("<II", 0xe2433039, 0xe3530006)
#: cmp r3, #0x3a8 - the wait counter, a few instructions from the test
_COUNTER = struct.pack("<I", 0xe3530fea)
#: mov r0, #2 - the first instruction of the give-up arm (flag_set(2) follows)
_MOV_R0_2 = 0xe3a00002
#: how far either side of the test the counter compare sits (both builds put
#: it within 0x400; the arms are ordered differently by build)
_WINDOW = 0x400


def _loads(elf):
    """(vaddr, offset, filesz) for each PT_LOAD, or [] for a non-ELF."""
    if len(elf) < 0x34 or elf[:4] != b"\x7fELF":
        return []
    phoff = struct.unpack_from("<I", elf, 0x1c)[0]
    phnum = struct.unpack_from("<H", elf, 0x2c)[0]
    out = []
    for i in range(phnum):
        base = phoff + 32 * i
        if base + 32 > len(elf):
            break
        p_type, p_off, p_va, _pa, p_fsz = struct.unpack_from("<5I", elf, base)
        if p_type == 1:
            out.append((p_va, p_off, p_fsz))
    return out


def verdict_bytes(elf):
    """:data:`NONE` / :data:`SHOWS` / :data:`SKIPS` / :data:`UNKNOWN` for one
    ARM game binary, whole, in memory."""
    loads = _loads(elf)
    if not loads:
        return UNKNOWN
    hit = elf.find(_TEST)
    if hit < 0:
        return NONE

    def va_of(off):
        for va, o, fsz in loads:
            if o <= off < o + fsz:
                return va + off - o
        return None

    def off_of(va):
        for v, o, fsz in loads:
            if v <= va < v + fsz:
                return o + va - v
        return None

    site = va_of(hit)
    if site is None:
        return UNKNOWN
    c = elf.find(_COUNTER, max(0, hit - _WINDOW), hit + _WINDOW)
    if c < 0 or c + 8 > len(elf):
        return UNKNOWN
    cva = va_of(c)
    branch = struct.unpack_from("<I", elf, c + 4)[0]
    if cva is None or (branch >> 24) != 0x9a:        # bls <target>
        return UNKNOWN
    imm = branch & 0xffffff
    if imm & 0x800000:
        imm -= 0x1000000
    target = off_of(cva + 4 + 8 + imm * 4)           # ARM pipeline: PC + 8
    if target is None or target + 4 > len(elf):
        return UNKNOWN
    first = struct.unpack_from("<I", elf, target)[0]
    return SKIPS if first == _MOV_R0_2 else SHOWS


def verdict_card(path, title=None):
    """``(title, verdict)`` for a card image - the game binary is read with
    the app's own ext4 reader, so this works on Windows with no WSL.

    *title* picks one game directory on a multi-image card; without it the
    first title that carries a ``game`` binary answers, which is the image the
    emulator boots (PAD-122).  A card that cannot be read is
    ``(None, UNKNOWN)`` rather than an exception: this decides a sentence on a
    tab, and it must never be the reason a card cannot be run.
    """
    from .explorer import CardImage
    try:
        with CardImage(path) as card:
            for part in card.partitions():
                if not part.browsable:
                    continue
                try:
                    reader = card.reader(part.index)
                    root = reader.read_inode(2)
                except Exception:                        # noqa: BLE001
                    continue
                for name, ino, _ft in reader._iter_dir(root):
                    if name in (".", "..", "lost+found", "data", "dump"):
                        continue
                    if title is not None and name != title:
                        continue
                    try:
                        node = reader.read_inode(ino)
                        game = None
                        for child, cino, _cft in reader._iter_dir(node):
                            if child == "game":
                                game = reader.read_inode(cino)
                                break
                        if game is None or game["size"] < (1 << 20):
                            continue
                        blob = b"".join(
                            chunk for _off, chunk
                            in reader.read_file_chunks(game))
                    except Exception:                    # noqa: BLE001
                        continue
                    return name, verdict_bytes(blob)
    except Exception:                                    # noqa: BLE001
        return None, UNKNOWN
    return None, UNKNOWN


def sentence(title, verdict):
    """What to tell the person who picked "50 Hz mains, US machine", or ""
    when the game will do what the setting promises.

    Named after the game the way the card names it, because a multi-image
    card's images can differ and "this game" would not say which.
    """
    name = title or "this game"
    if verdict == NONE:
        return ("%s has no mains check in it: the board runs on either "
                "mains, so nothing here can stop it starting. Home machines "
                "are built that way." % name)
    if verdict == SKIPS:
        return ("%s asks about the mains once at power-up and answers itself "
                "when its own power reading is not ready yet, which is how it "
                "boots here - so it starts normally on 50 Hz. Older code "
                "(Stranger Things 1.12, say) keeps asking and does refuse."
                % name)
    return ""


def cache_stamp(path):
    """``(size, mtime)`` for *path*, or None - what a caller keeps beside a
    verdict so a card is only read once."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_size, st.st_mtime)
