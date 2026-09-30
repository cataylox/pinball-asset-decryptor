"""Emulate AP tab: run an American Pinball game (Houdini, Oktoberfest, Hot
Wheels, Legends of Valhalla, Galactic Tank Force) on this PC from its
game-code .pkg.

THIN, like the BoF tab: every step of the launch (set the rig's Python up
the first time, unpack the .pkg, start the game) lives in
``tools/ap_emu/watch.sh``.  This service starts it (and cancels it), stops
it, and polls ``status.sh``.

The machine's switches are a WINDOW of their own, as the other rigs' are:
``tools/ap_emu/appf.py`` - the game's own playfield picture with its
switches on it, plus a labelled list and the ball controls (Plunge, Drain) -
run on the app's Windows Python.  This tab opens it once the game is up,
reopens it on request, and closes it on Stop.

Exports ``ap_emulate_pkg_var`` (the run logic persists it per project) and
answers ``emulate_shutdown`` (the app-quit fan-out).  ``launch_pkg(path)``
starts a given .pkg - the hook for "play what Write just built".
"""

import os
import subprocess
import sys
import threading

from pinball_decryptor.webui import rig as _rig
from .. import compat
from .. import emulate_ap_core as ap
from ..emulate_jjp_common import (RigTabMixin, rig_off, load_audio_ctl,
                                  windows_python)
from .base import TabService, rpc

INTRO = ("Run an American Pinball game on this PC - Houdini, Oktoberfest, "
         "Hot Wheels, Legends of Valhalla or Galactic Tank Force. The "
         "emulator stands in for the machine's controller board and gives the "
         "game a window, sound and every switch.\n"
         "Pick the game's code file (.pkg) - the one the machine installs, or "
         "one the Write tab built, to play a mod before it goes on a USB "
         "stick.")

PKG_TIP = ("The game's code file (.pkg), as American Pinball publishes it. It "
           "is only read: the emulator unpacks it once (under a minute) and "
           "keeps it, so the next start is quick.")

SOUND_TIP = ("Play the game's sound on this PC. Applies when the game starts; "
             "the game's own volume is in its service menu.")

SWITCHES_TIP = ("The machine's switches: the game's own playfield picture with "
                "every switch on it, and a labelled list. Hold a switch with "
                "the mouse, right-click to latch it; Plunge and Drain move "
                "the ball.")

#: The status grid (label, key into the values _apply computes).
CELLS = (
    ("Game", "title"),
    ("Version", "version"),
    ("Switches", "switches"),
    ("Window", "window"),
    ("Memory", "rss"),
    ("Uptime", "uptime"),
)


class EmulateAPTab(RigTabMixin, TabService):
    ns = "emulate_ap"
    key = "Emulate AP"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = ("ap_emulate_pkg_var",)

    LOG_PREFIX = "AP: "
    PHASES = ap.PHASES
    POLL_MS = ap.POLL_MS
    POLL_IDLE_MS = ap.POLL_IDLE_MS
    POLL_FIRST_MS = ap.POLL_FIRST_MS

    def __init__(self, window):
        super().__init__(window)
        self.ap_emulate_pkg_var = self.var("pkg")
        self._init_rig_state()
        self._starting = False
        self._cancelling = False
        #: the switch window (appf.py), when this app opened one
        self._sw_proc = None
        ok = ap.rig_available()
        if not ok:
            note = ("The American Pinball emulator is missing from "
                    "tools/ap_emu - this install looks incomplete.")
        elif not ap.platform_ok():
            ok = False
            note = ("The American Pinball emulator runs through WSL, so it "
                    "is available on Windows only.")
        else:
            note = ""
        self.set(intro=INTRO, pkg_tip=PKG_TIP, sound_tip=SOUND_TIP,
                 switches_tip=SWITCHES_TIP, platform=sys.platform, rig_ok=ok,
                 go_label="Start", go_enabled=ok, busy=False, go_busy=False,
                 starting=False,
                 state_label="Checking…", state_hint="", tone="",
                 cells=[{"label": lbl, "key": k, "value": "—"}
                        for lbl, k in CELLS],
                 note=note, up=False, game="")
        self._start_polling()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _rig_ready(self):
        return ap.rig_available()

    def on_manufacturer(self, mfr):
        if getattr(self, "_visible", False):
            self._schedule_poll()
        else:
            self._restore_default_phases()

    def on_show(self):
        self._show_own_phases()
        self._reload_volume()
        if self._polled_once and not self._busy:
            self._footer_from_info()
        elif not self._busy:
            self._footer_now("idle")
        self._poll_on_show()

    def on_close(self):
        self._stopped = True
        self._cancel_poll()

    def pkg_path(self):
        """The tab's own field, else the Select card input (the Extract
        tab's) when it is a .pkg - that page lists Emulate as working
        straight from the file."""
        own = (self.ap_emulate_pkg_var.get() or "").strip()
        if own:
            return own
        card = getattr(self.window, "extract_input_var", None)
        try:
            card = (card.get() or "").strip() if card is not None else ""
        except Exception:                                  # noqa: BLE001
            card = ""
        return card if ap.is_pkg(card) else ""

    # ------------------------------------------------------------------
    # the page's calls
    # ------------------------------------------------------------------
    @rpc
    def browse(self):
        path = self.window.ask_open(
            "ap_emulate_pkg", "Select an American Pinball game-code file",
            [("American Pinball game code", "*.pkg"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(self.pkg_path()))
        if path:
            self.ap_emulate_pkg_var.set(os.path.normpath(path))
        return path or ""

    @rpc
    def toggle(self):
        """Start / Stop - and Cancel while a start is in flight (the first
        one sets the emulator up, a few minutes)."""
        if self._starting and not self._cancelling:
            return self.cancel()
        if self._busy:
            return False
        if self._last_up:
            self._stop_async()
        else:
            self._start_async()
        return True

    @rpc
    def cancel(self):
        if not self._starting or self._cancelling:
            return False
        self._cancelling = True
        self._set_go("Cancelling…", False)
        self._log("AP: cancelling the start…")

        def work():
            try:
                out = subprocess.run(
                    ap.rig_cmd_root("cancel.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("AP: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("AP: cancel failed: %s" % exc)

        threading.Thread(target=work, daemon=True,
                         name="pad-ap-cancel").start()
        return True

    @rpc
    def switches(self):
        """Open (or bring back) the switch window for the running game."""
        if rig_off() or not self._last_up:
            return False
        info = dict(self._info)

        def work():
            self._open_switches(info)
        threading.Thread(target=work, daemon=True,
                         name="pad-ap-switches").start()
        return True

    def launch_pkg(self, path):
        """Start the rig on *path* (a .pkg), exactly as the Start button."""
        path = (path or "").strip()
        if not path or self._busy:
            return False
        self.ap_emulate_pkg_var.set(path)
        self._start_async()
        return True

    # ------------------------------------------------------------------
    # the switch window
    # ------------------------------------------------------------------
    def _switch_window_cmd(self, info):
        """appf.py's command line for the running game, or None."""
        table = info.get("switches_json")
        py = windows_python()
        if not table or not py:
            return None
        cmd = [py, os.path.join(ap.rig_dir(), "appf.py"),
               "--slot", info.get("slot") or "0"]
        if ap.title_name(info):
            cmd += ["--title", ap.title_name(info)]
        distro = ap.rig_distro()
        if distro:
            # the table (and the playfield picture it names) live in the
            # app's Linux; Windows reads them through the distro's share
            cmd += ["--distro", distro, "--table",
                    "\\\\wsl.localhost\\%s%s" % (distro, table.replace("/", "\\"))]
        else:
            cmd += ["--table", table]
        return cmd

    def _open_switches(self, info=None):
        if self._sw_proc is not None and self._sw_proc.poll() is None:
            return True
        if info is None or not info.get("switches_json"):
            info = self._read_status()
        cmd = self._switch_window_cmd(info or {})
        if not cmd:
            self._log("AP: could not open the switch window (no Python to "
                      "run it with, or the game is not running).")
            return False
        try:
            self._sw_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_rig.CREATE_FLAGS)
            return True
        except Exception as exc:                           # noqa: BLE001
            self._sw_proc = None
            self._log("AP: could not open the switch window: %s" % exc)
            return False

    def _close_switches(self):
        proc, self._sw_proc = self._sw_proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:                              # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # start / stop
    # ------------------------------------------------------------------
    def _set_go(self, label=None, enabled=None):
        kw = {}
        if label is not None:
            kw["go_label"] = label
        if enabled is not None:
            kw["go_enabled"] = bool(enabled)
        kw["busy"] = self._busy
        kw["go_busy"] = self._go_busy
        kw["starting"] = self._starting
        self.set(**kw)

    def _start_async(self):
        pkg = self.pkg_path()
        if not pkg:
            compat.messagebox.showinfo(
                "Emulate", "Pick the game's code file first (.pkg).")
            return
        if not os.path.isfile(pkg):
            compat.messagebox.showinfo("Emulate",
                                       "There is no file at\n%s" % pkg)
            return
        key, title = ap.game_info(pkg)
        if key in ap.NOT_HERE:
            compat.messagebox.showinfo("Emulate", ap.EXIT_TEXT[10])
            return
        if self._refuse_off():
            return
        self._busy = True
        self._go_busy = False
        self._starting = True
        self._cancelling = False
        self._started_here = True
        self._set_go("Cancel", True)
        _vol, muted = load_audio_ctl()

        def work():
            try:
                self._log("AP: starting %s%s." % (
                    os.path.basename(pkg), " (%s)" % title if title else ""))
                rc = self._run_streaming(
                    ap.rig_cmd_root(
                        "watch.sh", _rig.wsl_path(pkg),
                        env=["PAD_VISIBLE=1",
                             "PAD_AUDIO=%d" % (0 if muted else 1),
                             "PAD_LABEL=PAD",
                             "PAD_TITLE=%s" % title]),
                    timeout=3600, on_line=self._footer_line)
                if self._cancelling:
                    self._started_here = False
                    self._log("AP: start cancelled.")
                elif rc not in (0, None):
                    self._log("AP: start failed (exit %d). %s"
                              % (rc, ap.EXIT_TEXT.get(rc, "")))
                else:
                    self._open_switches()
            except Exception as exc:                       # noqa: BLE001
                self._log("AP: start failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-ap-start").start()

    def _footer_line(self, line):
        for head, kind, pct, text in ap.FOOTER_STEPS:
            if line.startswith(head):
                self._footer(kind, pct, text)
                return
        if line.startswith("progress "):
            try:
                pct = int(line.split()[1])
            except (IndexError, ValueError):
                return
            self._footer("copy", pct, "Unpacking the game… %d%%" % pct)

    def _stop_async(self):
        if self._refuse_off():
            return
        self._busy = True
        self._go_busy = True
        self._started_here = False
        self._set_go("Stopping…", False)
        self._close_switches()

        def work():
            try:
                out = subprocess.run(
                    ap.rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("AP: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("AP: stop failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-ap-stop").start()

    def _release(self):
        def done():
            self._busy = False
            self._go_busy = False
            self._starting = False
            self._cancelling = False
            self._set_go(enabled=ap.rig_available())
            self._poll_now()
        self._post(done)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def _read_status(self):
        return self._run_status(ap.rig_cmd("status.sh"))

    def _footer_from_info(self):
        if self._last_up:
            self._footer_now("run", None, "Game running")
        else:
            self._footer_now("idle")

    def _apply(self, info):
        self._info = info
        was_up = self._last_up
        self._last_up = info.get("running") == "1"
        if was_up and not self._last_up:
            self._started_here = False
            self._close_switches()
        label, hint = ap.state_text(info)
        tone = "ok" if self._last_up else (
            "warn" if label == "WSL not answering" else "")
        up = self._last_up
        rss = int(info.get("rss_kb") or 0)
        secs = int(info.get("uptime_s") or 0)
        window = " + ".join(w.replace("x", " × ") for w in
                            (info.get("window") or "").split())
        if up and info.get("av") == "1":
            window = "AP's A/V player"
        values = {
            "title": ap.title_name(info) if up else "—",
            "version": (info.get("version") or "—") if up else "—",
            "switches": (info.get("switches") or "—") if up else "—",
            "window": (window or "—") if up else "—",
            "rss": ("%.1f GB" % (rss / 1048576.0)) if up and rss else "—",
            "uptime": ("%d:%02d" % (secs // 60, secs % 60)) if up and secs
            else "—",
        }
        kw = dict(state_label=label, state_hint=hint, tone=tone,
                  cells=[{"label": lbl, "key": k, "value": values.get(k, "—")}
                         for lbl, k in CELLS],
                  note="" if ap.rig_available() else self.get("note"),
                  up=up, game=ap.title_name(info) if up else "")
        if not self._busy:
            kw["go_label"] = "Stop" if up else "Start"
            kw["go_enabled"] = ap.rig_available()
            self._footer_from_info()
        kw["busy"] = self._busy
        kw["go_busy"] = self._go_busy
        kw["starting"] = self._starting
        self.set(**kw)

    # ------------------------------------------------------------------
    # app quit
    # ------------------------------------------------------------------
    def emulate_shutdown(self):
        """App-quit hook: stop the game this app started (bounded), and
        nothing else - a run it merely saw is somebody else's."""
        self._stopped = True
        self._cancel_poll()
        self._close_switches()
        if rig_off() or not ap.rig_available() or not ap.platform_ok():
            return
        if not self._started_here or not (self._last_up or self._busy):
            return
        try:
            subprocess.run(ap.rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    shutdown_sync = emulate_shutdown


TAB = EmulateAPTab
