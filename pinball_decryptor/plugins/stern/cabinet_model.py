"""WHICH MODEL A SPIKE 2 MACHINE IS - Pro, Premium, LE, SLE - read off the game binary (PAD-519).

A tester asked to pick the edition in the emulator (Premium / LE / SLE on Batman 66, and so on)
"to display the software specificities of these editions and to change the boot screen".

THE GAME DOES NOT KNOW ITS EDITION FROM THE CARD. One Premium/LE card runs every Premium, LE and
SLE of a title; the machine says which it is with a MODEL CODE in the cabinet identity record, the
first 52 bytes of the CPU board's i2c EEPROM (decoded in tools/spike2_emu/hwshim.c,
``nv_ident_seed``: [0..3] serial, [4..7] the model code, [8..9] mains Hz, [10..11] a check). The
emulator's own record says "999", the engine's wildcard for "the build's compiled-in model", which
is why every run so far booted as whatever the build was compiled as (Batman 66 1.14: Premium).

THE CODES, decoded from batman 1.14.0 (title routine 0x2b5758, wrapper 0x2b567c, classifier
0x2b53c0) and the same shape in every build read. The title routine asks a wrapper for the model;
the wrapper hands the engine's classifier TWELVE code strings, three per class in a fixed order,
each a pointer in .data:

    Pro      Batman "05" "08"        Star Wars "J5" "J8" "08"   Munsters "L1" "05" "08"
    LE       Batman "I0" "06" "0A"   Elvira    "J1" "X2" "0A"   Munsters "L2" "06" "0A"
    Premium  Batman "I2" "I9" "09"   Elvira    "J2" "04" "09"   Munsters "L3" "L4" "09"
    SLE      Batman "I3" "I4" "0B"   Elvira    "J3" "J4" "0B"   Munsters (none of its own)

and the classifier answers 2 Pro, 3 LE, 4 Premium, 6 SLE, 5 for a code it does not know - the
indexes of the build's own word table " PRO" / " LE" / " PRE" / " PRE/LE" / " SLE", the same on
every build read. Each class's second and third strings come back flagged as alternates.

WHAT IT CHANGES, MEASURED on the rig (Batman 1.14, PAD-519): the title routine swaps the compiled
title's " PRE" for the class's word, and the service menu's first page names the machine with it
and its code - "BATMAN PRE" / "000000-I2-..." on the card's own model, "BATMAN LE" / "I0" with the
LE picked on the Emulate tab, "BATMAN SLE" / "I3" as an SLE. (The routine's entry is 8 bytes before
its push, a `cmp r0,#0; bxeq lr` guard; it has 12-13 callers on every build read - menu pages,
the Insider report.) The BOOT SCREEN does not follow: it is drawn from the compiled title, and
Batman as an SLE still boots "BATMAN PRE". The model also decides the Pro vs Premium/LE check
("PRE/LE CODE PRESENT ON PRO GAME") and the LE number's page, and a title's own checks where it has
them (hwshim.c nv_ident_seed: Stranger Things' projector).

A TITLE OF ITS OWN. The title routine carries three more strings, an own title for the LE, the
Premium and the Pro (loaded in that order, empty on most builds), used in place of the compiled
title when the board's code is that class's ALTERNATE. That is where Stern's named editions live:
Elvira 1.13 LE "X2" = "ELVIRA'S BLOOD RED KISS LE", Godzilla LE 1.16 Premium "T8" = "GODZILLA:
70TH ANNIVERSARY", Iron Maiden LE 1.18 "N8" = "IRON MAIDEN: 50TH ANNIVERSARY", Jaws LE 1.02 "AL" =
"JAWS ANNIVERSARY PREMIUM EDITION", Jurassic Park LE 1.16 LE "M6" = "JURASSIC PARK: 30TH
ANNIVERSARY LE" (library sweep, 53 latest cards). Each is offered as an edition of its own.

WHICH CODES A BUILD TAKES is the classifier's own answer, so this module RUNS it (unicorn, which
the app already ships for the audio engine) on every code in the table instead of trusting the
order above. That matters: a PRO build answers Pro for every code and raises a second flag for a
Premium/LE one, which is its "PRE/LE CODE PRESENT ON PRO GAME" message - measured on star_wars_pro
1.31.0. So a Pro card has no edition to pick, and a Premium/LE card offers the classes it answers
for. An alternate code is offered only where its class has a title of its own; elsewhere the game
treats it as its class, and the class's first code stands for it.

Read-only, no rig, no WSL: the Emulate tab shows the choices for the card picked, and Start hands
the code to the shim as PAD_MODEL.
"""
import struct

from .mains_check import _loads, game_binary

#: the classifier's answers
PRO, LE, PREMIUM, PRE_LE, SLE = 2, 3, 4, 5, 6
CLASS_NAMES = {PRO: "Pro", LE: "LE", PREMIUM: "Premium", PRE_LE: "Premium/LE", SLE: "SLE"}
#: the wrapper's twelve strings, in the order the classifier takes them (three per class)
_ORDER = (PRO,) * 3 + (LE,) * 3 + (PREMIUM,) * 3 + (SLE,) * 3
#: the engine's wildcard model: the reader puts the build's compiled-in code in its place
WILDCARD = "999"
#: the order the choices are listed in
_LIST = (PREMIUM, LE, SLE, PRO)


class _Elf:
    def __init__(self, blob):
        self.blob = blob
        self.loads = _loads(blob)

    def off(self, va):
        for v, o, fsz in self.loads:
            if v <= va < v + fsz:
                return o + va - v
        return None

    def va(self, off):
        for v, o, fsz in self.loads:
            if o <= off < o + fsz:
                return v + off - o
        return None

    def word(self, va):
        o = self.off(va)
        if o is None or o + 4 > len(self.blob):
            return None
        return struct.unpack_from("<I", self.blob, o)[0]

    def cstr(self, va, n=8):
        o = self.off(va)
        if o is None:
            return None
        s = self.blob[o:o + n].split(b"\0", 1)[0]
        try:
            return s.decode("ascii")
        except UnicodeDecodeError:
            return None


def _movw_movt_sites(elf, target):
    """Code addresses where a movw/movt pair builds *target* in one register."""
    lo, hi = target & 0xffff, target >> 16
    out = []
    b = elf.blob
    for v, o, fsz in elf.loads:
        end = o + fsz - 4
        k = o
        while k < end:
            w = struct.unpack_from("<I", b, k)[0]
            if (w & 0x0ff00000) == 0x03000000 and \
                    ((w >> 4) & 0xf000 | (w & 0xfff)) == lo:
                rd = (w >> 12) & 0xf
                for j in range(k + 4, min(k + 32, end), 4):
                    w2 = struct.unpack_from("<I", b, j)[0]
                    if (w2 & 0x0ff00000) == 0x03400000 and ((w2 >> 12) & 0xf) == rd:
                        if ((w2 >> 4) & 0xf000 | (w2 & 0xfff)) == hi:
                            out.append(v + j - o)
                        break
            k += 4
    return out


def _fn_start(elf, va, limit=0x2000):
    """The push {.., lr} that opens the function holding *va*."""
    a = va
    while a > va - limit:
        w = elf.word(a)
        if w is not None and (w & 0xffff4000) == 0xe92d4000:
            return a
        a -= 4
    return None


def _bl_target(addr, w):
    imm = w & 0xffffff
    if imm & 0x800000:
        imm -= 0x1000000
    return addr + 8 + imm * 4


def _string_va(elf, text):
    o = elf.blob.find(b"\0" + text + b"\0")
    return None if o < 0 else elf.va(o + 1)


def _wrapper_args(elf, wrapper):
    """``(globals, classifier)``: the twelve .data words the wrapper passes, in argument order,
    and the function it calls - or None when the wrapper is not that shape."""
    regs, stack = {}, {}
    a = wrapper
    for _ in range(80):
        w = elf.word(a)
        if w is None:
            return None
        rd = (w >> 12) & 0xf
        if (w & 0x0ff00000) == 0x03000000:                      # movw
            regs[rd] = ("imm", (w >> 4) & 0xf000 | (w & 0xfff))
        elif (w & 0x0ff00000) == 0x03400000:                    # movt
            old = regs.get(rd)
            low = old[1] & 0xffff if old and old[0] == "imm" else 0
            regs[rd] = ("imm", low | ((w >> 4) & 0xf000 | (w & 0xfff)) << 16)
        elif (w & 0x0ff00fff) == 0x05900000:                    # ldr rd, [rn]
            src = regs.get((w >> 16) & 0xf)
            regs[rd] = ("glob", src[1]) if src and src[0] == "imm" else None
        elif (w & 0x0fef0ff0) == 0x01a00000:                    # mov rd, rm
            regs[rd] = regs.get(w & 0xf)
        elif (w & 0x0fef0000) == 0x03a00000:                    # mov rd, #imm
            regs[rd] = None
        elif (w & 0x0fff0000) == 0x058d0000:                    # str rd, [sp, #imm]
            stack[w & 0xfff] = regs.get(rd)
        elif (w & 0x0f000000) == 0x0b000000:                    # bl
            args = [regs.get(r) for r in range(4)] + [stack.get(4 * i) for i in range(8)]
            if all(x is not None and x[0] == "glob" for x in args):
                return [x[1] for x in args], _bl_target(a, w)
            return None
        a += 4
    return None


def find_table(blob):
    """``{"codes": [(slot class, code or None), ...12], "globals": [...], "classifier": va,
    "builtin": code}`` for one game binary, or None when its model routine is not found."""
    elf = _Elf(blob)
    if not elf.loads:
        return None
    pro = _string_va(elf, b" PRO")
    if pro is None:
        return None
    for site in _movw_movt_sites(elf, pro):
        fn = _fn_start(elf, site)
        if fn is None:
            continue
        a = fn
        while a < site:
            w = elf.word(a)
            if w is not None and (w & 0x0f000000) == 0x0b000000:
                got = _wrapper_args(elf, _bl_target(a, w))
                if got:
                    globs, classifier = got
                    codes = []
                    for g in globs:
                        p = elf.word(g)
                        codes.append(elf.cstr(p) if p else None)
                    titles, title = _titles(elf, a + 4, site)
                    return {"codes": list(zip(_ORDER, codes)), "globals": globs,
                            "classifier": classifier, "builtin": _builtin(elf, globs, codes),
                            "titles": titles, "title": title}
            a += 4
    return None


#: the classes the title routine's three title-of-its-own strings belong to, in the order it
#: loads them (batman 1.14.0 0x2b5784..: 0x78ce0c tested with class 3, 0x78caa4 with 4,
#: 0x78c450 with 2)
_TITLE_ORDER = (LE, PREMIUM, PRO)


def _titles(elf, start, end):
    """``({class: title of its own}, compiled title)`` from the title routine after its model
    call: the first three strings it loads are the classes' own titles (empty on every build
    read but Elvira 1.13, whose LE's is "ELVIRA'S BLOOD RED KISS LE"), the fourth the title
    the build was compiled with ("BATMAN PRE")."""
    regs, found = {}, []
    a = start
    while a < end and len(found) < 4:
        w = elf.word(a)
        if w is None:
            break
        rd = (w >> 12) & 0xf
        if (w & 0x0ff00000) == 0x03000000:
            regs[rd] = (w >> 4) & 0xf000 | (w & 0xfff)
        elif (w & 0x0ff00000) == 0x03400000:
            regs[rd] = (regs.get(rd, 0) & 0xffff) | (((w >> 4) & 0xf000 | (w & 0xfff)) << 16)
        elif (w & 0x0ff00fff) == 0x05900000 and ((w >> 16) & 0xf) in regs:
            p = elf.word(regs[(w >> 16) & 0xf])
            found.append(elf.cstr(p, 80) or "" if p else "")
        a += 4
    if len(found) < 4:
        return {}, ""
    return {c: t for c, t in zip(_TITLE_ORDER, found) if t}, found[3]


def _edition_name(title):
    """A title of its own as an edition's name, in ordinary case ("JURASSIC PARK: 30TH
    ANNIVERSARY LE" -> "Jurassic Park: 30th Anniversary LE")."""
    return " ".join(w if w in ("LE", "SLE", "PRO", "PRE") else w.capitalize()
                    for w in title.split())


def _builtin(elf, globs, codes):
    """The code the reader puts in place of "999": the first of the wrapper's globals the
    reader loads after its compare with "999" (Batman 1.14: 0x77ede8 -> "I2")."""
    nines = _string_va(elf, WILDCARD.encode())
    if nines is None:
        return None
    for site in _movw_movt_sites(elf, nines):
        for k in range(1, 48):
            hit = None
            w = elf.word(site + 4 * k)
            if w is None:
                break
            if (w & 0x0ff00000) == 0x03400000:
                rd = (w >> 12) & 0xf
                hi = (w >> 4) & 0xf000 | (w & 0xfff)
                for j in range(1, 8):
                    w0 = elf.word(site + 4 * (k - j))
                    if w0 is not None and (w0 & 0x0ff00000) == 0x03000000 and \
                            ((w0 >> 12) & 0xf) == rd:
                        hit = (hi << 16) | ((w0 >> 4) & 0xf000 | (w0 & 0xfff))
                        break
            if hit in globs:
                return codes[globs.index(hit)]
    return None


def classify(blob, table, codes):
    """``{code: (class, alternate, other_family)}`` - the game's own classifier run on each
    code, the board's record read answered with that code. ``other_family`` is the flag behind
    "PRE/LE CODE PRESENT ON PRO GAME" / "PRO CODE PRESENT ON PRE/LE GAME"."""
    from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR,
                                   UC_ARM_REG_PC)
    elf = _Elf(blob)
    fn = table["classifier"]
    # The calls it makes: the first is the record read, the most frequent the 4-byte compare,
    # anything else (the LE-number read) answers 0.
    bls, a = [], fn
    for _ in range(200):
        w = elf.word(a)
        if w is None:
            break
        if (w & 0x0f000000) == 0x0b000000 and (w >> 28) == 0xe:
            bls.append(_bl_target(a, w))
        elif a != fn and (w & 0xffff4000) == 0xe92d4000:
            break
        a += 4
    if not bls:
        return {}
    reader = bls[0]
    compare = max(set(bls[1:]) or {reader}, key=bls.count)
    STR, STACK, END = 0x10000000, 0x20000000, 0x30000000
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    # The game's segments, each page mapped once (two segments can share a page).
    pages = set()
    for v, _o, fsz in elf.loads:
        pages.update(range(v >> 12, (v + fsz + 0xfff) >> 12))
    for start, count in _runs(sorted(pages)):
        mu.mem_map(start << 12, count << 12)
    for v, o, fsz in elf.loads:
        mu.mem_write(v, blob[o:o + fsz])
    mu.mem_map(STR, 0x1000)
    mu.mem_map(STACK - 0x4000, 0x8000)
    mu.mem_map(END, 0x1000)
    ptrs = []
    for i, (_cls, c) in enumerate(table["codes"]):
        if c is None:
            ptrs.append(0)
        else:
            mu.mem_write(STR + 16 * i, c.encode() + b"\0")
            ptrs.append(STR + 16 * i)
    res = STR + 0x800
    sp = STACK - 0x100
    model = [b""]

    def answer(uc, addr, _size, _data):
        if addr == reader:          # out: serial, mains Hz, model
            uc.mem_write(uc.reg_read(UC_ARM_REG_R0), b"\1\0\0\0" + b"\0" * 4 + model[0])
            uc.reg_write(UC_ARM_REG_R0, 1)
        elif addr == compare:
            x = bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R0), 4))
            y = bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R1), 4))
            n = min(uc.reg_read(UC_ARM_REG_R2), 4)
            uc.reg_write(UC_ARM_REG_R0, 0 if x[:n] == y[:n] else 1)
        else:
            uc.reg_write(UC_ARM_REG_R0, 0)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    for target in set(bls):
        mu.hook_add(UC_HOOK_CODE, answer, begin=target, end=target)
    out = {}
    for code in codes:
        model[0] = code.encode()[:4].ljust(4, b"\0")
        mu.mem_write(res, b"\0" * 16)
        for i, p in enumerate(ptrs[4:] + [res, res + 4, res + 5]):
            mu.mem_write(sp + 4 * i, struct.pack("<I", p))
        for r, p in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), ptrs):
            mu.reg_write(r, p)
        mu.reg_write(UC_ARM_REG_SP, sp)
        mu.reg_write(UC_ARM_REG_LR, END)
        try:
            mu.emu_start(fn, END, count=4000)
        except UcError:
            continue
        flags = bytes(mu.mem_read(res + 4, 2))
        out[code] = (mu.reg_read(UC_ARM_REG_R0), bool(flags[0]), bool(flags[1]))
    return out


def _runs(pages):
    """``(first, count)`` for each run of consecutive page numbers."""
    out = []
    for p in pages:
        if out and out[-1][0] + out[-1][1] == p:
            out[-1][1] += 1
        else:
            out.append([p, 1])
    return out


def editions_bytes(blob):
    """``{"built": class name or "", "choices": [(class name, code), ...]}`` for one game binary:
    the editions this build runs as, each with the code that makes it so. Empty choices when
    the binary's model routine is not found or the build is a Pro (it is Pro whatever the
    machine says)."""
    table = find_table(blob)
    if not table:
        return {"built": "", "choices": []}
    codes = [c for _cls, c in table["codes"] if c]
    # A build whose reader has no "999" wildcard (John Wick 1.02, Bond 60th 1.11) classifies
    # the emulator's own record as it is: "PRE/LE", the title's unknown-model word.
    own = table["builtin"] or WILDCARD
    try:
        answers = classify(blob, table, codes + [WILDCARD])
    except Exception:                                    # noqa: BLE001
        answers = {}
    built = answers.get(own)
    choices, own_title = {}, {}
    titles = table.get("titles") or {}
    for _slot, code in table["codes"]:
        got = answers.get(code)
        if not got:
            continue
        cls, alternate, other = got
        if other or cls not in CLASS_NAMES or cls == PRE_LE:
            continue
        if not alternate:
            choices.setdefault(cls, code)
        elif cls in titles:
            # an alternate code is where a class's title of its own comes in (the title
            # routine uses it only with the alternate flag up): Elvira's "X2"
            own_title.setdefault(cls, code)
    if len(choices) < 2:
        return {"built": CLASS_NAMES.get(built[0], "") if built else "", "choices": []}
    out = []
    for c in _LIST:
        if c in choices:
            out.append((CLASS_NAMES[c], choices[c]))
        if c in own_title:
            out.append((_edition_name(titles[c]), own_title[c]))
    return {"built": CLASS_NAMES.get(built[0], "") if built else "", "choices": out}


def editions_card(path, title=None):
    """``(title, editions_bytes(...))`` for a card image; ``(None, empty)`` when it cannot be
    read. Never raises: it decides a row on a tab, never whether a card runs."""
    name, blob = game_binary(path, title)
    if not blob:
        return None, {"built": "", "choices": []}
    try:
        return name, editions_bytes(blob)
    except Exception:                                    # noqa: BLE001
        return name, {"built": "", "choices": []}
