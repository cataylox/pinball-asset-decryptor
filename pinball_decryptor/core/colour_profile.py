"""Colour profile: the colour correction a project's build applies for the
machine's screen (PAD-305).

WHY.  A machine's display is not the PC monitor the art was made on.
A field report photographed a display test card on a Stern Godzilla: mid greys come
out far too bright and blue, saturated patches bloom, and everything under
about 24/255 sinks into one lifted black.  A profile pre-corrects for that:
the PC copy stays the "golden" asset, and only what the machine is given is
bent so it shows what the PC shows.

A STAGED CHANGE OF THE PROJECT, like every other Replace tab's: the Color
profile tab records the project's profile in its ``.staged_changes.json``
(:data:`KEY`), the Write tab lists it as pending, the next build or Emulate
Start applies it, and Revert all clears it.  No profile (or one that changes
nothing) is the "off" state; there is no separate switch.

WHERE IT APPLIES.  On Spike 2, in the game's own drawing shaders
(plugins/stern/shader_profile.py): everything on the screen, no file touched.
Elsewhere, at staging, to the user's replacement pictures and videos (the
only thing PAD can reach there), each read from the user's untouched source
every time, so it can never land twice.

THE MATHS, kept identical between Pillow (pictures), ffmpeg (videos) and the
GLSL the shaders get:

1. saturation: each pixel mixed toward its own Rec.601 grey by
   ``saturation`` (1 = unchanged, 0 = greyscale).
2. per channel: ``out = lift + (1 - lift) * clip(in * gain) ** gamma`` on a
   0..1 scale.  Gamma above 1 darkens the mid tones (the machine shows them
   too bright), gain below 1 pulls a channel down overall, lift raises the
   darkest values.

A COPY is plain ``key = value`` text (:func:`to_text`, :func:`read_file`), so
a user can keep one per machine, share it, or edit it in any text editor and
Load it back.  Unknown keys and bad values are skipped and named, never fatal.
"""

import contextlib
import threading
from dataclasses import dataclass

#: The project's profile in its ``.staged_changes.json``.
KEY = "color_profile"

#: Rec.601 luma weights: the grey a pixel is desaturated toward.
_LUMA = (0.299, 0.587, 0.114)

#: The profile a new file starts from: Stern Godzilla, read off a field
#: report's photographs of a display test card on the machine (PAD-305).  The
#: machine showed 128 grey as roughly (164, 187, 226) and 64 as (100, 113,
#: 148): mids far too bright, most of all in blue, then green, while white
#: stayed white.  Darkening each channel's mids by its own gamma (and a touch
#: less colour) is the pre-correction; a phone photo is not a colour meter,
#: so this is a starting point to tune against the test card, not a
#: calibration.
DEFAULT_TEXT = """\
# Pinball Asset Decryptor colour profile
#
# Corrects colors for a pinball machine's screen.  Load it on a project's
# Color profile tab and every build of that project applies it (on Spike 2,
# to everything the game draws).  No picture or video file is changed.
#
# Edit the numbers, save, and Load it again.  Three numbers = red green blue.
#
#   gamma       above 1 darkens the mid tones, below 1 brightens them
#   gain        multiplies the channel (0.9 = 10% less of that colour)
#   lift        raises the darkest values (0.05 = black becomes 13 of 255)
#   saturation  1 = unchanged, below 1 = less colour, above 1 = more
#
# "Recommended": made from photos of a display test card on a Stern Spike 2
# machine (a Godzilla), whose middle shades show too bright and too blue.

name = Recommended
gamma = 1.10 1.20 1.35
gain = 1.00 1.00 1.00
lift = 0.00 0.00 0.00
saturation = 0.90
"""


@dataclass(frozen=True)
class Profile:
    name: str = ""
    gamma: tuple = (1.0, 1.0, 1.0)
    gain: tuple = (1.0, 1.0, 1.0)
    lift: tuple = (0.0, 0.0, 0.0)
    saturation: float = 1.0

    def is_identity(self):
        return (self.gamma == (1.0, 1.0, 1.0) and self.gain == (1.0, 1.0, 1.0)
                and self.lift == (0.0, 0.0, 0.0) and self.saturation == 1.0)

    def label(self):
        return self.name or "colour profile"

    # -- the maths ----------------------------------------------------------
    def matrix(self):
        """The 3x3 saturation matrix, row-major (out_r = row 0 . rgb)."""
        s = self.saturation
        rows = []
        for i in range(3):
            rows.append(tuple((1 - s) * _LUMA[j] + (s if i == j else 0.0)
                              for j in range(3)))
        return tuple(rows)

    def table(self, channel):
        """256 output values for input 0..255 on *channel* (0 r, 1 g, 2 b)."""
        g, k, lo = self.gamma[channel], self.gain[channel], self.lift[channel]
        out = []
        for v in range(256):
            x = min(max(v / 255.0 * k, 0.0), 1.0)
            y = lo + (1.0 - lo) * (x ** g)
            out.append(int(min(max(y * 255.0 + 0.5, 0), 255)))
        return out

    def ffmpeg_filters(self):
        """The same correction as ffmpeg filters, in order."""
        out = []
        if self.saturation != 1.0:
            m = self.matrix()
            names = ("r", "g", "b")
            out.append("colorchannelmixer=" + ":".join(
                "%s%s=%.6f" % (names[i], names[j], m[i][j])
                for i in range(3) for j in range(3)))
        exprs = []
        for i, ch in enumerate(("r", "g", "b")):
            g, k, lo = self.gamma[i], self.gain[i], self.lift[i]
            if g == 1.0 and k == 1.0 and lo == 0.0:
                continue
            # commas inside an option are escaped for the filtergraph parser
            exprs.append(
                "%s=%.6f*255+%.6f*pow(clip(val*%.6f/255\\,0\\,1)\\,%.6f)*255+0.5"
                % (ch, lo, 1.0 - lo, k, g))
        if exprs:
            out.append("lutrgb=" + ":".join(exprs))
        return out

    def apply_image(self, im):
        """*im* (any Pillow mode) corrected; alpha passes through untouched.
        Returns a new RGB or RGBA image."""
        from PIL import Image
        alpha = None
        if im.mode in ("RGBA", "LA", "PA") or (
                im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            alpha = im.getchannel("A")
            rgb = im.convert("RGB")
        else:
            rgb = im.convert("RGB")
        if self.saturation != 1.0:
            m = self.matrix()
            rgb = rgb.convert("RGB", m[0] + (0.0,) + m[1] + (0.0,)
                              + m[2] + (0.0,))
        rgb = rgb.point(self.table(0) + self.table(1) + self.table(2))
        if alpha is not None:
            rgb.putalpha(alpha)
        return rgb if alpha is not None else rgb.convert("RGB")


def _numbers(text, n):
    vals = [float(t) for t in text.replace(",", " ").split()]
    if len(vals) == 1 and n == 3:
        vals = vals * 3
    if len(vals) != n:
        raise ValueError("needs %d number%s" % (n, "" if n == 1 else "s"))
    return tuple(vals)


def parse(text):
    """``(Profile, [problem, ...])`` from the file's text.  A bad line is
    skipped and named; it never raises."""
    fields = {}
    problems = []
    limits = {"gamma": (0.1, 5.0), "gain": (0.0, 4.0), "lift": (0.0, 0.9),
              "saturation": (0.0, 4.0)}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, sep, val = line.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if not sep:
            problems.append("line %d: no '=' (%s)" % (n, raw.strip()))
            continue
        if key == "name":
            fields["name"] = val
            continue
        if key not in limits:
            problems.append("line %d: unknown setting '%s'" % (n, key))
            continue
        try:
            nums = _numbers(val, 1 if key == "saturation" else 3)
        except ValueError as e:
            problems.append("line %d: %s %s" % (n, key, e))
            continue
        lo, hi = limits[key]
        if any(not (lo <= v <= hi) for v in nums):
            problems.append("line %d: %s must be between %g and %g"
                            % (n, key, lo, hi))
            continue
        fields[key] = nums[0] if key == "saturation" else nums
    return Profile(**fields), problems


def _from_dict(d):
    try:
        return Profile(name=str(d.get("name") or ""),
                       gamma=tuple(float(v) for v in d["gamma"])[:3],
                       gain=tuple(float(v) for v in d["gain"])[:3],
                       lift=tuple(float(v) for v in d["lift"])[:3],
                       saturation=float(d["saturation"]))
    except (KeyError, TypeError, ValueError):
        return None


def for_project(assets_dir):
    """The profile staged for *assets_dir*, or ``None`` (none staged)."""
    from . import staged_changes
    d = staged_changes.load(assets_dir).get(KEY)
    return _from_dict(d) if isinstance(d, dict) else None


def store(assets_dir, prof):
    """Stage *prof* for *assets_dir*; ``None`` (or a profile that changes
    nothing) takes it away."""
    from . import staged_changes
    data = staged_changes.load(assets_dir)
    if prof is None or prof.is_identity():
        data.pop(KEY, None)
    else:
        data[KEY] = {"name": prof.name, "gamma": list(prof.gamma),
                     "gain": list(prof.gain), "lift": list(prof.lift),
                     "saturation": prof.saturation}
    staged_changes.save(assets_dir, data)


#: The emulator's "stock colours" switch: when not None it wins over the
#: project's profile for as long as :func:`forced` holds it.  Module-wide
#: rather than per thread, because the engine fans some of an override build
#: out to a thread pool; the Emulate tab only holds it around its own
#: preparation, and Spike 2 staging around its file staging.
_FORCED = None
_FORCED_LOCK = threading.Lock()


@contextlib.contextmanager
def forced(on):
    """Within the block, :func:`active` answers ``None`` when *on* is False
    (``None`` leaves it to the project)."""
    global _FORCED
    with _FORCED_LOCK:
        prev, _FORCED = _FORCED, on
    try:
        yield
    finally:
        with _FORCED_LOCK:
            _FORCED = prev


def active(assets_dir):
    """The profile a build of *assets_dir* applies now, or ``None``."""
    if _FORCED is False:
        return None
    prof = for_project(assets_dir)
    return None if prof is None or prof.is_identity() else prof


def signature(assets_dir):
    """A short text that changes whenever what :func:`active` would apply
    changes ("" when nothing): an emulator override set records it so a
    changed or held-off profile rebuilds the set rather than reusing it."""
    prof = active(assets_dir)
    if prof is None:
        return ""
    return "%s|%s|%s|%s" % (prof.gamma, prof.gain, prof.lift, prof.saturation)


def _fmt(nums):
    return " ".join("%.2f" % v for v in nums)


def to_text(prof):
    """The file text for *prof*: the explanatory header, then its values."""
    head = DEFAULT_TEXT.split("\nname =", 1)[0]
    return ("%s\nname = %s\ngamma = %s\ngain = %s\nlift = %s\n"
            "saturation = %.2f\n" % (head, prof.name or "My profile",
                                     _fmt(prof.gamma), _fmt(prof.gain),
                                     _fmt(prof.lift), prof.saturation))


def save(prof, path):
    """Write *prof* to the text file *path* (Save a copy)."""
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(to_text(prof))
    os.replace(tmp, path)
    return path


def read_file(path):
    """``(Profile, problems)`` from any profile file (Load...)."""
    with open(path, encoding="utf-8-sig") as f:
        return parse(f.read())


#: Starting points the Color profile tab offers.  The first is the default
#: profile, named "Recommended" in the tab (it was measured on a Godzilla,
#: but nothing in it is Godzilla's own: it is the display that it corrects).
PRESETS = (
    ("recommended", parse(DEFAULT_TEXT)[0]),
    ("none", Profile(name="No change")),
    # Black-and-white playfield editions (EHoH, Godzilla): every picture as
    # its own grey (Rec.601 luma), nothing else changed.
    ("bw", Profile(name="Black and white", saturation=0.0)),
)

#: The tab's tooltip for each starting point: how it was made.
PRESET_TIPS = {
    "recommended": (
        "Made from photos of a display test card on a real Stern Spike 2 "
        "machine (a Godzilla). The card's grey steps and color patches "
        "were measured in the photos: a mid grey (128, 128, 128) came out "
        "around (164, 187, 226), far too bright and most of all in blue, "
        "then green, while white stayed white. This profile darkens each "
        "color's middle shades to pull that back (red 10%, green 20%, blue "
        "35% darker) and calms colors a little (90% strength). A phone "
        "photo is not a color meter, so treat it as a starting point and "
        "tune it against your own machine."),
    "none": "Leaves every color as you made it.",
    "bw": ("Every picture and video in greys, for a black-and-white "
           "playfield edition. Nothing else is changed."),
}
