#!/usr/bin/env python3
"""closewin.py <display> <name part> - press a window's X, the way a window
manager does: send WM_DELETE_WINDOW to every top-level window on <display>
whose name contains <name part>.  Prints what it closed; exit 1 if nothing
matched.  The rig's proof that closing a game window ends the run (PAD-292);
PAD-Runtime has no xdotool, so this is libX11 through ctypes.

    python3 closewin.py :141 "Legends of Valhalla"
"""
import ctypes
import sys

X = ctypes.CDLL("libX11.so.6")
X.XOpenDisplay.restype = ctypes.c_void_p
X.XOpenDisplay.argtypes = [ctypes.c_char_p]
X.XDefaultRootWindow.restype = ctypes.c_ulong
X.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
X.XInternAtom.restype = ctypes.c_ulong
X.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
X.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                         ctypes.POINTER(ctypes.c_ulong),
                         ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                         ctypes.POINTER(ctypes.c_uint)]
X.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_char_p)]
X.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long,
                         ctypes.c_void_p]
X.XFlush.argtypes = [ctypes.c_void_p]
X.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
                                 ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                                 ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                 ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                 ctypes.POINTER(ctypes.c_char_p)]
X.XCloseDisplay.argtypes = [ctypes.c_void_p]


class ClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("l", ctypes.c_long * 5)]


class XEvent(ctypes.Union):
    _fields_ = [("xclient", ClientMessage), ("pad", ctypes.c_long * 24)]


def children(d, w):
    r, p, kids, n = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
    if not X.XQueryTree(d, w, ctypes.byref(r), ctypes.byref(p), ctypes.byref(kids), ctypes.byref(n)):
        return []
    return [kids[i] for i in range(n.value)]


def title_of(d, w, net_name, utf8):
    """WM_NAME, else _NET_WM_NAME (SDL may set only the UTF-8 one)."""
    name = ctypes.c_char_p()
    if X.XFetchName(d, w, ctypes.byref(name)) and name.value:
        return name.value.decode("utf-8", "replace")
    typ, fmt, n, after, data = (ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(),
                                ctypes.c_ulong(), ctypes.c_char_p())
    if X.XGetWindowProperty(d, w, net_name, 0, 1024, 0, utf8, ctypes.byref(typ),
                            ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(after),
                            ctypes.byref(data)) == 0 and data.value:
        return data.value.decode("utf-8", "replace")
    return ""


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    d = X.XOpenDisplay(argv[0].encode())
    if not d:
        sys.exit("closewin.py: cannot open display %s" % argv[0])
    root = X.XDefaultRootWindow(d)
    protocols = X.XInternAtom(d, b"WM_PROTOCOLS", 0)
    delete = X.XInternAtom(d, b"WM_DELETE_WINDOW", 0)
    net_name = X.XInternAtom(d, b"_NET_WM_NAME", 0)
    utf8 = X.XInternAtom(d, b"UTF8_STRING", 0)
    closed = 0
    todo = children(d, root)
    while todo:
        w = todo.pop()
        todo.extend(children(d, w))
        title = title_of(d, w, net_name, utf8)
        if not title or argv[1] not in title:
            continue
        ev = XEvent()
        ev.xclient.type = 33                            # ClientMessage
        ev.xclient.window = w
        ev.xclient.message_type = protocols
        ev.xclient.format = 32
        ev.xclient.l[0] = delete
        X.XSendEvent(d, w, 0, 0, ctypes.byref(ev))
        print("closed %#x %s" % (w, title))
        closed += 1
    X.XFlush(d)
    X.XCloseDisplay(d)
    return 0 if closed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
