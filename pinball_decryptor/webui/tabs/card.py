"""The web Select card tab (PAD-224): pick the card image (or the card in a
reader) the app works on, and see which tabs work straight from it and
which need it extracted first.

The card itself is still the Extract tab's input (``extract_input_var``
and friends, which the run logic and the other tabs read), so the page
renders the ``extract`` namespace and calls ``extract.*`` for the picker.
This service owns what the page shows ABOUT the picked card, both read on a
worker so the tab never waits on them:

* ``preview`` - the boot screen, or a multi-boot card's menu
  (:mod:`..card_preview`), as a "yes, that one" for the pick;
* ``info`` - the Image Info report, shown under the card tile rather than
  in a window of its own.

The page says which card it is showing (:meth:`look`); a card already
looked at is not read again.
"""

import os
import threading

from .base import TabService, rpc
from .. import card_preview as CP


class CardTab(TabService):
    ns = "card"
    key = "Select Card"
    label = "Select card"
    group = "Card"
    icon = "sd"

    def __init__(self, window):
        super().__init__(window)
        self._key = None
        self._path = ""
        self._seq = 0
        self._runner = None
        self._info_sections = []
        self.set(preview=None, info=None)

    def on_show(self):
        ext = self.window.service("extract")
        if ext is not None:
            ext.on_show()

    def _forget(self):
        self._key = None
        self._path = ""
        self._seq += 1
        if self._runner is not None:
            self._runner.cancel()
            self._runner = None
        self._info_sections = []
        self.set(preview=None, info=None)

    # ------------------------------------------------------------------
    @rpc
    def look(self, path, force=False):
        """The page is showing *path* (a card image or a device, '' for
        none): read its boot screen and its Image Info, unless that is what
        is on the page already."""
        from ...core.rawdevice import is_device_path
        path = (path or "").strip().strip('"')
        if path and not is_device_path(path):
            if not os.path.isfile(path):
                path = ""
            else:
                path = os.path.normpath(path)
        mfr = self.mfr
        key = (os.path.normcase(path), getattr(mfr, "key", ""),
               CP.card_key(path) if path else None)
        if key == self._key and not force:
            return True
        self._forget()
        if not path or mfr is None:
            return True
        self._key, self._path = key, path
        seq = self._seq
        self._start_info(seq, mfr, path)
        if getattr(mfr, "key", "") == "stern":
            self._start_preview(seq, path)
        return True

    @rpc
    def refresh(self):
        """Read the card on the page again, its cached pictures included."""
        path = self._path
        if not path:
            return False
        ck = CP.card_key(path)
        if ck:
            for name in ("splash.png", "boot.png", "menu.png"):
                try:
                    os.remove(os.path.join(CP.cache_root(), ck, name))
                except OSError:
                    pass
        return self.look(path, force=True)

    # -- the splash / the menu --------------------------------------------
    def _post(self, seq, fn, *args, **kw):
        """``fn(*args, **kw)`` on the loop, unless another card has been
        picked since *seq*."""
        self.ctx.loop.post(lambda: seq == self._seq and fn(*args, **kw))

    def _preview(self, **kw):
        self.set(preview=dict(self.get("preview") or {}, **kw))

    def _start_preview(self, seq, path):
        ck = CP.card_key(path)
        out = os.path.join(CP.cache_root(), ck or "device")
        runner = CP.Runner()
        self._runner = runner
        self.set(preview={"state": "loading", "stage": "Reading the card…"})

        def _work():
            games = CP.games_on(path)
            why = ""
            if len(games) >= 2:
                self._post(seq, self._preview, games=len(games))
                shot = CP.cached(out, "menu.png") if ck else None
                if shot is None and not ck:
                    why = ("the menu is drawn from an image file, and this "
                           "is the card in the reader")
                elif shot is None and CP.rig_off():
                    why = "the emulator tools are off (PAD_UI_NO_RIG)"
                elif shot is None:
                    self._post(seq, self._preview,
                               stage="Drawing the boot menu…")
                    try:
                        shot = CP.menu_png(path, out, runner)
                    except CP.Cancelled:
                        return
                    except Exception as e:              # noqa: BLE001
                        why = str(e) or e.__class__.__name__
                if shot is not None:
                    self._post(seq, self._preview, state="ready", kind="menu",
                               **shot)
                    return
            try:
                shot = None
                for kind in ("splash", "boot") if ck else ():
                    shot = CP.cached(out, kind + ".png")
                    if shot is not None:
                        shot["kind"] = kind
                        break
                shot = shot or CP.splash_png(path, out)
            except Exception as e:                      # noqa: BLE001
                shot, why = None, (why or str(e))
            if runner.cancelled:
                return
            if shot is None:
                # an ordinary card with nothing to show shows nothing
                self._post(seq, self._preview, state="none",
                           note=("Could not draw the boot menu: %s." % why
                                 if len(games) >= 2 else ""))
                return
            note = ""
            if len(games) >= 2:
                note = ("Showing the first game's loading screen instead of "
                        "the menu: %s." % why)
            self._post(seq, self._preview, state="ready", kind=shot["kind"],
                       note=note, src=shot["src"], w=shot["w"], h=shot["h"])

        threading.Thread(target=_work, daemon=True,
                         name="card-preview").start()

    # -- Image Info --------------------------------------------------------
    def _start_info(self, seq, mfr, path):
        from ...core import image_info as _info_mod
        ext = self.window.service("extract")
        assets = ext._info_assets_dir() if ext is not None else None
        self.set(info={"state": "loading", "path": path, "sections": []})

        def _work():
            try:
                sections = _info_mod.collect(mfr, path, assets)
            except Exception as e:                      # noqa: BLE001
                sections = [("Error", [("Could not read", str(e))])]
            self._post(seq, self._apply_info, path, sections)

        threading.Thread(target=_work, daemon=True, name="card-info").start()

    def _apply_info(self, path, sections):
        self._info_sections = list(sections or [])
        out = [{"title": str(title),
                "rows": [[str(r[0]), str(r[1])] for r in rows]}
               for title, rows in self._info_sections]
        self.set(info={"state": "ready", "path": path, "sections": out,
                       "status": ""})

    @rpc
    def info_copy(self):
        from ...core import image_info as _info_mod
        if not self._info_sections:
            return ""
        text = _info_mod.as_text(self._info_sections)
        self.ctx.bus.publish("clipboard", text=text)
        self.set(info=dict(self.get("info") or {},
                           status="Report copied to clipboard."))
        return text


TAB = CardTab
