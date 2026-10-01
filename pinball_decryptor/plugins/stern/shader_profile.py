"""The color profile applied to EVERYTHING the Spike 2 game draws (PAD-305).

A colour profile (core/colour_profile.py) corrects for the machine's screen.
Applied to the user's replacement files it reaches only what they replaced;
David's ask was the other one: "a global color profile that just affects
display output", every picture, clip, mode screen and line of text, with
no asset touched.

WHERE THAT IS POSSIBLE.  Spike 2's renderer (Radium) is linked into the game
program, and every pixel it draws comes out of one of a handful of GLSL ES
fragment shaders it hands the GPU as plain text at boot: the textured sprite
(every picture and scene texture), YUV -> RGB (the video clips), the font
and gradient-text shaders, the solid fill, an external-image sprite and a
debug overlay.  Measured on Godzilla LE 1.16: nine ``gl_FragColor`` writers
in ``.rodata``.  Each ends by writing ``gl_FragColor``; this module rewrites
that one statement to pass the colour through ``pad_cp()``, the profile's
maths (the same as Pillow's and ffmpeg's, core/colour_profile.py) spliced
in as a GLSL function with the numbers baked in as literals.

PREMULTIPLIED ALPHA.  The engine's textures are premultiplied (its shaders
add ``colorTransformAdd * fragmentColor.a``; scene textures are stored that
way), so ``pad_cp`` divides the alpha out, corrects, and multiplies it back
in: a soft edge keeps its colour.  A shader that is not of that family (the
debug overlay, the external-image sprite) is corrected as straight alpha.
Opaque pixels, the vast majority, come out the same either way.

WHY THE TEXT MOVES.  The corrected shader is longer than its slot, so the
original bytes are left alone and the new text goes into the game program's
extension segment (the same segment, header and relocation census longer
program text uses: :mod:`.progreloc`, ``engine._grow_program_text``), with
each reference retargeted at the copy.  References come in two shapes: an
absolute address (a pointer word, a movw/movt pair: the progreloc census)
and pc + a stored offset (the video player's sprite shader, on every title:
:func:`pcrel_census`).  Only references that point at the START of a shader
are moved; anything else (a look-alike word pointing into the middle of the
text) keeps the original, so the worst a missed or odd reference can do is
leave that one shader uncorrected.  Measured on all 57 Spike 2 card images
on hand: 8 of the 9 shaders corrected on each, the debug fill left alone.

A shader that has no ``precision`` statement (the solid red debug fill) is
left alone: a function needs a default float precision in a fragment
shader, and that one is never on a player's screen.
"""

import re

from . import progreloc

#: The statement the profile is spliced into: the LAST write of the colour.
_WRITE_RE = re.compile(r"gl_FragColor\s*=\s*([^;]+);")
_FUNC = "pad_cp"


def fragment_shaders(raw):
    """``[(file_off, text)]`` of every NUL-terminated GLSL fragment shader in
    the ELF *raw* (a string that writes ``gl_FragColor``)."""
    out = []
    seen = set()
    for m in re.finditer(rb"gl_FragColor", raw):
        s = raw.rfind(b"\x00", 0, m.start()) + 1
        e = raw.find(b"\x00", m.start())
        if e < 0 or s in seen:
            continue
        seen.add(s)
        try:
            text = raw[s:e].decode("ascii")
        except UnicodeDecodeError:
            continue
        if "void main" in text:
            out.append((s, text))
    return out


def _f(v):
    return "%.6f" % float(v)


def _v3(t):
    return "vec3(%s,%s,%s)" % tuple(_f(x) for x in t)


def correction_glsl(prof, premultiplied):
    """The ``pad_cp`` function for *prof* (a core.colour_profile.Profile)."""
    body = []
    if premultiplied:
        body.append("float a=f.a;vec3 c=clamp(f.rgb/max(a,0.0001),0.0,1.0);")
    else:
        body.append("float a=f.a;vec3 c=clamp(f.rgb,0.0,1.0);")
    if prof.saturation != 1.0:
        body.append("c=mix(vec3(dot(c,vec3(0.299,0.587,0.114))),c,%s);"
                    % _f(prof.saturation))
    body.append("c=pow(clamp(c*%s,0.0,1.0),%s);" % (_v3(prof.gain),
                                                   _v3(prof.gamma)))
    if any(prof.lift):
        lo = _v3(prof.lift)
        body.append("c=%s+(vec3(1.0)-%s)*c;" % (lo, lo))
    body.append("return vec4(c*a,a);" if premultiplied
                else "return vec4(c,a);")
    return "vec4 %s(vec4 f){%s}" % (_FUNC, "".join(body))


def _premultiplied(text):
    """Is *text* one of the engine's premultiplied-alpha shaders?"""
    return ("colorTransformAdd" in text) or ("colorTransformFont" in text) \
        or ("textureYSampler" in text)


def patch_source(text, prof):
    """*text* with the profile applied to its final colour, or ``None`` when
    it is not a shader this patches (no ``precision`` statement, no
    ``void main``, already patched)."""
    if "precision" not in text or _FUNC + "(" in text:
        return None
    main = text.find("void main")
    writes = list(_WRITE_RE.finditer(text))
    if main < 0 or not writes:
        return None
    w = writes[-1]
    if w.start() < main:
        return None
    expr = w.group(1).strip()
    body = (text[:w.start()] + "gl_FragColor = %s(%s);" % (_FUNC, expr)
            + text[w.end():])
    func = correction_glsl(prof, _premultiplied(text))
    sep = "\n" if "\n" in text[:main] else ""
    return body[:main] + func + sep + body[main:]


#: How far back from an ``add Rd, pc, Rm`` the ``ldr Rm, =offset`` may sit.
_PCREL_BACK = 16


def pcrel_census(raw, spans):
    """Position-independent references to *spans* (``[(file_off, text)]``):
    an ``ldr Rm, [pc, #imm]`` of a literal OFFSET, then ``add Rd, pc, Rm``
    a few instructions on, so the address is ``pc + offset`` and no word in
    the file holds it.  :func:`progreloc.reference_census` cannot see these;
    the video player's sprite shader is reached only this way on every Spike
    2 title on hand (one A32 site, ``SpiVideoPlayer``), which is why the
    first version left video uncorrected.

    Returns ``{span_off: [{"kind": "pcrel", "delta", "lit", "base"}]}`` where
    the literal at file offset *lit* holds ``target - base``."""
    import numpy as np
    segs = progreloc.load_segments(raw)
    off2va, va2off = progreloc.seg_maps(segs)
    targets = {}
    for off, text in spans:
        va = off2va(off)
        if va is not None:
            for k in range(len(text)):
                targets[va + k] = (off, k)
    out = {}
    if not targets:
        return out
    n = len(raw)
    for seg_va, seg_off, fs, _ms, fl in segs:
        if not fl & 1:
            continue
        lo = seg_off - seg_off % 4
        words = np.frombuffer(raw, dtype="<u4", count=(min(n, seg_off + fs) - lo) // 4,
                              offset=lo)
        # A32: add Rd, pc, Rm  =  cond 0000 100S 1111 dddd 0000 0000 mmmm
        for idx in np.nonzero((words & 0x0FEF0FF0) == 0x008F0000)[0]:
            i = lo + int(idx) * 4
            ins = int(words[idx])
            rm = ins & 0xF
            for back in range(1, _PCREL_BACK + 1):
                j = i - 4 * back
                if j < lo:
                    break
                w = int(words[idx - back])
                if (w & 0x0F7F0000) == 0x051F0000 and ((w >> 12) & 0xF) == rm:
                    imm = w & 0xFFF
                    lit = j + 8 + (imm if (w >> 23) & 1 else -imm)
                    if 0 <= lit <= n - 4:
                        base = off2va(i) + 8
                        lval = int.from_bytes(raw[lit:lit + 4], "little")
                        hit = targets.get((base + lval) & 0xFFFFFFFF)
                        if hit is not None:
                            out.setdefault(hit[0], []).append(
                                {"kind": "pcrel", "delta": hit[1],
                                 "lit": lit, "base": base})
                    break
                if ((w >> 12) & 0xF) == rm and (w & 0x0C000000) == 0:
                    break           # Rm rewritten by a data op: not this site
        # T32: add Rdn, pc (16-bit 0100 0100 D111 1ddd), ldr Rt,[pc,#imm8*4]
        hlo = lo
        halves = np.frombuffer(raw, dtype="<u2", count=(min(n, seg_off + fs) - hlo) // 2,
                               offset=hlo)
        for idx in np.nonzero((halves & 0xFF78) == 0x4478)[0]:
            i = hlo + int(idx) * 2
            h = int(halves[idx])
            rd = (h & 7) | ((h >> 4) & 8)
            for back in range(1, 2 * _PCREL_BACK + 1):
                if idx - back < 0:
                    break
                h2 = int(halves[idx - back])
                if (h2 & 0xF800) == 0x4800 and ((h2 >> 8) & 7) == rd:
                    j = i - 2 * back
                    lit_va = ((off2va(j) + 4) & ~3) + (h2 & 0xFF) * 4
                    lit = va2off(lit_va)
                    if lit is not None and 0 <= lit <= n - 4:
                        base = off2va(i) + 4
                        lval = int.from_bytes(raw[lit:lit + 4], "little")
                        hit = targets.get((base + lval) & 0xFFFFFFFF)
                        if hit is not None:
                            out.setdefault(hit[0], []).append(
                                {"kind": "pcrel", "delta": hit[1],
                                 "lit": lit, "base": base})
                    break
    return out


def _retarget(raw, ref, va):
    if ref["kind"] == "pcrel":
        return [(ref["lit"], ((va - ref["base"]) & 0xFFFFFFFF).to_bytes(
            4, "little"))]
    return progreloc.retarget_writes(raw, ref, va)


def plan(raw, prof, base_va):
    """Where every patched shader goes and what to rewrite.

    *base_va* is the virtual address the blob will start at (the extension
    segment's base + its first free offset).  Returns ``(file_writes, blob,
    report)``: *file_writes* the ``[(file_off, bytes)]`` reference rewrites,
    *blob* the NUL-terminated new shader texts back to back, *report* a list
    of ``(file_off, n_refs_moved, n_refs_left, what)`` per shader, for the
    log.  A shader with no reference at its start is not placed at all.
    References are the absolute ones :func:`progreloc.reference_census`
    finds and the position-independent ones :func:`pcrel_census` finds."""
    shaders = fragment_shaders(raw)
    census = progreloc.reference_census(raw, shaders) if shaders else {}
    pcrel = pcrel_census(raw, shaders) if shaders else {}
    writes, blob, report = [], bytearray(), []
    for off, text in shaders:
        new = patch_source(text, prof)
        if new is None:
            report.append((off, 0, 0, "left alone"))
            continue
        refs = (census.get(off) or []) + (pcrel.get(off) or [])
        head = [r for r in refs if r["delta"] == 0]
        if not head:
            report.append((off, 0, len(refs), "no reference found"))
            continue
        va = base_va + len(blob)
        for r in head:
            writes += _retarget(raw, r, va)
        blob += new.encode("ascii") + b"\x00"
        while len(blob) % 4:
            blob += b"\x00"
        report.append((off, len(head), len(refs) - len(head), "corrected"))
    return writes, bytes(blob), report


def describe(report):
    """One log sentence for :func:`plan`'s report."""
    done = [r for r in report if r[3] == "corrected"]
    left = [r for r in report if r[3] != "corrected"]
    return ("%d of the game's %d drawing shaders carry the color profile"
            % (len(done), len(report))
            + ("; %d left as they are (%s)" % (len(left), ", ".join(
                "0x%x %s" % (r[0], r[3]) for r in left)) if left else ""))
