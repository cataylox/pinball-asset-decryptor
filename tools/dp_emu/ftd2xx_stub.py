#!/usr/bin/env python3
"""Write a stand-in FTD2XX.dll for a Windows Dutch Pinball build.

    ftd2xx_stub.py <out FTD2XX.dll>

Bride of Pinbot 2.0 is a Windows program (a 32-bit PyInstaller build of the
same `dp` framework as The Big Lebowski).  Its pinproc.pyd links FTDI's
D2XX driver DLL, which a real machine gets from FTDI's driver install and
the update zip does not carry - so the game dies at `import pinproc`
("DLL load failed") before it gets to choose FakePinPROC.  On `fakepinproc`
nothing ever calls the driver; the DLL only has to LOAD.

So this writes the smallest valid PE32 DLL that exports ordinals 1..64 (the
build imports 2, 3, 4, 6, 7, 18, 27 and 28, by ordinal only): every export
is `mov eax, 2 (FT_DEVICE_NOT_FOUND); ret`, and DllMain returns TRUE.  No
imports, no absolute addresses (so no relocations are needed wherever the
loader puts it).  If anything did call it, the caller would get "no device"
- the answer a PC with no P-ROC plugged in gives anyway.

The stub's `ret` pops no arguments (D2XX is stdcall), so a call WOULD
unbalance the caller's stack; it is not called on fakepinproc, which is the
only way the rig runs the game.
"""
import struct
import sys

N_EXPORTS = 64
IMAGE_BASE = 0x6F200000
SECT_RVA = 0x1000
FILE_ALIGN = 0x200


def build():
    code = bytearray()
    dllmain = SECT_RVA + len(code)
    code += b"\xB8\x01\x00\x00\x00\xC2\x0C\x00"          # mov eax,1 ; ret 12
    stub = SECT_RVA + len(code)
    code += b"\xB8\x02\x00\x00\x00\xC3"                  # mov eax,2 ; ret
    while len(code) % 16:
        code += b"\xCC"
    name = b"FTD2XX.dll\0"
    exp_rva = SECT_RVA + len(code)
    funcs_rva = exp_rva + 40
    name_rva = funcs_rva + 4 * N_EXPORTS
    export = struct.pack("<IIHHIIIIIII", 0, 0, 0, 0, name_rva, 1, N_EXPORTS, 0,
                         funcs_rva, 0, 0)
    export += struct.pack("<%dI" % N_EXPORTS, *([stub] * N_EXPORTS)) + name
    exp_size = len(export)
    body = bytes(code) + export
    raw_size = (len(body) + FILE_ALIGN - 1) // FILE_ALIGN * FILE_ALIGN
    virt_size = len(body)
    image_size = SECT_RVA + (virt_size + 0xFFF) // 0x1000 * 0x1000

    dos = b"MZ" + b"\0" * 58 + struct.pack("<I", 0x40)
    coff = struct.pack("<HHIIIHH", 0x14C, 1, 0, 0, 0, 0xE0,
                       0x2102)                          # EXE | 32BIT | DLL
    opt = struct.pack("<HBBIIIIIIIIIHHHHHHIIIIHHIIIIII",
                      0x10B, 0, 0, raw_size, 0, 0, dllmain, SECT_RVA, SECT_RVA,
                      IMAGE_BASE, 0x1000, FILE_ALIGN, 4, 0, 0, 0, 4, 0, 0,
                      image_size, FILE_ALIGN, 0, 2,
                      0x0140,                           # DYNAMIC_BASE | NX_COMPAT
                      0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    dirs = [(0, 0)] * 16
    dirs[0] = (exp_rva, exp_size)
    opt += b"".join(struct.pack("<II", *d) for d in dirs)
    sect = struct.pack("<8sIIIIIIHHI", b".text", virt_size, SECT_RVA, raw_size,
                       FILE_ALIGN, 0, 0, 0, 0, 0x60000020 | 0x40000000)
    head = dos + b"PE\0\0" + coff + opt + sect
    head += b"\0" * (FILE_ALIGN - len(head))
    return head + body + b"\0" * (raw_size - len(body))


def main(argv):
    if len(argv) != 1:
        sys.exit(__doc__)
    with open(argv[0], "wb") as f:
        f.write(build())
    print(argv[0])


if __name__ == "__main__":
    main(sys.argv[1:])
