"""Plumbing shared by the emulator control panels, parameterised on a rig.

There are two emulator rigs now - ``tools/spike2_emu`` for Stern Spike 2 and
``tools/jjp_emu`` for Jersey Jack - and both are Linux programs reached the
same way from Windows.  The parts that do not care WHICH rig they are talking
to live here so the two panels cannot drift apart on them.

That matters more than it sounds: the Spike 2 rig's own hardest-won rule is
*never let two scripts define the same fact* (``plans/TODO.md``), and it was
learned from ``alive.sh`` and ``killgame.sh`` disagreeing about what a running
rig is.  Two GUI panels each with their own idea of how to spell a WSL path is
the same mistake one level up.

What is deliberately NOT here: anything that knows a rig's directory, its
script names, its status vocabulary, or how it is launched.  Those genuinely
differ - Spike 2 runs a chroot under qemu-user and reaches macOS through a
container, JJP runs a native x86-64 binary and needs a USB dongle - and
pretending otherwise would produce a shared function with two unrelated halves.
"""

import subprocess
import sys

#: Never flash a console window when a helper runs.  A control surface that
#: blinks a black rectangle every poll is worse than one that is a little slow.
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def wsl_path(win_path):
    """``c:\\repo\\tools\\jjp_emu`` -> ``/mnt/c/repo/tools/jjp_emu``.

    A POSIX path has no drive letter and passes through untouched, so this is
    also correct on a Linux desktop where there is no translation to do.
    """
    p = (win_path or "").replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def linux_host_env(environ=None, scrubbed=None):
    """The ``env(1)`` arguments a rig needs on a Linux DESKTOP, or [] (PAD-291).

    Two things the AppImage gets wrong for the rig if left alone:

    * THE BUNDLE'S LIBRARIES LEAK INTO IT.  PyInstaller points
      ``LD_LIBRARY_PATH`` (and friends) at the AppImage, so the rig's system
      programs - bash, python3 + GTK for the playfield window, the GL host -
      load OUR older ``libmount.so.1`` beside the system's newer glib and fail
      before a window appears.  A user on Ubuntu 26.04 worked around it with
      ``LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libmount.so.1``; handing the rig
      the desktop's own environment (:func:`core.desktop.desktop_env`) is the
      fix that preload was standing in for.
    * WAYLAND.  The rig's windows are X11 programs (Xlib + EGL); on a Wayland
      session they belong on XWayland, so ``GDK_BACKEND=x11`` and
      ``EGL_PLATFORM=x11`` are pinned - only when XWayland is there
      (``DISPLAY`` set) and only where the user has not chosen already.

    ``-u NAME`` entries come first because env(1) takes its options before
    any ``NAME=value``.  Anything but Linux answers [] - WSL and the macOS
    container are Linux the app does not share an environment with.
    """
    if not sys.platform.startswith("linux"):
        return []
    import os
    from ..core import desktop
    environ = dict(os.environ if environ is None else environ)
    if scrubbed is None:
        scrubbed = desktop.desktop_env(environ)
    unset, assign = [], []
    for var in sorted(set(environ) | set(scrubbed)):
        if var in scrubbed and environ.get(var) == scrubbed[var]:
            continue
        if var in scrubbed:
            assign.append("%s=%s" % (var, scrubbed[var]))
        else:
            unset += ["-u", var]
    if environ.get("WAYLAND_DISPLAY") and environ.get("DISPLAY"):
        for var in ("GDK_BACKEND", "EGL_PLATFORM"):
            if not environ.get(var):
                assign.append(var + "=x11")
    return unset + assign


def rig_cmd(rig_dir, script, *args, env=(), distro=None):
    """Run one of ``rig_dir``'s scripts as the ordinary user.

    ``env`` is a list of ``NAME=value`` strings applied with ``env(1)`` rather
    than by a shell, because ``wsl.exe`` RE-PARSES its argument line: a ``$var``
    or ``$(subst)`` written into the command reaches the far side already
    expanded to nothing.  Every rig script that needs a value gets it this way.

    ``distro`` names the WSL distro to run in.  None means the machine's
    default, which is what every rig used before the app had a Linux of its own
    (core/runtime.py) - and is still what a rig whose tools the runtime image
    does not carry must use, which is why this is a per-call argument rather
    than a global switch.
    """
    if sys.platform == "win32":
        head = ["wsl.exe"] + (["-d", str(distro)] if distro else []) + ["-e"]
        path = "%s/%s" % (wsl_path(rig_dir), script)
    else:
        head = []
        path = "%s/%s" % (rig_dir, script)
    host = linux_host_env()
    if env or host:
        head = head + ["env"] + host + [str(e) for e in env]
    return head + ["bash", path] + [str(a) for a in args]


def rig_cmd_root(rig_dir, script, *args, env=(), distro=None):
    """The same script as root.  Windows only, and that is honest rather than
    a limitation settled for.

    ``wsl -u root`` is uid 0 with no password, because the Windows side is what
    launches the distro.  On a Linux desktop the equivalent is sudo, which
    wants a password a GUI app has nowhere to ask for without becoming an
    invisible hang.

    Kept separate from :func:`rig_cmd` rather than being a flag on it: the two
    are different privilege levels and a wrong argument must not be able to
    flip one into the other.
    """
    if sys.platform != "win32":
        raise RuntimeError("rig_cmd_root is WSL-only")
    head = ["wsl.exe"] + (["-d", str(distro)] if distro else [])         + ["-u", "root", "-e"]
    if env:
        head = head + ["env"] + [str(e) for e in env]
    return head + ["bash", "%s/%s" % (wsl_path(rig_dir), script)] + \
        [str(a) for a in args]


def parse_status(text):
    """Parse a rig ``status.sh``'s ``key=value`` output into a dict.

    Both rigs speak key=value for exactly this reason: a control surface must
    never have to parse prose.  Lines without an ``=`` are ignored rather than
    guessed at, so a script that prints a warning does not corrupt the reading.
    """
    info = {}
    for line in (text or "").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            info[key.strip()] = value.strip()
    return info
