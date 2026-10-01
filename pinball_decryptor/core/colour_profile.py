"""Colour profile: a colour correction applied to the user's replacement
pictures and videos as a build writes them, never to the files themselves
(PAD-305).

WHY.  A machine's display is not the PC monitor the art was made on.
DragonRR photographed a display test card on a Stern Godzilla: mid greys come
out far too bright and blue, saturated patches bloom, and everything under
about 24/255 sinks into one lifted black.  Art that looks right on the PC
looks washed out and blue on the cabinet.  A profile pre-corrects for that:
the PC copy stays the "golden" asset, and only what goes onto the card is
bent so the machine shows what the PC shows.

WHERE IT APPLIES.  Only at staging, the step every Write / Build (and the
Emulate tab's "apply my replaced assets") runs to turn the user's own files
into the project folder's slot files, plus a scene's added picture as the
build encodes it.  Each of those reads the user's untouched source every
time, so the profile can never land twice on one asset, and switching it off
and building again gives the uncorrected card back.  Stock assets are never
touched: the stock art was made for the machine already.

THE MATHS, kept identical between Pillow (pictures) and ffmpeg (videos):

1. saturation: each pixel mixed toward its own Rec.601 grey by
   ``saturation`` (1 = unchanged, 0 = greyscale).  Pillow's
   ``convert("RGB", matrix)`` and ffmpeg's ``colorchannelmixer`` take the
   same 3x3 matrix.
2. per channel: ``out = lift + (1 - lift) * clip(in * gain) ** gamma`` on a
   0..1 scale.  Gamma above 1 darkens the mid tones (the machine shows them
   too bright), gain below 1 pulls a channel down overall, lift raises the
   darkest values.  Pillow uses the table, ffmpeg's ``lutrgb`` the same
   expression.

THE FILE is plain ``key = value`` text in the settings folder, created from
:data:`DEFAULT_TEXT` the first time it is wanted, so a user can edit it in
any text editor and keep a copy per machine.  Unknown keys and bad values
are ignored (named by :func:`problems`), never fatal: a typo must not stop a
build.

The Write tab's tick turns it on; the choice is mirrored to
``PAD_COLOUR_PROFILE`` ("1" / "0") like the other build options, so the
worker threads and the emulator's override build see it without a new
parameter through every signature.
"""

import contextlib
import os
import threading
from dataclasses import dataclass

from .config import _settings_root

#: Env var the Write tab's tick is mirrored into ("1" = apply).
ENV = "PAD_COLOUR_PROFILE"
#: Env var naming a profile file other than the default (tests, power users).
ENV_FILE = "PAD_COLOUR_PROFILE_FILE"
FILE_NAME = "colour_profile.txt"

#: Rec.601 luma weights: the grey a pixel is desaturated toward.
_LUMA = (0.299, 0.587, 0.114)

#: The profile a new file starts from: Stern Godzilla, read off DragonRR's
#: photographs of his display test card on the machine (PAD-305).  The
#: machine showed 128 grey as roughly (164, 187, 226) and 64 as (100, 113,
#: 148): mids far too bright, most of all in blue, then green, while white
#: stayed white.  Darkening each channel's mids by its own gamma (and a touch
#: less colour) is the pre-correction; a phone photo is not a colour meter,
#: so this is a starting point to tune against the test card, not a
#: calibration.
DEFAULT_TEXT = """\
# Pinball Asset Decryptor colour profile
#
# Applied to YOUR replacement pictures and videos as a build writes them to
# the card, when "Apply colour profile" is ticked on the Write tab.  Your own
# files are never changed, and stock art is never touched.
#
# Edit the numbers, save, and build again.  Three numbers = red green blue.
#
#   gamma       above 1 darkens the mid tones, below 1 brightens them
#   gain        multiplies the channel (0.9 = 10% less of that colour)
#   lift        raises the darkest values (0.05 = black becomes 13 of 255)
#   saturation  1 = unchanged, below 1 = less colour, above 1 = more
#
# Starting point: Stern Godzilla, from photos of a display test card on the
# machine (its mids show too bright and too blue).

name = Godzilla (Stern Spike 2)
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


def profile_path():
    return os.environ.get(ENV_FILE) or os.path.join(_settings_root(),
                                                     FILE_NAME)


def ensure_file():
    """The profile file's path, written from :data:`DEFAULT_TEXT` first if
    it is not there yet."""
    path = profile_path()
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(DEFAULT_TEXT)
    return path


def load():
    """``(Profile, problems)`` from the file (created when missing)."""
    try:
        with open(ensure_file(), encoding="utf-8-sig") as f:
            return parse(f.read())
    except OSError as e:
        prof, _ = parse(DEFAULT_TEXT)
        return prof, ["could not read %s (%s); using the default"
                      % (profile_path(), e)]


def enabled():
    return os.environ.get(ENV, "0") == "1"


def set_enabled(on):
    os.environ[ENV] = "1" if on else "0"


#: The emulator's "stock colours" switch (PAD-305): when not None it wins
#: over the env for as long as :func:`forced` holds it.  Module-wide rather
#: than per thread, because the engine fans some of an override build out to
#: a thread pool; the Emulate tab only holds it around its own preparation.
_FORCED = None
_FORCED_LOCK = threading.Lock()


@contextlib.contextmanager
def forced(on):
    """Within the block, :func:`active` answers as if the tick were *on*
    (``None`` leaves it to the tick).  The Emulate tab's "stock colours"
    switch runs its staging and override build under ``forced(False)``."""
    global _FORCED
    with _FORCED_LOCK:
        prev, _FORCED = _FORCED, on
    try:
        yield
    finally:
        with _FORCED_LOCK:
            _FORCED = prev


def active():
    """The profile a build should apply now, or None (off, or a profile that
    changes nothing)."""
    on = enabled() if _FORCED is None else bool(_FORCED)
    if not on:
        return None
    prof, _ = load()
    return None if prof.is_identity() else prof


def signature():
    """A short text that changes whenever what :func:`active` would apply
    changes ("" when nothing): an emulator override set records it so a
    switched or edited profile rebuilds the set rather than reusing it."""
    prof = active()
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


def save(prof, path=None):
    """Write *prof* to *path* (the active profile file by default)."""
    path = path or profile_path()
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


#: Starting points the Color profile tab offers.
PRESETS = (
    ("godzilla", parse(DEFAULT_TEXT)[0]),
    ("none", Profile(name="No change")),
)
