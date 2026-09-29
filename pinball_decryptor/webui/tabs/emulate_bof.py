"""Emulate BoF tab: run a Barrels of Fun game on this PC.

THIN, like the JJP tab: every step of the launch (decrypt, boards, game)
lives in ``tools/bof_emu/watch.sh``.  This service starts it, stops it, polls
``status.sh``, and - unlike the other rigs, whose playfields have their own
windows - carries the switch panel itself: the title's switch table comes
from its profile, and a press goes to the rig over ONE long-lived
``ctl.sh --stream`` pipe, because starting wsl.exe per click costs a few
hundred milliseconds and a flipper cannot wait that long.

Exports ``bof_emulate_fun_var`` (the run logic persists it per project) and
answers ``emulate_shutdown`` (the app-quit fan-out).  ``launch_fun(path)``
starts a given build - the hook for "play what Write just built".
"""

import os
import subprocess
import sys
import threading

from pinball_decryptor.webui import rig as _rig
from .. import compat
from .. import emulate_bof_core as bof
from ..emulate_jjp_common import RigTabMixin, rig_off, load_audio_ctl
from .base import TabService, rpc

INTRO = ("Run a Barrels of Fun game on this PC - Dune, Winchester Mystery "
         "House or Labyrinth. The game is a native Linux program, so it runs "
         "directly; the emulator stands in for the machine's boards.\n"
         "Pick the machine's .fun update file, or one the Write tab built, to "
         "play a mod before it goes on a USB stick.")

FUN_TIP = ("A Barrels of Fun update file (.fun). It is only read: the "
           "emulator unpacks a copy inside the app's Linux, and keeps the last "
           "two so the next start is instant.")

SOUND_TIP = ("Play the game's sound on this PC. Applies when the game starts; "
             "the game's own volume is in its service menu.")

#: The status grid (label, key into the values _apply computes).
CELLS = (
    ("Game", "title"),
    ("Boards", "boards"),
    ("Balls", "balls"),
    ("LEDs lit", "leds"),
    ("Drivers set up", "drivers"),
    ("Memory", "rss"),
    ("Uptime", "uptime"),
)

#: The buttons above the switch list: profile key -> label, in cabinet order.
QUICK = (("start", "Start"), ("coin", "Coin"), ("launch", "Launch"),
         ("flipper_left", "Left flipper"), ("flipper_right", "Right flipper"),
         ("action", "Action"), ("tilt", "Tilt"))
SERVICE = (("enter", "Enter"), ("exit", "Exit"), ("up", "Up"),
           ("down", "Down"))


class _CtlStream:
    """One ``ctl.sh --stream`` process, restarted on demand.  Replies are
    read on a thread and dropped (a refused press is logged)."""

    def __init__(self, log):
        self._proc = None
        self._lock = threading.Lock()
        self._log = log

    def send(self, line):
        with self._lock:
            for _attempt in (1, 2):
                if self._proc is None or self._proc.poll() is not None:
                    self._start()
                try:
                    self._proc.stdin.write(line + "\n")
                    self._proc.stdin.flush()
                    return True
                except (OSError, ValueError, AttributeError):
                    self._proc = None
            return False

    def _start(self):
        self._proc = subprocess.Popen(
            bof.rig_cmd("ctl.sh", "--stream"),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True,
            encoding="utf-8", errors="replace",
            creationflags=_rig.CREATE_FLAGS)
        proc = self._proc

        def drain():
            for reply in proc.stdout:
                reply = reply.strip()
                if reply.startswith("err") or reply.startswith("bofctl:"):
                    self._log("BoF: " + reply)
        threading.Thread(target=drain, daemon=True,
                         name="pad-bof-ctl").start()

    def close(self):
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.stdin.close()
                proc.wait(timeout=5)
            except Exception:                              # noqa: BLE001
                try:
                    proc.kill()
                except Exception:                          # noqa: BLE001
                    pass


class EmulateBoFTab(RigTabMixin, TabService):
    ns = "emulate_bof"
    key = "Emulate BoF"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = ("bof_emulate_fun_var",)

    LOG_PREFIX = "BoF: "
    PHASES = bof.PHASES
    POLL_MS = bof.POLL_MS
    POLL_IDLE_MS = bof.POLL_IDLE_MS
    POLL_FIRST_MS = bof.POLL_FIRST_MS

    def __init__(self, window):
        super().__init__(window)
        self.bof_emulate_fun_var = self.var("fun")
        self._init_rig_state()
        self._ctl = _CtlStream(self._log)
        #: a Start is in flight (the button is Cancel) / its cancel is
        self._starting = False
        self._cancelling = False
        self._panel_title = None
        ok = bof.rig_available()
        if not ok:
            note = ("The Barrels of Fun emulator is missing from "
                    "tools/bof_emu - this install looks incomplete.")
        elif not bof.platform_ok():
            ok = False
            note = ("The Barrels of Fun emulator runs through WSL, so it is "
                    "available on Windows only.")
        else:
            note = ""
        self.set(intro=INTRO, fun_tip=FUN_TIP, sound_tip=SOUND_TIP,
                 platform=sys.platform, rig_ok=ok,
                 go_label="Start", go_enabled=ok, busy=False, go_busy=False,
                 state_label="Checking…", state_hint="", tone="",
                 cells=[{"label": lbl, "key": k, "value": "—"}
                        for lbl, k in CELLS],
                 note=note,
                 up=False, ready=False, game="", panel=None, active=[])
        self._start_polling()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _rig_ready(self):
        return bof.rig_available()

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
        self._ctl.close()

    def fun_path(self):
        """This tab's own .fun, else the one picked on Select card (the
        Extract input) - that page lists Emulate as working "straight from
        the card", so a card already picked must not be asked for again."""
        own = (self.bof_emulate_fun_var.get() or "").strip()
        if own:
            return own
        card = getattr(self.window, "extract_input_var", None)
        try:
            path = (card.get() or "").strip() if card is not None else ""
        except Exception:                                  # noqa: BLE001
            path = ""
        return path if path.lower().endswith(".fun") else ""

    # ------------------------------------------------------------------
    # the page's calls
    # ------------------------------------------------------------------
    @rpc
    def browse(self):
        path = self.window.ask_open(
            "bof_emulate_fun", "Select a Barrels of Fun .fun file",
            [("Barrels of Fun update", "*.fun"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(self.fun_path()))
        if path:
            self.bof_emulate_fun_var.set(os.path.normpath(path))
        return path or ""

    @rpc
    def toggle(self):
        """Start / Stop - and Cancel while a start is in flight (the button
        says so: unpacking a 4 GB build off a busy disk can take a long
        time, and nothing else could end it)."""
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
        """End the start in flight: tools/bof_emu/cancel.sh ends watch.sh and
        everything it started (the decrypt included), drops the half-unpacked
        build and stops any game that had come up."""
        if not self._starting or self._cancelling:
            return False
        self._cancelling = True
        self._set_go("Cancelling…", False)
        self._log("BoF: cancelling the start…")

        def work():
            try:
                out = subprocess.run(
                    bof.rig_cmd_root("cancel.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("BoF: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("BoF: cancel failed: %s" % exc)

        threading.Thread(target=work, daemon=True,
                         name="pad-bof-cancel").start()
        return True

    @rpc
    def press(self, n, ms=150):
        """Tap switch *n* (press, release after *ms*)."""
        return self._send("tap %d %d" % (int(n), max(30, min(5000, int(ms)))))

    @rpc
    def hold(self, n, on):
        """Hold switch *n* down (on) or let it go - flippers, the coin door."""
        return self._send("sw %d %d" % (int(n), 1 if on else 0))

    @rpc
    def plunge(self):
        return self._send("plunge")

    @rpc
    def drain(self):
        return self._send("drain")

    def _send(self, line):
        if rig_off() or not self._last_up:
            return False
        return self._ctl.send(line)

    def launch_fun(self, path):
        """Start the rig on *path* (a .fun), exactly as the Start button."""
        path = (path or "").strip()
        if not path or self._busy:
            return False
        self.bof_emulate_fun_var.set(path)
        self._start_async()
        return True

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
        fun = self.fun_path()
        if not fun:
            compat.messagebox.showinfo(
                "Emulate",
                "Pick a Barrels of Fun .fun file first - the machine's own "
                "update file, or one the Write tab built.")
            return
        if not os.path.isfile(fun):
            compat.messagebox.showinfo("Emulate", "There is no file at\n%s"
                                       % fun)
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
                self._log("BoF: starting %s (a first start unpacks the build "
                          "- a minute or two; the next is instant)."
                          % os.path.basename(fun))
                rc = self._run_streaming(
                    bof.rig_cmd_root(
                        "watch.sh", _rig.wsl_path(fun),
                        env=["BOF_KEYS=" + bof.title_keys(),
                             "PAD_VISIBLE=1",
                             "PAD_AUDIO=%d" % (0 if muted else 1)]),
                    timeout=1800, on_line=self._footer_line)
                if self._cancelling:
                    self._started_here = False
                    self._log("BoF: start cancelled.")
                elif rc not in (0, None):
                    self._log("BoF: start failed (exit %d). %s"
                              % (rc, bof.EXIT_TEXT.get(rc, "")))
            except Exception as exc:                       # noqa: BLE001
                self._log("BoF: start failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-bof-start").start()

    def _footer_line(self, line):
        for head, kind, pct, text in bof.FOOTER_STEPS:
            if line.startswith(head):
                self._footer(kind, pct, text)
                return
        if line.startswith("progress "):
            try:
                pct = int(line.split()[1])
            except (IndexError, ValueError):
                return
            self._footer("copy", pct, "Decrypting the game… %d%%" % pct)

    def _stop_async(self):
        if self._refuse_off():
            return
        self._busy = True
        self._go_busy = True
        self._started_here = False
        self._set_go("Stopping…", False)
        self._ctl.close()

        def work():
            try:
                out = subprocess.run(
                    bof.rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("BoF: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("BoF: stop failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-bof-stop").start()

    def _release(self):
        def done():
            self._busy = False
            self._go_busy = False
            self._starting = False
            self._cancelling = False
            self._set_go(enabled=bof.rig_available())
            self._poll_now()
        self._post(done)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def _read_status(self):
        return self._run_status(bof.rig_cmd("status.sh"))

    def _footer_from_info(self):
        if self._last_up:
            self._footer_now("run", None, "Game running")
        else:
            self._footer_now("idle")

    def _panel(self, title):
        """The switch panel for *title*: quick buttons, service buttons and
        every switch, grouped, from the title's profile."""
        prof = bof.load_profile(title)
        if not prof:
            return None
        keys = prof.get("keys") or {}
        quick = [{"key": k, "label": lbl, "n": keys[k],
                  "hold": k.startswith("flipper")}
                 for k, lbl in QUICK if k in keys]
        service = [{"label": lbl, "n": keys[k]}
                   for k, lbl in SERVICE if k in keys]
        cab, pf = [], []
        for s in prof.get("switches") or []:
            item = {"n": s["n"], "label": s.get("label") or s.get("const", ""),
                    "opto": bool(s.get("opto"))}
            (cab if "cabinet" in (s.get("tags") or []) or s["n"] < 24
             else pf).append(item)
        return {"title": prof.get("title") or bof.title_name(title),
                "quick": quick, "service": service,
                "coin_door": keys.get("coin_door"),
                "groups": [{"name": "Cabinet", "switches": cab},
                           {"name": "Playfield", "switches": pf}]}

    def _apply(self, info):
        self._info = info
        was_up = self._last_up
        self._last_up = info.get("running") == "1"
        if was_up and not self._last_up:
            self._started_here = False
            self._ctl.close()
        hw = bof.hw_state(info)
        ready = bool((hw.get("status") or {}).get("hardware_connected"))
        label, hint = bof.state_text(info)
        tone = "ok" if self._last_up and ready else (
            "warn" if label == "WSL not answering" else "")
        title = info.get("title") if self._last_up else ""
        rss = int(info.get("rss_kb") or 0)
        up = int(info.get("uptime_s") or 0)
        values = {
            "title": bof.title_name(title) if title else "—",
            "boards": bof.boards_text(hw) if self._last_up else "—",
            "balls": bof.balls_text(hw) if self._last_up else "—",
            "leds": str(hw.get("leds_lit", "—")) if self._last_up else "—",
            "drivers": str(hw.get("drivers_configured", "—"))
            if self._last_up else "—",
            "rss": ("%.1f GB" % (rss / 1048576.0)) if rss else "—",
            "uptime": ("%d:%02d" % (up // 60, up % 60)) if up else "—",
        }
        kw = dict(state_label=label, state_hint=hint, tone=tone,
                  cells=[{"label": lbl, "key": k, "value": values.get(k, "—")}
                         for lbl, k in CELLS],
                  note="" if bof.rig_available() else self.get("note"),
                  up=self._last_up, ready=ready,
                  game=bof.title_name(title) if title else "",
                  active=sorted(int(k) for k, v in
                                (hw.get("switches") or {}).items() if v))
        if title != self._panel_title:
            self._panel_title = title
            kw["panel"] = self._panel(title) if title else None
        if not self._busy:
            kw["go_label"] = "Stop" if self._last_up else "Start"
            kw["go_enabled"] = bof.rig_available()
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
        self._ctl.close()
        if rig_off() or not bof.rig_available() or not bof.platform_ok():
            return
        if not self._started_here or not (self._last_up or self._busy):
            return
        try:
            subprocess.run(bof.rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    shutdown_sync = emulate_shutdown


TAB = EmulateBoFTab
