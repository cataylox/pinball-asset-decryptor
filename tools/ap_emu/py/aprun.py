"""aprun.py - run an American Pinball title on its own FakePinPROC.

usage (run_game.sh does this):  python aprun.py [--pm] <launcher.py>   in its folder

Python 2.7 (Houdini to Hot Wheels) or 3 (Galactic Tank Force's 2026 build).
The game's own simulator does the heavy lifting: config.yaml selects
procgame.fakepinproc.FakePinPROC and the desktop.  Two things the
machine has that FakePinPROC lacks are added here, before the launcher runs:

* A machine AT REST.  FakePinPROC.switch_get_states() answers all zeros, so
  every NC opto reads as blocked by a ball and the trough reads empty (or
  full, if its optos are NC) - games sit in ball search or refuse to start.
  Here each switch starts in its INACTIVE state (NC closed, NO open) and the
  trough holds the game's balls: the switches tagged `trough` (minus a jam
  switch) by number, the first PRGame.numBalls of them active; the coin
  door (`coinDoor`) is shut.
  AP_SEED="name=1,name=0" sets any switch's raw state on top.
* Switch input with nobody at the keyboard.  A reader thread takes lines
  `<switch> close|open|tap [ms]` from the FIFO $AP_FIFO (sw.py writes them)
  and the game loop delivers them through FakePinPROC.add_switch_event, the
  hook its own switch simulator uses - so every switch in the machine yaml
  can be pressed, not only the keyboard_switch_map ones.  `!drain` puts a
  ball back in the trough (the playfield has no physics to drain it).
* What the game sees, for the switch window: the numbers of the switches
  the game has active, in `active` beside $AP_LOG, rewritten when they change
  (checked five times a second from the game loop).

Everything the rig injects is logged to $AP_LOG.
"""
import os
import sys
import threading
import time
try:
    import Queue
except ImportError:                             # Python 3
    import queue as Queue
    basestring = str

    def execfile(path, g):
        with open(path) as f:
            exec(compile(f.read(), path, "exec"), g)

LOG = os.environ.get("AP_LOG")


def log(msg):
    if LOG:
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))


import pinproc                                  # ours (py/), ahead of any other
import locale
import types

# The games set en_US.UTF-8 (for locale.format's thousands commas in scores);
# PAD-Runtime has only C.UTF-8 compiled and no locale sources to build one.
# Fall back to C.UTF-8 and answer localeconv() with en_US's number rules -
# locale.format() reads them from there, and it is the only use they make.
_orig_setlocale = locale.setlocale
_orig_localeconv = locale.localeconv
_en_us = [False]


def _setlocale(category, loc=None):
    try:
        return _orig_setlocale(category, loc)
    except locale.Error:
        if not (loc and str(loc).startswith("en_US")):
            raise
        _en_us[0] = True
        return _orig_setlocale(category, "C.UTF-8")


def _localeconv():
    conv = _orig_localeconv()
    if _en_us[0]:
        conv.update(decimal_point=".", thousands_sep=",", grouping=[3, 3, 0],
                    mon_decimal_point=".", mon_thousands_sep=",", mon_grouping=[3, 3, 0],
                    currency_symbol="$", int_curr_symbol="USD ", positive_sign="",
                    negative_sign="-", frac_digits=2, int_frac_digits=2)
    return conv


locale.setlocale = _setlocale
locale.localeconv = _localeconv
# Tank's Python 3 code still calls locale.format (score commas), which 3.12
# removed; format_string is the same call for its single %d.
if not hasattr(locale, "format"):
    locale.format = lambda fmt, val, grouping=False, monetary=False: \
        locale.format_string(fmt, val, grouping, monetary)
try:
    import cv2
except ImportError:                             # Tank's Python 3: apiav plays video
    cv2 = None

# procgame's movie code is written for OpenCV 2.4 (`import cv2.cv as cv`,
# cv.CV_CAP_PROP_*, cv2.cv.CV_BGR2RGB, cv.fromarray(frame).tostring()); the
# py27 OpenCV setup.sh can get is 4.2, which dropped cv2.cv.  The names it
# uses, standing on 4.2's:
if cv2 is not None:
    _cv = types.ModuleType("cv2.cv")
    _cv.CV_CAP_PROP_FRAME_WIDTH = cv2.CAP_PROP_FRAME_WIDTH
    _cv.CV_CAP_PROP_FRAME_HEIGHT = cv2.CAP_PROP_FRAME_HEIGHT
    _cv.CV_CAP_PROP_FRAME_COUNT = cv2.CAP_PROP_FRAME_COUNT
    _cv.CV_CAP_PROP_POS_FRAMES = cv2.CAP_PROP_POS_FRAMES
    _cv.CV_CAP_PROP_FPS = cv2.CAP_PROP_FPS
    _cv.CV_BGR2RGB = cv2.COLOR_BGR2RGB
    _cv.fromarray = lambda a: a                 # a numpy array has .tostring()
    cv2.cv = sys.modules["cv2.cv"] = _cv

try:
    import sdl2
    import sdl2.video
except ImportError:                             # Tank: no SDL on the Python side
    sdl2 = None

# Every window the game opens, logged (run_game.sh waits for the first; shot.sh
# crops to them).  Patched before procgame's `from sdl2 import *` copies it.
if sdl2 is not None:
    _orig_create_window = sdl2.video.SDL_CreateWindow

    # A visible run's windows say whose they are (the line in
    # $AP_TITLE_FILE, "PAD - Legends of Valhalla"), not "PyProcGameHD.
    # [CTRL-C to exit]".
    try:
        with open(os.environ["AP_TITLE_FILE"], "rb") as f:
            _title = f.read().strip()
    except (KeyError, IOError, OSError):
        _title = b""

    def _create_window(title, x, y, w, h, flags):
        title = _title or title
        win = _orig_create_window(title, x, y, w, h, flags)
        log("window: %dx%d+%d+%d %s" % (w, h, x, y, title))
        return win

    sdl2.video.SDL_CreateWindow = sdl2.SDL_CreateWindow = _create_window
from procgame import fakepinproc
from procgame.game import game as pgame

_game = [None]
_queue = Queue.Queue()


def _raw_inactive(sw):
    return 1 if getattr(sw, "type", "NO") == "NC" else 0


def _rest_states(g):
    states = [0] * 256
    by_name = {}
    for sw in g.switches:
        if 0 <= sw.number < 256:
            states[sw.number] = _raw_inactive(sw)
            by_name[sw.name] = sw
    trough = [sw for sw in g.switches
              if "trough" in (getattr(sw, "tags", None) or [])
              and "jam" not in (getattr(sw, "label", "") or sw.name).lower()]
    if not trough:                              # untagged (Hot Wheels on): by name
        trough = [sw for sw in g.switches
                  if sw.name.startswith("trough") and sw.name[6:].isdigit()]
    trough.sort(key=lambda s: s.number)
    try:
        balls = int(g.config["PRGame"]["numBalls"])
    except Exception:
        balls = len(trough)
    for sw in trough[:balls]:
        states[sw.number] = 1 - _raw_inactive(sw)
    if "coinDoor" in by_name:                   # shut: no "Coin Door is Open"
        states[by_name["coinDoor"].number] = 1 - _raw_inactive(by_name["coinDoor"])
    for item in filter(None, os.environ.get("AP_SEED", "").split(",")):
        name, _, v = item.partition("=")
        if name.strip() in by_name:
            states[by_name[name.strip()].number] = int(v)
        else:
            log("AP_SEED: no switch %s" % name)
    log("rest: %d switches, trough %s holds %d (%s)" % (
        len(by_name), len(trough), min(balls, len(trough)),
        " ".join(s.name for s in trough[:balls])))
    # The machine's switches for sw.py --list: name, number, NO/NC, label.
    if LOG:
        with open(os.path.join(os.path.dirname(LOG), "switches"), "w") as f:
            for sw in sorted(by_name.values(), key=lambda s: s.number):
                f.write("%s %d %s %s\n" % (sw.name, sw.number, getattr(sw, "type", "NO"),
                                           getattr(sw, "label", "") or ""))
    return states


_orig_process_config = pgame.GameController.process_config


def process_config(self):
    _game[0] = self
    return _orig_process_config(self)


pgame.GameController.process_config = process_config

# SkeletonGame's OSC mode "closes" a title's osc_closed_switches at boot - the
# developers' way to fill the trough on their desktops, written for NO
# switches.  Houdini's trough optos are NC, where closed means EMPTY, so the
# game starts with no balls and goes ball searching.  The rest state above
# already holds the balls; the list is dropped.
try:
    from procgame.modes import osc as _osc
except ImportError:                             # Tank has osc23
    _osc = None


def _osc_hook(cls):
    orig = cls.__init__

    def init(self, *a, **k):
        if k.get("closed_switches"):
            log("osc: ignoring closed_switches %s" % " ".join(k["closed_switches"]))
        k["closed_switches"] = []
        return orig(self, *a, **k)
    cls.__init__ = init


if _osc is not None:
    _osc_hook(_osc.OSC_Mode)

# SkeletonGame treats ANY IOError while the game sets up as "no P-ROC" and
# dies in its own handler (self.log before a logger exists), hiding the real
# one - a missing font, image or folder.  Log the real one first.
from procgame.game import basicgame as _bg
_orig_bg_init = _bg.BasicGame.__init__


def _bg_init(self, *a, **k):
    try:
        return _orig_bg_init(self, *a, **k)
    except Exception:
        import traceback
        log("setup failed:\n" + traceback.format_exc())
        raise


_bg.BasicGame.__init__ = _bg_init

# Each kind of mode the game runs, once (bootcheck.sh looks for Attract).
from procgame.game import mode as _mq
_orig_mq_add = _mq.ModeQueue.add
_modes_seen = set()


def _mq_add(self, mode):
    name = type(mode).__name__
    if name not in _modes_seen:
        _modes_seen.add(name)
        log("mode+ %s" % name)
    return _orig_mq_add(self, mode)


_mq.ModeQueue.add = _mq_add

_orig_run_loop = pgame.GameController.run_loop


def run_loop(self, *a, **k):
    log("run_loop")
    return _orig_run_loop(self, *a, **k)


pgame.GameController.run_loop = run_loop

_orig_get_events = fakepinproc.FakePinPROC.get_events
_orig_get_events_nodmd = fakepinproc.FakePinPROC.get_events_noDMD


def _switch_states(self, *args):
    # (not getattr: FakePinPROC.__getattr__ answers any missing name with noop)
    st = self.__dict__.get("_ap_states")
    if st is None:
        st = self._ap_states = _rest_states(_game[0]) if _game[0] else [0] * 256
    return list(st)


def _log_state(g):
    """sw.py --state: what the game thinks - active switches, ball, players,
    the modes running."""
    if g is None:
        log("state: game not set up yet")
        return
    act = [sw.name for sw in g.switches if sw.is_active()]
    modes = [type(m).__name__ for m in g.modes.modes]
    log("state: ball %s, players %d, credits %s" % (
        getattr(g, "ball", "?"), len(getattr(g, "players", []) or []),
        getattr(g, "credits", getattr(g, "total_credits", "?"))))
    log("state: active %s" % " ".join(act))
    log("state: modes %s" % " ".join(modes))
    coil, pos, shooter = _trough_parts(g)
    log("state: trough coil %s (%s), positions %s, shooter %s" % (
        coil, type(g.coils[coil]).__name__ if coil in g.coils else "-",
        " ".join(s.name for s in pos), shooter.name if shooter else "-"))


def _inject(self):
    while True:
        try:
            num, closed = _queue.get_nowait()
        except Queue.Empty:
            return
        if num == "state":
            _log_state(_game[0])
            continue
        if num == "drain":
            _trough_drain(_game[0])
            continue
        sw = _game[0].switches[num]
        et = (pinproc.EventTypeSwitchClosedDebounced if closed else pinproc.EventTypeSwitchOpenDebounced) \
            if sw.debounce else \
            (pinproc.EventTypeSwitchClosedNondebounced if closed else pinproc.EventTypeSwitchOpenNondebounced)
        _switch_states(self)                # make sure _ap_states exists
        self._ap_states[num] = 1 if closed else 0
        self.add_switch_event(num, et)


def _set_active(sw, active, delay=0.0):
    """Queue `sw` going active/inactive after `delay` seconds (game-loop time)."""
    raw = (1 - _raw_inactive(sw)) if active else _raw_inactive(sw)
    if delay <= 0:
        _queue.put((sw.number, raw))
    else:
        _later.append((time.time() + delay, sw.number, raw))


_later = []


def _release_later():
    now = time.time()
    for item in [i for i in _later if i[0] <= now]:
        _later.remove(item)
        _queue.put(item[1:])


# The one piece of physics the rig models (AP_BALLS=0 turns it off): the
# trough.  Firing the trough's eject coil (pulse, patter - Houdini uses
# pulsed_patter) takes the ball off the eject switch, the rest roll down one
# place, and the ball lands in the shooter lane half a second later.
# Plunging it is `sw.py shooter open`.


def _name(x):
    return x if isinstance(x, basestring) else getattr(x, "name", None)


def _num(sw):
    digits = "".join(c for c in sw.name if c.isdigit())
    return int(digits) if digits else 0


def _trough_parts(g):
    """(eject coil name, position switches in the order balls sit - from
    the eject end to the ENTRY, where a drained ball lands - shooter switch)
    of the game's trough - SkeletonGame's Trough / Houdini's TroughHoudini
    (names) or ApiLib's TroughController (Hot Wheels on: objects, positions
    listed from the eject end).

    The entry matters: SkeletonGame only checks for a drain once a ball has
    come in there (its sw_trough6_active - trough7 on Houdini - sets
    ball_entered_trough); a count going up anywhere else is ignored.  It is
    the position the trough class has its own `sw_<name>_active` for (else
    the highest-numbered); the rest sit by their numbers, eject end first."""
    t = getattr(g, "trough", None)
    if t is None:
        return None, [], None
    if hasattr(t, "trough_device"):                         # ApiLib
        coil = _name(getattr(t, "release_coil", None) or getattr(t.trough_device, "release_coil", None))
        pos = [g.switches[_name(s)] for s in (t.trough_device.position_switches or [])
               if _name(s) in g.switches]
        entry = _name(getattr(t.trough_device, "entry_switch", None))
        shooter = _name(getattr(t, "shooter_switch", None))
    else:
        coil = getattr(t, "eject_coilname", None)
        pos = [g.switches[n] for n in (getattr(t, "position_switchnames", None) or [])
               if n in g.switches]
        eject = getattr(t, "eject_switchname", None)
        pos.sort(key=_num)
        if eject in g.switches and g.switches[eject] in pos:
            pos.remove(g.switches[eject])
            pos.insert(0, g.switches[eject])        # balls sit from the eject end
        entry = next((s.name for s in pos if hasattr(type(t), "sw_%s_active" % s.name)), None)
        if entry is None and pos:
            entry = max(pos[1:] or pos, key=_num).name
        shooter = getattr(t, "shooter_lane_switchname", None)
    pos = [s for s in pos if "jam" not in (getattr(s, "label", "") or s.name).lower()]
    if entry in [s.name for s in pos]:
        pos = [s for s in pos if s.name != entry] + [g.switches[entry]]
    return coil, pos, (g.switches[shooter] if shooter in g.switches else None)


def _trough_eject(g, pos, shooter):
    balls = sum(1 for s in pos if s.is_active())
    if not balls:
        log("trough: eject pulse with the trough empty")
        return
    for i, s in enumerate(pos):
        want = i < balls - 1
        if s.is_active() != want:
            _set_active(s, want, 0.0 if not want else 0.3)
    if shooter is not None:
        _set_active(shooter, True, 0.5)
    log("trough: ejected a ball, %d left%s" % (balls - 1, ", into " + shooter.name if shooter else ""))


def _trough_drain(g):
    """A ball drains the way a real one does: it lands on the trough's entry
    switch (the far end) and rolls down to the next free position (they fill
    from the eject end) - the entry is what makes the game look for a drain
    (_trough_parts)."""
    if g is None:
        return
    coil, pos, shooter = _trough_parts(g)
    balls = sum(1 for s in pos if s.is_active())
    if balls >= len(pos):
        log("trough: drain with the trough full")
        return
    entry = pos[-1]
    if not entry.is_active():
        _set_active(entry, True)
    for i, s in enumerate(pos):
        want = i <= balls
        if s is entry:
            if not want:
                _set_active(entry, False, 0.3)          # rolled on down
        elif s.is_active() != want:
            _set_active(s, want, 0.3)
    log("trough: drained a ball in at %s, %d in the trough" % (entry.name, balls + 1))


def _coil_fired(driver):
    g = _game[0]
    if g is None or os.environ.get("AP_BALLS", "1") == "0":
        return
    coil, pos, shooter = _trough_parts(g)
    if coil and driver.name == coil:
        _trough_eject(g, pos, shooter)


from procgame.game import gameitems as _gi


def _hook(cls, meth):
    orig = getattr(cls, meth)

    def fired(self, *a, **k):
        _coil_fired(self)
        return orig(self, *a, **k)
    setattr(cls, meth, fired)


for _m in ("pulse", "future_pulse", "patter", "pulsed_patter"):
    for _cls in (_gi.Driver, getattr(_gi, "VirtualDriver", None)):
        if _cls is not None and _m in _cls.__dict__:
            _hook(_cls, _m)


_ACTIVE = os.path.join(os.path.dirname(LOG), "active") if LOG else None
_active_seen = [0.0, None]


def _publish_active():
    """Rewrite `active` (the switch numbers the game has active) when they
    changed - at most five times a second."""
    now = time.time()
    g = _game[0]
    if not _ACTIVE or g is None or now - _active_seen[0] < 0.2:
        return
    _active_seen[0] = now
    try:
        line = " ".join(str(n) for n in sorted(sw.number for sw in g.switches if sw.is_active()))
    except Exception:                           # the game still setting up
        return
    if line != _active_seen[1]:
        _active_seen[1] = line
        with open(_ACTIVE + ".tmp", "w") as f:
            f.write(line + "\n")
        os.rename(_ACTIVE + ".tmp", _ACTIVE)


def get_events(self):
    _release_later()
    _inject(self)
    _publish_active()
    return _orig_get_events(self)


def get_events_noDMD(self):
    _release_later()
    _inject(self)
    _publish_active()
    return _orig_get_events_nodmd(self)


fakepinproc.FakePinPROC.switch_get_states = _switch_states
fakepinproc.FakePinPROC.get_events = get_events
fakepinproc.FakePinPROC.get_events_noDMD = get_events_noDMD
# FakePinPROC.__init__ binds get_events_noDMD to self.get_events when the
# config says use_virtual_dmd_only; the class attributes above are what it binds.


def _reader(path):
    """FIFO lines: `<switch> close|open|tap [ms]`; `<switch>` is a name or number."""
    while True:
        with open(path) as f:                   # blocks until a writer opens it
            for line in f:
                parts = line.split()
                if parts == ["!state"]:
                    _queue.put(("state", None))     # answered from the game loop
                    continue
                if parts == ["!drain"]:
                    log("sw: drain")
                    _queue.put(("drain", None))
                    continue
                if len(parts) < 2 or _game[0] is None:
                    continue
                name, act = parts[0], parts[1]
                try:
                    sw = _game[0].switches[int(name) if name.isdigit() else name]
                except (KeyError, ValueError):
                    log("sw: no switch %s" % name)
                    continue
                active = 1 - _raw_inactive(sw)
                log("sw: %s %s" % (sw.name, act))
                if act == "tap":
                    ms = int(parts[2]) if len(parts) > 2 else 150
                    _queue.put((sw.number, active))
                    time.sleep(ms / 1000.0)
                    _queue.put((sw.number, 1 - active))
                elif act in ("close", "on", "active"):
                    _queue.put((sw.number, active))
                elif act in ("open", "off", "inactive"):
                    _queue.put((sw.number, 1 - active))
                else:
                    log("sw: unknown action %s" % act)


def _postmortem(kind, value, tb):
    """--pm: on a crash, print the innermost frames' variables too (the
    bytecode has no source to read them from)."""
    import traceback
    traceback.print_exception(kind, value, tb)
    frames = []
    while tb:
        frames.append(tb.tb_frame)
        tb = tb.tb_next
    for fr in frames[-3:]:
        print("POSTMORTEM %s:%d %s" % (fr.f_code.co_filename, fr.f_lineno, fr.f_code.co_name))
        for k, v in sorted(fr.f_locals.items()):
            print("    %s = %.200r" % (k, v))


def main():
    if sys.argv[1] == "--pm":
        del sys.argv[1]
        sys.excepthook = _postmortem
    launcher = sys.argv[1]
    if os.environ.get("AP_PIDFILE"):
        with open(os.environ["AP_PIDFILE"], "w") as f:
            f.write("%d\n" % os.getpid())
    fifo = os.environ.get("AP_FIFO")
    if fifo:
        t = threading.Thread(target=_reader, args=(fifo,))
        t.daemon = True
        t.start()
    log("launch %s in %s" % (launcher, os.getcwd()))
    sys.argv = [launcher]
    g = {"__name__": "__main__", "__file__": launcher}
    execfile(launcher, g)


if __name__ == "__main__":
    main()
