"""Emulate Spooky tab: run a Spooky Pinball game on this PC - Beetlejuice
only, so far, and the page says so first.

THIN, like the BoF tab: every step of the launch (unpack, board, game)
lives in ``tools/spooky_emu/watch.sh``.  This service starts it (and cancels
it), stops it, and polls ``status.sh``.

The machine's switches are a WINDOW of their own, as the other rigs' are:
``tools/spooky_emu/spkpf.py`` (the BoF switch window pointed at this rig's
board), run on the app's Windows Python.  This tab opens it once the game is
in attract mode, reopens it on request, and closes it on Stop.

Exports ``spooky_emulate_file_var`` (the run logic persists it per project)
and answers ``emulate_shutdown`` (the app-quit fan-out).
"""

import os
import subprocess
import sys
import threading

from pinball_decryptor.webui import rig as _rig
from .. import compat
from .. import emulate_spooky_core as spk
from ..emulate_jjp_common import (RigTabMixin, rig_off, load_audio_ctl,
                                  windows_python)
from .base import TabService, rpc

INTRO = ("Run a Spooky Pinball game on this PC. Supported so far: %s - "
         "the other Spooky games can't be emulated yet. The game is a native "
         "Linux program, so it runs directly; the emulator stands in for the "
         "machine's controller board.\n"
         "Pick the machine's update file, or one the Write tab built, to play "
         "a mod before it goes on a USB stick."
         % ", ".join(spk.supported_names()))

FILE_TIP = ("A Beetlejuice update file (.beetlejuice). It is only read: the "
            "emulator unpacks a copy inside the app's Linux, and keeps the "
            "last two so the next start is quicker.")

SOUND_TIP = ("Play the game's sound on this PC. Applies when the game starts; "
             "the game's own volume is in its service menu.")

SWITCHES_TIP = ("The machine's switches, every one by name. Hold a switch with "
                "the mouse, right-click to latch it.")

#: The status grid (label, key into the values _apply computes).
CELLS = (
    ("Game", "title"),
    ("Version", "version"),
    ("Board", "board"),
    ("Balls", "balls"),
    ("Memory", "rss"),
    ("Uptime", "uptime"),
)


class EmulateSpookyTab(RigTabMixin, TabService):
    ns = "emulate_spooky"
    key = "Emulate Spooky"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = ("spooky_emulate_file_var",)

    LOG_PREFIX = "Spooky: "
    PHASES = spk.PHASES
    POLL_MS = spk.POLL_MS
    POLL_IDLE_MS = spk.POLL_IDLE_MS
    POLL_FIRST_MS = spk.POLL_FIRST_MS

    def __init__(self, window):
        super().__init__(window)
        self.spooky_emulate_file_var = self.var("file")
        self._init_rig_state()
        #: a Start is in flight (the button is Cancel) / its cancel is
        self._starting = False
        self._cancelling = False
        #: the switch window (spkpf.py), when this app opened one
        self._sw_proc = None
        ok = spk.rig_available()
        if not ok:
            note = ("The Spooky emulator is missing from tools/spooky_emu - "
                    "this install looks incomplete.")
        elif not spk.platform_ok():
            ok = False
            note = ("The Spooky emulator runs through WSL, so it is available "
                    "on Windows only.")
        else:
            note = ""
        self.set(intro=INTRO, file_tip=FILE_TIP, sound_tip=SOUND_TIP,
                 switches_tip=SWITCHES_TIP,
                 supported=spk.supported_names(),
                 platform=sys.platform, rig_ok=ok,
                 go_label="Start", go_enabled=ok, busy=False, go_busy=False,
                 starting=False,
                 state_label="Checking…", state_hint="", tone="",
                 cells=[{"label": lbl, "key": k, "value": "—"}
                        for lbl, k in CELLS],
                 note=note, up=False, ready=False, game="")
        self._start_polling()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _rig_ready(self):
        return spk.rig_available()

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

    def file_path(self):
        """This tab's own update file, else the one picked on Select card
        (the Extract input) when it is one the emulator runs - a card already
        picked must not be asked for again."""
        own = (self.spooky_emulate_file_var.get() or "").strip()
        if own:
            return own
        card = getattr(self.window, "extract_input_var", None)
        try:
            path = (card.get() or "").strip() if card is not None else ""
        except Exception:                                  # noqa: BLE001
            path = ""
        return path if spk.supported_file(path) else ""

    # ------------------------------------------------------------------
    # the page's calls
    # ------------------------------------------------------------------
    @rpc
    def browse(self):
        path = self.window.ask_open(
            "spooky_emulate_file", "Select a Beetlejuice update file",
            [("Beetlejuice update", "*.beetlejuice"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(self.file_path()))
        if path:
            self.spooky_emulate_file_var.set(os.path.normpath(path))
        return path or ""

    @rpc
    def toggle(self):
        """Start / Stop - and Cancel while a start is in flight."""
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
        """End the start in flight: tools/spooky_emu/cancel.sh ends watch.sh
        and everything it started, drops a half-unpacked build and stops any
        game that had come up."""
        if not self._starting or self._cancelling:
            return False
        self._cancelling = True
        self._set_go("Cancelling…", False)
        self._log("Spooky: cancelling the start…")

        def work():
            try:
                out = subprocess.run(
                    spk.rig_cmd_root("cancel.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("Spooky: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("Spooky: cancel failed: %s" % exc)

        threading.Thread(target=work, daemon=True,
                         name="pad-spooky-cancel").start()
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
                         name="pad-spooky-switches").start()
        return True

    def launch_file(self, path):
        """Start the rig on *path*, exactly as the Start button."""
        path = (path or "").strip()
        if not path or self._busy:
            return False
        self.spooky_emulate_file_var.set(path)
        self._start_async()
        return True

    # ------------------------------------------------------------------
    # the switch window
    # ------------------------------------------------------------------
    def _switch_window_cmd(self, info):
        """spkpf.py's command line for the running game, or None."""
        py = windows_python()
        if not py:
            return None
        cmd = [py, os.path.join(spk.rig_dir(), "spkpf.py"),
               "--slot", (info or {}).get("slot") or "0"]
        distro = spk.rig_distro()
        if distro:
            cmd += ["--distro", distro]
        return cmd

    def _open_switches(self, info=None):
        if self._sw_proc is not None and self._sw_proc.poll() is None:
            return True              # already open (it keeps itself on top)
        cmd = self._switch_window_cmd(info)
        if not cmd:
            self._log("Spooky: could not open the switch window (no Python "
                      "to run it with).")
            return False
        try:
            self._sw_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_rig.CREATE_FLAGS)
            return True
        except Exception as exc:                           # noqa: BLE001
            self._sw_proc = None
            self._log("Spooky: could not open the switch window: %s" % exc)
            return False

    def _close_switches(self):
        """The window also closes itself once the game stops answering;
        this is the prompt version, for Stop and app quit."""
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
        path = self.file_path()
        if not path:
            compat.messagebox.showinfo(
                "Emulate",
                "Pick a Beetlejuice update file first - the machine's own "
                "(.beetlejuice), or one the Write tab built.\n\n"
                "Supported so far: %s." % ", ".join(spk.supported_names()))
            return
        if not os.path.isfile(path):
            compat.messagebox.showinfo("Emulate", "There is no file at\n%s"
                                       % path)
            return
        if self._refuse_off():
            return
        self._busy = True
        # No spinner on the button while starting: it is the Cancel button
        # now, and the footer ladder shows the progress.
        self._go_busy = False
        self._starting = True
        self._cancelling = False
        self._started_here = True
        self._set_go("Cancel", True)
        _vol, muted = load_audio_ctl()

        def work():
            try:
                self._log("Spooky: starting %s (a first start unpacks the "
                          "update - a few minutes; then the game loads for "
                          "a minute or two)." % os.path.basename(path))
                rc = self._run_streaming(
                    spk.rig_cmd_root(
                        "watch.sh", _rig.wsl_path(path),
                        env=["PAD_VISIBLE=1",
                             "PAD_AUDIO=%d" % (0 if muted else 1)]),
                    timeout=1800, on_line=self._footer_line)
                if self._cancelling:
                    self._started_here = False
                    self._log("Spooky: start cancelled.")
                elif rc not in (0, None):
                    self._log("Spooky: start failed (exit %d). %s"
                              % (rc, spk.EXIT_TEXT.get(rc, "")))
                else:
                    self._open_switches()
            except Exception as exc:                       # noqa: BLE001
                self._log("Spooky: start failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True,
                         name="pad-spooky-start").start()

    def _footer_line(self, line):
        for head, kind, pct, text in spk.FOOTER_STEPS:
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
                    spk.rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("Spooky: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("Spooky: stop failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True,
                         name="pad-spooky-stop").start()

    def _release(self):
        def done():
            self._busy = False
            self._go_busy = False
            self._starting = False
            self._cancelling = False
            self._set_go(enabled=spk.rig_available())
            self._poll_now()
        self._post(done)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def _read_status(self):
        return self._run_status(spk.rig_cmd("status.sh"))

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
        hw = spk.hw_state(info)
        ready = self._last_up and info.get("attract") == "1"
        label, hint = spk.state_text(info)
        tone = "ok" if ready else (
            "warn" if label == "WSL not answering" else "")
        rss = int(info.get("rss_kb") or 0)
        up = int(info.get("uptime_s") or 0)
        values = {
            "title": "Beetlejuice" if self._last_up else "—",
            "version": (info.get("version") or "—") if self._last_up else "—",
            "board": ("connected" if hw.get("connected") else "waiting")
            if self._last_up else "—",
            "balls": spk.balls_text(hw) if self._last_up else "—",
            "rss": ("%.1f GB" % (rss / 1048576.0)) if rss else "—",
            "uptime": ("%d:%02d" % (up // 60, up % 60)) if up else "—",
        }
        kw = dict(state_label=label, state_hint=hint, tone=tone,
                  cells=[{"label": lbl, "key": k, "value": values.get(k, "—")}
                         for lbl, k in CELLS],
                  note="" if spk.rig_available() else self.get("note"),
                  up=self._last_up, ready=ready,
                  game="Beetlejuice" if self._last_up else "")
        if not self._busy:
            kw["go_label"] = "Stop" if self._last_up else "Start"
            kw["go_enabled"] = spk.rig_available()
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
        if rig_off() or not spk.rig_available() or not spk.platform_ok():
            return
        if not self._started_here or not (self._last_up or self._busy):
            return
        try:
            subprocess.run(spk.rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    shutdown_sync = emulate_shutdown


TAB = EmulateSpookyTab
