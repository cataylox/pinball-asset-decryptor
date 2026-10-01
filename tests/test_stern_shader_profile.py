"""PAD-305: the color profile applied to everything a Spike 2 game draws, by
patching the drawing shaders in the game program (plugins/stern/shader_profile.py).

The shaders here are written in the SHAPE of the engine's (premultiplied
sprite, YUV video, a straight-alpha overlay, a precision-less debug fill),
not copied from a card.  The ELF is the same tiny synthetic one
test_stern_progreloc.py builds: one PT_LOAD over the file, a pointer word to
each shader in it."""

import struct

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.plugins.stern import progreloc as pr
from pinball_decryptor.plugins.stern import shader_profile as sp

from tests.test_stern_progreloc import BODY_OFF, VBASE, _elf

SPRITE = ("precision highp float;varying vec2 uv;uniform sampler2D tex;"
          "uniform vec4 colorTransformMultiply;uniform vec4 colorTransformAdd;"
          "void main(){vec4 c = texture2D(tex, uv);"
          "c = clamp(c + (colorTransformAdd * c.a), 0.0, 1.0);"
          "gl_FragColor = c;}")
VIDEO = ("precision highp float;varying vec2 uv;uniform sampler2D textureYSampler;"
         "void main(){float y = texture2D(textureYSampler, uv).r;"
         "gl_FragColor = vec4(y, y, y, 1.0);}")
OVERLAY = ("#version 100\nprecision mediump float;\nuniform sampler2D T;\n"
           "varying vec2 uv;\nvarying vec4 col;\n"
           "void main(){\n   gl_FragColor = col * texture2D(T, uv);\n}\n")
DEBUG = "void main(){gl_FragColor = vec4(255.0, 0.0, 0.0, 255.0);}"
PROF = dict(cp.PRESETS)["recommended"]


def _card_elf(shaders, unreferenced=()):
    """A synthetic game program holding *shaders* (each NUL-terminated,
    word-aligned) and, after them, one pointer word per shader (none for the
    indices in *unreferenced*)."""
    body = bytearray(b"\x00" * 16)
    offs = []
    for s in shaders:
        offs.append(BODY_OFF + len(body))
        body += s.encode() + b"\x00"
        body += b"\x00" * (-len(body) % 4)
    ptrs = []
    for i, off in enumerate(offs):
        if i in unreferenced:
            continue
        ptrs.append(BODY_OFF + len(body))
        body += struct.pack("<I", VBASE + off)
    return _elf(bytes(body)), offs, ptrs


def test_finds_every_fragment_shader():
    raw, offs, _p = _card_elf([SPRITE, VIDEO, OVERLAY, DEBUG])
    found = sp.fragment_shaders(raw)
    assert [o for o, _t in found] == offs
    assert found[1][1] == VIDEO


def test_patch_wraps_the_last_colour_write_and_defines_the_function_first():
    new = sp.patch_source(SPRITE, PROF)
    assert new.endswith("gl_FragColor = pad_cp(c);}")
    assert new.index("vec4 pad_cp(vec4 f)") < new.index("void main")
    assert new.index("precision highp float;") < new.index("vec4 pad_cp")
    # the profile's numbers are baked in, the way GLSL ES wants floats
    assert "vec3(1.100000,1.200000,1.350000)" in new
    assert "0.900000" in new                      # colour strength
    # untouched apart from the splice
    assert new.replace(sp.correction_glsl(PROF, True), "").replace(
        "pad_cp(c)", "c") == SPRITE


def test_premultiplied_shaders_divide_the_alpha_out_and_back_in():
    assert "f.rgb/max(a,0.0001)" in sp.patch_source(SPRITE, PROF)
    assert "return vec4(c*a,a);" in sp.patch_source(VIDEO, PROF)
    straight = sp.patch_source(OVERLAY, PROF)
    assert "f.rgb/max" not in straight and "return vec4(c,a);" in straight
    assert "gl_FragColor = pad_cp(col * texture2D(T, uv));" in straight


def test_debug_fill_and_an_already_patched_shader_are_left_alone():
    assert sp.patch_source(DEBUG, PROF) is None
    assert sp.patch_source(sp.patch_source(SPRITE, PROF), PROF) is None


def test_black_and_white_and_lift_reach_the_glsl():
    bw = sp.correction_glsl(dict(cp.PRESETS)["bw"], True)
    assert "dot(c,vec3(0.299,0.587,0.114))),c,0.000000)" in bw
    lifted = sp.correction_glsl(cp.Profile(lift=(0.05, 0.05, 0.05)), True)
    assert "vec3(0.050000,0.050000,0.050000)+" in lifted
    plain = sp.correction_glsl(cp.Profile(gamma=(1.2, 1.2, 1.2)), False)
    assert "mix(" not in plain                    # strength 100%: no mix


def test_plan_moves_each_referenced_shader_and_repoints_it():
    raw, offs, ptrs = _card_elf([SPRITE, VIDEO, OVERLAY, DEBUG],
                                unreferenced=())
    base = 0x40000
    writes, blob, report = sp.plan(raw, PROF, base)
    assert [r[3] for r in report] == ["corrected", "corrected", "corrected",
                                      "left alone"]
    buf = bytearray(raw)
    for off, b in writes:
        buf[off:off + len(b)] = b
    # three pointers moved into the blob, the debug fill's kept
    for i, p in enumerate(ptrs):
        va = struct.unpack_from("<I", buf, p)[0]
        if i == 3:
            assert va == VBASE + offs[3]
            continue
        start = va - base
        text = blob[start:blob.index(b"\x00", start)].decode()
        assert text == sp.patch_source([SPRITE, VIDEO, OVERLAY][i], PROF)
        assert start % 4 == 0
    # the original shaders are untouched
    assert bytes(buf[offs[0]:offs[0] + len(SPRITE)]) == SPRITE.encode()


def test_a_shader_with_no_visible_reference_stays_as_it_is():
    raw, _offs, _p = _card_elf([SPRITE, VIDEO], unreferenced=(1,))
    _w, blob, report = sp.plan(raw, PROF, 0x40000)
    assert [r[3] for r in report] == ["corrected", "no reference found"]
    assert b"textureYSampler" not in blob
    assert "1 left as they are" in sp.describe(report)


def test_spike2_holds_the_file_correction_off_and_others_keep_it():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    m = SternManufacturer()
    assert m.colour_profile_on_display() is True
    m.set_era("spike1")
    assert m.colour_profile_on_display() is False
