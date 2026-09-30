"""Emulate tab for Spooky Pinball - the Tk-free facts of the rig in
``tools/spooky_emu`` (the tab itself is ``webui/tabs/emulate_spooky.py``).

Beetlejuice is a native x86-64 Linux Unity game with a desktop mode of its
own, so like Barrels of Fun there is no CPU to emulate and no key: the rig
stands in for the one board it talks to over USB serial (Spooky's "Warden"
playfield controller).  See ``tools/spooky_emu/README.md``.

ONE GAME SO FAR.  Spooky makes a dozen titles on three engines; only
Beetlejuice has been brought up.  The tab says so up front and refuses any
other update with that answer (``SUPPORTED``), rather than failing inside
the rig.

Everything that knows the rig's layout lives here, as the BoF tab's does in
``emulate_bof_core``; how a script is invoked and how status is parsed is
``webui/rig.py``'s, shared by every rig.
"""

import json
import os
import pathlib
import sys

from pinball_decryptor.core import runtime
from pinball_decryptor.webui import rig as _rig

#: The rig ships next to this package.  ``PAD_SPOOKY_EMU_DIR`` moves it.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "spooky_emu"
)

POLL_MS = 2000
POLL_IDLE_MS = 10000
POLL_FIRST_MS = 700

#: The Spooky games the emulator runs: (display name, update file suffix).
SUPPORTED = (("Beetlejuice", ".beetlejuice"),)

#: watch.sh's step headers -> the footer ladder (copy = first chip).
FOOTER_STEPS = (("== Unpack ==", "copy", 0, "Unpacking the game…"),
                ("== Board ==", "boot", None, "Starting the board…"),
                ("== Game ==", "techalerts", None,
                 "Starting the game (a minute or two)…"),
                ("== Ready ==", "run", None, "Game running"))
PHASES = ("Unpack", "Board", "Game", "Ready")

#: watch.sh's exit codes that mean something a user can act on.
EXIT_TEXT = {
    3: "Not enough free space in the app's Linux to unpack this update.",
    4: "This file is not a Beetlejuice update, or it is damaged. Beetlejuice "
       "is the only Spooky game the emulator runs so far.",
    5: "The file opened but holds no game program.",
    6: "The game did not reach attract mode.",
}


def supported_names():
    return [name for name, _ext in SUPPORTED]


def supported_file(path):
    """Is *path* an update of a game the emulator runs?  By suffix, the way
    the machine itself tells its update files apart."""
    p = (path or "").lower()
    return any(p.endswith(ext) for _name, ext in SUPPORTED)


def rig_dir():
    return os.environ.get("PAD_SPOOKY_EMU_DIR") or DEFAULT_RIG_DIR


def rig_available():
    """Present?  Checked by script, not by directory - a half-copied tools
    tree is the failure this catches."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, s))
               for s in ("watch.sh", "stop.sh", "status.sh", "cancel.sh",
                         "cache.sh", "ctl.sh", "spkshim.so", "spkwarden.py",
                         "spkswitches.py", "spkpf.py", "spkvol.py",
                         "spktitles.py"))


def platform_ok():
    """watch.sh runs as root, and only WSL gives the app a root without a
    password prompt (``webui/rig.rig_cmd_root``) - so Windows only.  A
    function, not an inline test, so tests stub THIS rather than faking
    ``sys.platform``."""
    return sys.platform == "win32"


def rig_distro():
    """The app's own Linux when it is installed (it carries gpg, Xvfb and
    Mesa, and has room for a 5 GB game), else the machine's default."""
    return runtime.distro_for("spooky")


def rig_cmd(*args, **kw):
    kw.setdefault("distro", rig_distro())
    return _rig.rig_cmd(rig_dir(), *args, **kw)


def rig_cmd_root(*args, **kw):
    kw.setdefault("distro", rig_distro())
    return _rig.rig_cmd_root(rig_dir(), *args, **kw)


def state_text(info):
    """(label, hint) for the headline, first problem first."""
    if not info:
        return "Checking…", ""
    if info.get("wsl") != "1":
        return ("WSL not answering",
                "The game runs inside WSL, the app's Linux.")
    if info.get("running") == "1":
        if info.get("attract") != "1":
            return ("Starting", "Beetlejuice is loading…")
        bits = ["Beetlejuice"]
        if info.get("version"):
            bits.append(info["version"])
        rss = int(info.get("rss_kb") or 0)
        if rss:
            bits.append("%.1f GB" % (rss / 1048576.0))
        up = int(info.get("uptime_s") or 0)
        if up:
            bits.append("%d:%02d" % (up // 60, up % 60))
        return "Running", "  ·  ".join(bits)
    return "Stopped", ""


def parse_cache(text):
    """``cache.sh --list`` -> ``(entries, disk)``: the AP rig's protocol, so
    its parser (and the AP tab's Cache window) serve this tab too."""
    from .emulate_ap_core import parse_cache as _parse
    return _parse(text)


def cache_label(entry):
    """What the Cache window calls an entry: bj_v2026.09.15.11 ->
    Beetlejuice v2026.09.15.11."""
    name = entry["name"]
    if name.startswith("bj_"):
        return "Beetlejuice " + name[3:]
    return name
