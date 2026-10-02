#!/usr/bin/env python3
"""gamekeys.py - the playfield window's keys in the GAME's own window too.

    gamekeys.py --display :0 --mark PB_MARK=/var/tmp/pad_pb/rig0
                --sock /var/tmp/pad_pb/rig0/ctl.sock --pidfile .../game.pid
                (--table switches.json | --bof-profile dune) [--skip "Enter Space"]

David, 2026-10-02 (PAD-313): "keyboard events should be registered when i
focus in the display window too. this should be common on all of our
emulators".  Stern, Spike 1, JJP, AP and Dutch Pinball already had it, each
its own way; the Pinball Brothers, Spooky and Barrels of Fun games have no
keys of their own (on the machine every input is a switch), so a key pressed
in their window did nothing.  This is the one listener those rigs share.

How: an ordinary X client on the game's display.  It finds the game's
windows by the rig's mark in the owning process's environment (the window's
_NET_WM_PID), and selects KeyPress / KeyRelease / FocusChange on them.  X
lets any number of clients select key events on a window, so the game still
gets every key it got before; nothing is grabbed, and keys in any other
window on the desktop are never seen.  A key is looked up in the same keymap
the playfield window uses (appf's: [{codes, ns, action}], browser
KeyboardEvent.code names) and sent to the rig's board on its ctl.sock in the
line protocol all three boards speak: `sw <n> 1|0` while held, `plunge`,
`drain`, `reset`, `pause 0|1`.  Losing focus releases every held switch.

It ends by itself when the game (--pidfile) ends.  Only libX11, through
ctypes: no packages to install.
"""
import argparse
import ctypes
import ctypes.util
import json
import os
import select
import socket
import sys
import time

KeyPress, KeyRelease, FocusOut = 2, 3, 10
KeyPressMask, KeyReleaseMask = 1 << 0, 1 << 1
FocusChangeMask = 1 << 21
AnyPropertyType = 0
RESCAN_S = 1.0

# --------------------------------------------------------------- keysyms -> codes
_NAMED = {
    0x20: "Space", 0x27: "Quote", 0x2c: "Comma", 0x2d: "Minus", 0x2e: "Period",
    0x2f: "Slash", 0x3b: "Semicolon", 0x3d: "Equal", 0x5b: "BracketLeft",
    0x5c: "Backslash", 0x5d: "BracketRight", 0x60: "Backquote",
    0xff08: "Backspace", 0xff09: "Tab", 0xff0d: "Enter", 0xff13: "Pause",
    0xff1b: "Escape", 0xff51: "ArrowLeft", 0xff52: "ArrowUp",
    0xff53: "ArrowRight", 0xff54: "ArrowDown", 0xff8d: "NumpadEnter",
    0xffab: "NumpadAdd", 0xffad: "NumpadSubtract", 0xffaa: "NumpadMultiply",
    0xffaf: "NumpadDivide", 0xffae: "NumpadDecimal",
    0xffe1: "ShiftLeft", 0xffe2: "ShiftRight", 0xffe3: "ControlLeft",
    0xffe4: "ControlRight", 0xffe9: "AltLeft", 0xffea: "AltRight",
}


def code_of(keysym):
    """An X keysym (unshifted) -> the browser KeyboardEvent.code the keymaps
    use, or ""."""
    if 0x61 <= keysym <= 0x7a:
        return "Key" + chr(keysym - 0x20)
    if 0x41 <= keysym <= 0x5a:
        return "Key" + chr(keysym)
    if 0x30 <= keysym <= 0x39:
        return "Digit" + chr(keysym)
    if 0xffb0 <= keysym <= 0xffb9:
        return "Numpad%d" % (keysym - 0xffb0)
    if 0xffbe <= keysym <= 0xffc9:
        return "F%d" % (keysym - 0xffbe + 1)
    return _NAMED.get(keysym, "")


# --------------------------------------------------------------- the keymaps
def keymap_from_table(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("keymap") or []


def keymap_from_bof(title):
    """Barrels of Fun's playfield window keeps its keys in bofpf.py (profile
    key -> codes) and its page (P plunge, D drain): the same map here."""
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(here), "bof_emu"))
    import bofpf                                     # noqa: E402
    model = bofpf.page_model(bofpf.load_profile(title))
    km = [{"codes": r["codes"], "ns": [r["n"]], "action": None}
          for r in model["switches"] if r["codes"]]
    km.append({"codes": ["KeyP"], "ns": [], "action": "plunge"})
    km.append({"codes": ["KeyD"], "ns": [], "action": "drain"})
    return km


# --------------------------------------------------------------- the board
class Board:
    """The rig's ctl.sock: one line out, one line back."""

    def __init__(self, path):
        self.path = path
        self.s = None
        self.f = None

    def ask(self, line):
        for _attempt in (1, 2):
            try:
                if self.s is None:
                    self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.s.settimeout(3)
                    self.s.connect(self.path)
                    self.f = self.s.makefile("r", encoding="utf-8", errors="replace")
                self.s.sendall((line + "\n").encode())
                return self.f.readline().strip()
            except OSError:
                try:
                    if self.s is not None:
                        self.s.close()
                except OSError:
                    pass
                self.s = self.f = None
        return ""


class Keys:
    """Key events -> board requests, as appf.App.key does for its window."""

    def __init__(self, keymap, board, skip=(), say=print):
        self.keymap = keymap
        self.board = board
        self.skip = set(skip)
        self.held = {}                 # code -> switch numbers held for it
        self.paused = False
        self.say = say

    def key(self, code, down):
        if not code or code in self.skip:
            return False
        for k in self.keymap:
            if code not in k.get("codes", ()):
                continue
            act = k.get("action")
            if act:
                if down and code not in self.held:
                    self.held[code] = []
                    if act == "pause":
                        self.paused = not self.paused
                        self.board.ask("pause %d" % (1 if self.paused else 0))
                    elif act in ("plunge", "drain", "reset"):
                        self.board.ask(act)
                    self.say("key %s -> %s" % (code, act))
                elif not down:
                    self.held.pop(code, None)
                return True
            ns = list(k.get("ns") or [])
            if down:
                if code in self.held:          # auto-repeat
                    return True
                self.held[code] = ns
                for n in ns:
                    self.board.ask("sw %d 1" % n)
                self.say("key %s down -> sw %s" % (code, ns))
            else:
                for n in self.held.pop(code, ns):
                    self.board.ask("sw %d 0" % n)
            return True
        return False

    def release_all(self):
        for code in list(self.held):
            self.key(code, False)


# --------------------------------------------------------------- X11
class XKeyEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
                ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
                ("state", ctypes.c_uint), ("keycode", ctypes.c_uint),
                ("same_screen", ctypes.c_int)]


class XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xkey", XKeyEvent),
                ("pad", ctypes.c_long * 24)]


def _x11():
    x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                             ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                             ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                             ctypes.POINTER(ctypes.c_uint)]
    x.XGetWindowProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
        ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_void_p)]
    x.XFree.argtypes = [ctypes.c_void_p]
    x.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
    x.XPending.argtypes = [ctypes.c_void_p]
    x.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(XEvent)]
    x.XLookupKeysym.restype = ctypes.c_ulong
    x.XLookupKeysym.argtypes = [ctypes.POINTER(XKeyEvent), ctypes.c_int]
    x.XConnectionNumber.argtypes = [ctypes.c_void_p]
    x.XFlush.argtypes = [ctypes.c_void_p]
    x.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    x.XkbSetDetectableAutoRepeat.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    return x


_ERR = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda d, e: 0)


def marked(pid, mark):
    """Does process *pid* carry the rig's mark (NAME=value) in its environment?"""
    try:
        with open("/proc/%d/environ" % pid, "rb") as f:
            return mark.encode() in f.read().split(b"\0")
    except OSError:
        return False


class Display:
    def __init__(self, name):
        self.x = _x11()
        self.dpy = self.x.XOpenDisplay(name.encode())
        if not self.dpy:
            raise SystemExit("gamekeys: cannot open display %s" % name)
        # a window that vanishes between a query and a select must not kill us
        self.x.XSetErrorHandler(_ERR)
        # held keys repeat as presses only, not release+press pairs
        self.x.XkbSetDetectableAutoRepeat(self.dpy, 1, None)
        self.root = self.x.XDefaultRootWindow(self.dpy)
        self.pid_atom = self.x.XInternAtom(self.dpy, b"_NET_WM_PID", 0)
        self.watched = set()

    def _pid(self, w):
        t, fmt = ctypes.c_ulong(), ctypes.c_int()
        n, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        if self.x.XGetWindowProperty(self.dpy, w, self.pid_atom, 0, 1, 0,
                                     AnyPropertyType, ctypes.byref(t), ctypes.byref(fmt),
                                     ctypes.byref(n), ctypes.byref(after),
                                     ctypes.byref(data)) != 0 or not data.value:
            return 0
        pid = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0] if n.value else 0
        self.x.XFree(data)
        return int(pid)

    def _children(self, w):
        root, parent = ctypes.c_ulong(), ctypes.c_ulong()
        kids, n = ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
        if not self.x.XQueryTree(self.dpy, w, ctypes.byref(root), ctypes.byref(parent),
                                 ctypes.byref(kids), ctypes.byref(n)):
            return []
        out = [kids[i] for i in range(n.value)]
        if kids:
            self.x.XFree(kids)
        return out

    def scan(self, mark):
        """Select key events on every window of a marked process (and its
        children: a toolkit may give the focus to a child)."""
        found = []
        stack = list(self._children(self.root))
        while stack:
            w = stack.pop()
            pid = self._pid(w)
            if pid and marked(pid, mark):
                found.append(w)
                found.extend(self._children(w))
            else:
                stack.extend(self._children(w))
        new = [w for w in found if w not in self.watched]
        for w in new:
            self.x.XSelectInput(self.dpy, w, KeyPressMask | KeyReleaseMask | FocusChangeMask)
            self.watched.add(w)
        if new:
            self.x.XFlush(self.dpy)
        return new

    def events(self, timeout):
        fd = self.x.XConnectionNumber(self.dpy)
        if not self.x.XPending(self.dpy):
            select.select([fd], [], [], timeout)
        ev = XEvent()
        while self.x.XPending(self.dpy):
            self.x.XNextEvent(self.dpy, ctypes.byref(ev))
            if ev.type in (KeyPress, KeyRelease):
                sym = self.x.XLookupKeysym(ctypes.byref(ev.xkey), 0)
                yield ev.type == KeyPress, code_of(sym)
            elif ev.type == FocusOut:
                yield None, ""


def alive(pidfile):
    try:
        with open(pidfile) as f:
            pid = int(f.read().strip() or 0)
        return pid > 0 and os.path.exists("/proc/%d" % pid)
    except (OSError, ValueError):
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--display", required=True)
    ap.add_argument("--mark", required=True, help="NAME=value in the game's environment")
    ap.add_argument("--sock", required=True, help="the rig's board ctl.sock")
    ap.add_argument("--pidfile", required=True, help="ends when this pid ends")
    ap.add_argument("--table", help="switches.json with a keymap (PB, Spooky)")
    ap.add_argument("--bof-profile", help="a Barrels of Fun title (dune...)")
    ap.add_argument("--skip", default="", help="codes the game handles itself")
    a = ap.parse_args(argv)

    def say(text):
        print("%s gamekeys: %s" % (time.strftime("%H:%M:%S"), text), flush=True)

    for _ in range(600):                       # the game and its table come up
        if alive(a.pidfile) and (a.bof_profile or (a.table and os.path.isfile(a.table))):
            break
        time.sleep(0.2)
    else:
        say("the game never came up - nothing to listen to")
        return 1
    keymap = keymap_from_bof(a.bof_profile) if a.bof_profile else keymap_from_table(a.table)
    keys = Keys(keymap, Board(a.sock), a.skip.split(), say)
    disp = Display(a.display)
    say("listening on %s for %s (%d keys%s)" % (
        a.display, a.mark, sum(len(k.get("codes", ())) for k in keymap),
        ", the game's own: " + a.skip if a.skip else ""))
    next_scan, gone = 0.0, 0
    try:
        while True:
            now = time.monotonic()
            if now >= next_scan:
                next_scan = now + RESCAN_S
                for w in disp.scan(a.mark):
                    say("watching window 0x%x" % w)
                gone = 0 if alive(a.pidfile) else gone + 1
                if gone >= 3:
                    say("the game ended")
                    return 0
            for down, code in disp.events(RESCAN_S):
                if down is None:
                    keys.release_all()
                else:
                    keys.key(code, down)
    finally:
        keys.release_all()


if __name__ == "__main__":
    sys.exit(main())
