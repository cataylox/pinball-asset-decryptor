"""The Color profile tab (PAD-305): the colour correction a build applies to
the user's replacement pictures and videos so the machine's display shows
them the way the PC does.

The maths, the file and where a build applies it are core/colour_profile.py.
This service holds the switch (settings.json ``colour_profile``, mirrored to
``PAD_COLOUR_PROFILE`` by the app), the profile's numbers (saved to the
profile file on every change, so the file stays the one source a build
reads), the presets, Save a copy / Load for keeping one profile per machine,
and the picture the page previews them on.

The PREVIEW is drawn by the page itself (static/js/tabs/color.js) with the
same maths, so a slider moves the picture as it is dragged; this side only
says which picture: a test card PAD draws, or one of the user's own.
"""

import base64
import io
import logging
import os

from .base import TabService, rpc
from ...core import colour_profile as cp

log = logging.getLogger(__name__)

#: limits of the page's controls; the file accepts a wider range (parse())
LIMITS = {"gamma": (0.5, 2.5), "gain": (0.5, 1.5), "lift": (0.0, 0.3),
          "saturation": (0.0, 2.0)}

_CARD_CACHE = []


def test_card_png():
    """A small display test card (grey steps, full and half colours, dark
    sea tones, a smooth ramp and skin tones): the shades a display gets
    wrong first.  Drawn here, so it ships with nothing of anyone else's."""
    if _CARD_CACHE:
        return _CARD_CACHE[0]
    from PIL import Image, ImageDraw
    w, h = 640, 400
    im = Image.new("RGB", (w, h), (24, 24, 24))
    d = ImageDraw.Draw(im)
    x0, cw = 16, (w - 32)
    greys = [0, 8, 16, 24, 32, 48, 64, 80, 96, 112, 128, 160, 192, 224, 240,
             255]
    step = cw / len(greys)
    for i, v in enumerate(greys):
        d.rectangle([x0 + i * step, 16, x0 + (i + 1) * step - 1, 76],
                    fill=(v, v, v))
    full = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 255, 255),
            (255, 0, 255), (255, 255, 0)]
    step = cw / len(full)
    for i, c in enumerate(full):
        half = tuple(v // 2 for v in c)
        d.rectangle([x0 + i * step, 88, x0 + (i + 1) * step - 1, 138], fill=c)
        d.rectangle([x0 + i * step, 140, x0 + (i + 1) * step - 1, 190],
                    fill=half)
    sea = [(8, 24, 40), (8, 32, 56), (12, 48, 80), (16, 64, 104),
           (24, 80, 128), (32, 96, 152)]
    skin = [(255, 224, 196), (234, 192, 160), (198, 145, 110),
            (160, 105, 75), (110, 70, 50), (70, 45, 32)]
    for row, (y, colours) in enumerate(((202, sea), (254, skin))):
        step = cw / len(colours)
        for i, c in enumerate(colours):
            d.rectangle([x0 + i * step, y, x0 + (i + 1) * step - 1, y + 48],
                        fill=c)
    for x in range(cw):
        v = round(x * 255 / (cw - 1))
        d.line([x0 + x, 314, x0 + x, 384], fill=(v, v, v))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    _CARD_CACHE.append("data:image/png;base64,"
                       + base64.b64encode(buf.getvalue()).decode())
    return _CARD_CACHE[0]


def _clamp(key, v):
    lo, hi = LIMITS[key]
    return min(max(float(v), lo), hi)


class ColorTab(TabService):
    ns = "color"
    key = "Color Profile"
    label = "Color profile"
    group = "Replace"
    icon = "palette"
    exports = ("colour_profile_enabled",)

    def __init__(self, window):
        super().__init__(window)
        cb = window.cb
        self.enabled_var = self.var(
            "enabled", "bool", bool(cb.get("initial_colour_profile")))
        self.enabled_var.trace_add("write", lambda *_a: self._on_enabled())
        self._prof = None
        self._rev = 0
        self._sample = "card"
        self.set(sample="card", sample_url="", sample_path="", samples=[],
                 problems=[], rev=0)

    # -- the switch --------------------------------------------------------
    def colour_profile_enabled(self):
        try:
            return bool(self.enabled_var.get())
        except Exception:                               # noqa: BLE001
            return False

    @rpc
    def set_enabled(self, on):
        self.enabled_var.set(bool(on))
        return True

    def _on_enabled(self):
        fn = self.window.cb.get("on_colour_profile_change")
        if fn is not None:
            try:
                fn(self.colour_profile_enabled())
            except Exception:                           # noqa: BLE001
                log.exception("colour profile change")
        else:
            cp.set_enabled(self.colour_profile_enabled())
        # the Write and Emulate tabs say whether it is on
        for ns in ("write", "emulate"):
            svc = self.window.service(ns)
            fn = getattr(svc, "_refresh_colour_note", None)
            if fn is not None:
                try:
                    fn()
                except Exception:                       # noqa: BLE001
                    log.exception("colour note %s", ns)
        self._tell_emulator()

    def _tell_emulator(self):
        """A game running on this project's edits gets the change live
        (Emulate tab, PAD-305).  Not on every slider move: each one would
        rebuild the set; a switch, a starting point or a Load does."""
        emu = self.window.service("emulate")
        fn = getattr(emu, "colour_live", None)
        if fn is not None:
            try:
                fn()
            except Exception:                           # noqa: BLE001
                log.exception("colour live")

    # -- the profile -------------------------------------------------------
    def _load(self):
        prof, problems = cp.load()
        self._prof = prof
        self._rev += 1
        self._publish(problems)

    def _publish(self, problems=None):
        p = self._prof or cp.load()[0]
        values = dict(
            name=p.name, gamma=list(p.gamma), gain=list(p.gain),
            lift=max(p.lift), saturation=p.saturation, rev=self._rev,
            path=cp.profile_path(),
            presets=[{"key": k, "label": v.name} for k, v in cp.PRESETS],
            limits={k: list(v) for k, v in LIMITS.items()})
        if problems is not None:
            values["problems"] = list(problems)
        self.set(**values)

    def _store(self, prof, rev=False):
        self._prof = prof
        try:
            cp.save(prof)
        except OSError as e:
            self.set(problems=["could not save %s (%s)" % (cp.profile_path(),
                                                           e)])
            return False
        if rev:
            self._rev += 1
        self._publish(problems=[])
        return True

    @rpc
    def set_params(self, params):
        """The page's sliders: any of name, gamma [r g b], gain [r g b],
        lift (one number, all three), saturation."""
        p = self._prof or cp.load()[0]
        kw = dict(name=p.name, gamma=p.gamma, gain=p.gain, lift=p.lift,
                  saturation=p.saturation)
        params = params or {}
        if "name" in params:
            kw["name"] = str(params["name"] or "").strip()[:60]
        for key in ("gamma", "gain"):
            if key in params:
                kw[key] = tuple(round(_clamp(key, v), 3)
                                for v in list(params[key])[:3])
        if "lift" in params:
            v = round(_clamp("lift", params["lift"]), 3)
            kw["lift"] = (v, v, v)
        if "saturation" in params:
            kw["saturation"] = round(_clamp("saturation",
                                            params["saturation"]), 3)
        return self._store(cp.Profile(**kw))

    @rpc
    def preset(self, key):
        for k, prof in cp.PRESETS:
            if k == key:
                ok = self._store(prof, rev=True)
                self._tell_emulator()
                return ok
        return False

    @rpc
    def reload(self):
        self._load()
        return True

    @rpc
    def save_copy(self):
        p = self._prof or cp.load()[0]
        stem = "".join(c if c.isalnum() or c in "-_ " else "_"
                       for c in (p.name or "profile")).strip() or "profile"
        path = self.window.ask_save(
            "colour_profile", "Save a copy of this color profile",
            initialfile=stem + ".txt", defaultextension=".txt",
            filetypes=[("Color profile", "*.txt"), ("All files", "*.*")])
        if not path:
            return False
        try:
            cp.save(p, path)
        except OSError as e:
            self.toast("Could not save the profile: %s" % e, "error")
            return False
        self.toast("Saved %s" % os.path.basename(path), "success")
        return True

    @rpc
    def load_file(self):
        path = self.window.ask_open(
            "colour_profile", "Load a color profile",
            filetypes=[("Color profile", "*.txt"), ("All files", "*.*")])
        if not path:
            return False
        try:
            prof, problems = cp.read_file(path)
        except OSError as e:
            self.toast("Could not read the profile: %s" % e, "error")
            return False
        self._store(prof, rev=True)
        self._tell_emulator()
        if problems:
            self.set(problems=list(problems))
        self.toast("Loaded %s" % (prof.name or os.path.basename(path)),
                   "success")
        return True

    @rpc
    def open_text(self):
        from ..shellx_common import open_in_text_viewer
        try:
            open_in_text_viewer(cp.ensure_file())
        except OSError as e:
            self.toast("Could not open the profile: %s" % e, "error")
            return False
        return True

    # -- the preview picture -----------------------------------------------
    def _assets(self):
        var = getattr(self.window, "write_assets_var", None)
        try:
            return (var.get() or "").strip() if var is not None else ""
        except Exception:                               # noqa: BLE001
            return ""

    def _replacement_pictures(self):
        """``[(label, path)]`` of the pictures the user has assigned on the
        Images tab of this project, for the preview's picker."""
        assets = self._assets()
        if not assets or not os.path.isdir(assets):
            return []
        try:
            from ...core import staged_changes
            saved = staged_changes.load(assets).get("image") or {}
        except Exception:                               # noqa: BLE001
            return []
        out, seen = [], set()
        for rel, path in sorted(saved.items()):
            if (isinstance(path, str) and os.path.isfile(path)
                    and path not in seen):
                seen.add(path)
                out.append((os.path.basename(path), path))
        return out[:60]

    def _publish_sample(self):
        mine = self._replacement_pictures()
        opts = [{"value": "card", "label": "Test card"}]
        opts += [{"value": p, "label": "Mine: %s" % label}
                 for label, p in mine]
        if self._sample not in ("card",) and not any(
                o["value"] == self._sample for o in opts):
            if os.path.isfile(self._sample):
                opts.append({"value": self._sample, "label": os.path.basename(
                    self._sample)})
            else:
                self._sample = "card"
        self.set(samples=opts, sample=self._sample,
                 sample_url=test_card_png() if self._sample == "card" else "",
                 sample_path="" if self._sample == "card" else self._sample)

    @rpc
    def pick_sample(self, value):
        if value == "browse":
            path = self.window.ask_open(
                "colour_profile_sample", "Preview the profile on a picture",
                filetypes=[("Pictures", "*.png *.jpg *.jpeg *.webp *.bmp"),
                           ("All files", "*.*")])
            if not path:
                self._publish_sample()
                return False
            value = path
        self._sample = value or "card"
        self._publish_sample()
        return True

    # -- hooks ---------------------------------------------------------------
    def rail_needs(self):
        return "none"

    def on_show(self):
        # the file may have been edited in a text editor since
        self._load()
        self._publish_sample()

    def on_manufacturer(self, mfr):
        self._publish()


TAB = ColorTab
