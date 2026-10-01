#!/usr/bin/env python3
"""frame_sites.py - find a Spike 2 game's frame hand-over sites (PAD-301) from its tick site.

    frame_sites.py <game ELF> <tick address>

Prints the two port lines `site frame_end` and `site frame_kick` with their first two instruction words,
or says which step of the chain did not match. The chain (portgen.frame_chain, which port_tool.py also
follows when a draft cannot place the two by signature), read off Godzilla Premium 1.16:

    main loop:   bl tick ; bl frame_begin (r0 = renderer busy) ; mov <r>, r0 ; ...processes...
                 mov r0, <r> ; bl frame_end
    frame_end:   cmp r0, #0 ; push ... ; ... ; b kick        (both paths end in the kick)

frame_end is the first `bl` after the tick's call whose r0 comes from the register the begin's answer
was kept in; the kick is the first unconditional `b` that leaves frame_end (below it on Premium 1.16,
above it on Pro 1.15).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))
from pinball_decryptor.plugins.stern import portgen  # noqa: E402


def find(path, tick):
    """``([(name, address, word0, word1), ...], None)`` or ``(None, why)``."""
    elf = portgen.Elf(path)
    end, kick, why = portgen.frame_chain(elf, tick)
    if end is None:
        return None, why
    return [(n, a, elf.word(a), elf.word(a + 4)) for n, a in (("frame_end", end), ("frame_kick", kick))], None


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    got, why = find(sys.argv[1], int(sys.argv[2], 16))
    if not got:
        sys.exit("frame_sites: " + why)
    for name, a, w0, w1 in got:
        print("site %-16s 0x%08x 0x%08x 0x%08x" % (name, a, w0, w1))


if __name__ == "__main__":
    main()
