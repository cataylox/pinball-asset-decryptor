#!/usr/bin/env python3
"""spkwin.py - let the game's window on the desktop be resized.

    spkwin.py --display :0 --mark SPK_MARK=/var/tmp/pad_spooky/rig0
              --pidfile /var/tmp/pad_spooky/rig0/game.pid

David, PAD-321: every Spooky game must "display in a window that I can move
around and resize".  The Unity titles (all but Looney Tunes) are built not
resizable - a cabinet's screen has nothing else on it - and Unity says so
the X way, in WM_NORMAL_HINTS: minimum size = maximum size = the window's
size.  The desktop's window manager then refuses every drag of an edge.
Unity has no command-line switch for it, and it asks libX11 through
dlsym, which an LD_PRELOAD shim cannot see.  But the hints are only advice
to the window manager, and the player itself draws whatever size its window
is (Beetlejuice measured: resized to 960x540 it scales the whole picture).
So this clears the minimum and maximum from the hints of every window the
game owns, and again whenever the game sets them back.  Looney Tunes
(Godot) never sets them, and is left alone.

The game's windows are found by the rig's mark in the owning process's
environment (_NET_WM_PID), as gamekeys.py finds them.  It ends when the game
(--pidfile) does.  Only libX11, through ctypes: no packages to install.
"""
import argparse
import ctypes
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ap_emu"))
from gamekeys import _ERR, _x11, alive, marked  # noqa: E402

PMinSize, PMaxSize = 1 << 4, 1 << 5
RESCAN_S = 1.0


class XSizeHints(ctypes.Structure):
    """Xutil.h's XSizeHints."""
    _fields_ = [("flags", ctypes.c_long), ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("min_width", ctypes.c_int), ("min_height", ctypes.c_int),
                ("max_width", ctypes.c_int), ("max_height", ctypes.c_int),
                ("width_inc", ctypes.c_int), ("height_inc", ctypes.c_int),
                ("min_aspect_x", ctypes.c_int), ("min_aspect_y", ctypes.c_int),
                ("max_aspect_x", ctypes.c_int), ("max_aspect_y", ctypes.c_int),
                ("base_width", ctypes.c_int), ("base_height", ctypes.c_int),
                ("win_gravity", ctypes.c_int)]


def unlocked(flags):
    """The hints' flags without a minimum or maximum size, or None when
    there is neither (nothing to change)."""
    if not flags & (PMinSize | PMaxSize):
        return None
    return flags & ~(PMinSize | PMaxSize)


class Display:
    def __init__(self, name):
        x = self.x = _x11()
        x.XGetWMNormalHints.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                        ctypes.POINTER(XSizeHints),
                                        ctypes.POINTER(ctypes.c_long)]
        x.XSetWMNormalHints.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                        ctypes.POINTER(XSizeHints)]
        self.dpy = x.XOpenDisplay(name.encode())
        if not self.dpy:
            raise SystemExit("spkwin: cannot open display %s" % name)
        x.XSetErrorHandler(_ERR)            # a window may vanish mid-query
        self.root = x.XDefaultRootWindow(self.dpy)
        self.pid_atom = x.XInternAtom(self.dpy, b"_NET_WM_PID", 0)

    def _pid(self, w):
        t, fmt = ctypes.c_ulong(), ctypes.c_int()
        n, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        if self.x.XGetWindowProperty(self.dpy, w, self.pid_atom, 0, 1, 0, 0,
                                     ctypes.byref(t), ctypes.byref(fmt),
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

    def windows(self, mark):
        """The windows of a marked process: the first one down each branch
        (on the desktop the window manager has framed them)."""
        mine, stack = [], self._children(self.root)
        while stack:
            w = stack.pop()
            pid = self._pid(w)
            if pid and marked(pid, mark):
                mine.append(w)
            else:
                stack.extend(self._children(w))
        return mine

    def unlock(self, w):
        """Clear the window's minimum and maximum size -> what it was, or None."""
        h, supplied = XSizeHints(), ctypes.c_long()
        if not self.x.XGetWMNormalHints(self.dpy, w, ctypes.byref(h), ctypes.byref(supplied)):
            return None
        flags = unlocked(h.flags)
        if flags is None:
            return None
        was = "%dx%d..%dx%d" % (h.min_width, h.min_height, h.max_width, h.max_height)
        h.flags = flags
        self.x.XSetWMNormalHints(self.dpy, w, ctypes.byref(h))
        self.x.XFlush(self.dpy)
        return was


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--display", required=True)
    ap.add_argument("--mark", required=True, help="NAME=value in the game's environment")
    ap.add_argument("--pidfile", required=True, help="ends when this pid ends")
    a = ap.parse_args(argv)

    def say(text):
        print("%s spkwin: %s" % (time.strftime("%H:%M:%S"), text), flush=True)

    for _ in range(600):                       # the game comes up
        if alive(a.pidfile):
            break
        time.sleep(0.2)
    else:
        say("the game never came up")
        return 1
    disp = Display(a.display)
    gone = 0
    while gone < 3:
        for w in disp.windows(a.mark):
            was = disp.unlock(w)
            if was:
                say("window 0x%x resizable (its size was held to %s)" % (w, was))
        gone = 0 if alive(a.pidfile) else gone + 1
        time.sleep(RESCAN_S)
    say("the game ended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
