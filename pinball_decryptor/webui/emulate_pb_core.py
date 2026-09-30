"""Emulate tab for Pinball Brothers - the Tk-free facts of the rig in
``tools/pb_emu`` (the tab itself is ``webui/tabs/emulate_pb.py``).

Predator is two native x86-64 Linux programs (pinprog, the rules; vidprog,
the screen), so like Barrels of Fun and Spooky there is no CPU to emulate and
no key: the rig stands in for the boards the game talks to over USB serial
(a FAST Neuron with its I/O nodes and expansion boards).  See
``tools/pb_emu/README.md``.

ONE GAME SO FAR.  Predator is Pinball Brothers' only FAST machine; Alien,
Queen and ABBA run on PB's own I/O boards, a different rig.  The tab says so
up front and refuses their updates with that answer (``SUPPORTED``), rather
than failing inside the rig.

A Predator update is a FULL .upd and then DELTAS over it; a person picks the
version they want and the rig finds the rest of the chain beside it
(``tools/pb_emu/pbupdates.py``).

Everything that knows the rig's layout lives here, as the Spooky tab's does
in ``emulate_spooky_core``; how a script is invoked and how status is parsed
is ``webui/rig.py``'s, shared by every rig.
"""

import ntpath
import os
import pathlib
import re
import sys

from pinball_decryptor.core import runtime
from pinball_decryptor.webui import rig as _rig

#: The rig ships next to this package.  ``PAD_PB_EMU_DIR`` moves it.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "pb_emu"
)

POLL_MS = 2000
POLL_IDLE_MS = 10000
POLL_FIRST_MS = 700

#: The Pinball Brothers games the emulator runs: (display name, the start
#: of their update files' names).
SUPPORTED = (("Predator", "pbpp_predator_game_"),)

#: watch.sh's step headers -> the footer ladder (copy = first chip).
FOOTER_STEPS = (("== Setup ==", "copy", 0,
                 "Setting up the emulator (once, about 700 MB)…"),
                ("== Unpack ==", "copy", 0, "Unpacking the game…"),
                ("== Board ==", "boot", None, "Starting the board…"),
                ("== Game ==", "techalerts", None,
                 "Starting the game (under a minute)…"),
                ("== Ready ==", "run", None, "Game running"))
PHASES = ("Unpack", "Board", "Game", "Ready")

#: watch.sh's exit codes that mean something a user can act on.
EXIT_TEXT = {
    3: "Not enough free space in the app's Linux to unpack this update.",
    4: "This file is not a Predator update. Predator is the only Pinball "
       "Brothers game the emulator runs so far (Alien, Queen and ABBA run on "
       "different boards).",
    5: "The update could not be unpacked, or holds no game program - if you "
       "picked a delta (pbpp_predator_game_1_0_1.upd), the full update it "
       "builds on (pbpp_predator_game_1_0.upd) must be in the same folder.",
    6: "The game did not reach attract mode.",
    7: "The emulator's one-time setup did not finish (it downloads about "
       "700 MB) - check the connection and press Start again.",
}

SETUP_LABEL = "Set up emulator…"
SETUP_BUSY = "Setting up…"

_VERSION = re.compile(r"_game_(\d+(?:_\d+)*)\.upd$", re.I)


def _base(path):
    """The file's name, whichever separator the path uses: a Windows path
    (a file picked on Select card) must read the same in a test on Linux."""
    return ntpath.basename(path or "")


def supported_names():
    return [name for name, _pre in SUPPORTED]


def supported_file(path):
    """Is *path* an update of a game the emulator runs?  By name, the way
    Pinball Brothers names its update files."""
    base = _base(path).lower()
    return base.endswith(".upd") and any(base.startswith(pre)
                                         for _name, pre in SUPPORTED)


def title_of(path):
    """The game a supported update is for, else ""."""
    base = _base(path).lower()
    return next((name for name, pre in SUPPORTED if base.startswith(pre)), "")


def version_of(path):
    """pbpp_predator_game_1_0_1.upd -> "1.0.1" (else "")."""
    m = _VERSION.search(_base(path))
    return m.group(1).replace("_", ".") if m else ""


def rig_dir():
    return os.environ.get("PAD_PB_EMU_DIR") or DEFAULT_RIG_DIR


def rig_available():
    """Present?  Checked by script, not by directory - a half-copied tools
    tree is the failure this catches.  The switch window and the volume
    holder live in the AP and Spooky rigs."""
    d = rig_dir()
    tools = os.path.dirname(d)
    return (all(os.path.isfile(os.path.join(d, s))
                for s in ("watch.sh", "stop.sh", "status.sh", "cancel.sh",
                          "cache.sh", "ctl.sh", "setup.sh", "prepare.sh",
                          "run_game.sh", "pbshim.so", "pbfast.py",
                          "pbctl.py", "pbswitches.py", "pbpf.py", "pbvol.py",
                          "pbtitles.py", "pbupdates.py"))
            and os.path.isfile(os.path.join(tools, "ap_emu", "appf.py"))
            and os.path.isfile(os.path.join(tools, "spooky_emu", "spkvol.py")))


def platform_ok():
    """watch.sh runs as root, and only WSL gives the app a root without a
    password prompt (``webui/rig.rig_cmd_root``) - so Windows only.  A
    function, not an inline test, so tests stub THIS rather than faking
    ``sys.platform``."""
    return sys.platform == "win32"


def rig_distro():
    """The app's own Linux when it is installed, else the machine's
    default."""
    return runtime.distro_for("pb")


def rig_cmd(*args, **kw):
    kw.setdefault("distro", rig_distro())
    return _rig.rig_cmd(rig_dir(), *args, **kw)


def rig_cmd_root(*args, **kw):
    kw.setdefault("distro", rig_distro())
    return _rig.rig_cmd_root(rig_dir(), *args, **kw)


def mem_text(kb):
    """The game's memory: pinprog is small (tens of MB), so MB below 1 GB."""
    kb = int(kb or 0)
    if not kb:
        return ""
    if kb < 1048576:
        return "%d MB" % max(1, round(kb / 1024.0))
    return "%.1f GB" % (kb / 1048576.0)


def state_text(info):
    """(label, hint) for the headline, first problem first."""
    if not info:
        return "Checking…", ""
    if info.get("wsl") != "1":
        return ("WSL not answering",
                "The game runs inside WSL, the app's Linux.")
    if info.get("running") == "1":
        name = info.get("title_name") or "Predator"
        if info.get("attract") != "1":
            return ("Starting", "%s is loading…" % name)
        bits = [name]
        if info.get("version"):
            bits.append(info["version"])
        if mem_text(info.get("rss_kb")):
            bits.append(mem_text(info.get("rss_kb")))
        up = int(info.get("uptime_s") or 0)
        if up:
            bits.append("%d:%02d" % (up // 60, up % 60))
        return "Running", "  ·  ".join(bits)
    return "Stopped", ""


def setup_notice(info, rt_state, can_install=True):
    """``(text, button)`` for the tab's setup notice, as the AP tab's
    (``emulate_ap_core.setup_notice``): what is not set up, and whether "Set
    up emulator…" can fix it.  ``("", False)`` when nothing is wrong (or
    nothing is known yet)."""
    if rt_state == "foreign":
        from . import runtime_prompt
        return runtime_prompt.notice("foreign", ""), False
    if rt_state in ("absent", "stale") and can_install:
        what = ("is not on this PC yet" if rt_state == "absent"
                else "is from an older version of this app")
        return ("Not set up: the Linux this app installs for its emulators "
                "%s, so the game would run in this PC's own WSL distro "
                "instead, which this emulator is not built for. Press "
                "“Set up emulator…” to install it and the libraries "
                "the game runs on (one-time downloads, about 1.2 GB)." % what,
                True)
    if (info or {}).get("wsl") == "1" and info.get("ready") == "0":
        return ("Not set up yet: the emulator still needs the libraries the "
                "game runs on (about 700 MB, once). Press “Set up "
                "emulator…” now, or the first Start does it.", True)
    return "", False


def parse_cache(text):
    """``cache.sh --list`` -> ``(entries, disk)``: the AP rig's protocol, so
    its parser (and the AP tab's Cache window) serve this tab too."""
    from .emulate_ap_core import parse_cache as _parse
    return _parse(text)


def cache_label(entry):
    """What the Cache window calls an entry: predator_1_0_1-028700ac ->
    Predator 1.0.1; the setup -> the libraries."""
    name = entry["name"]
    if entry.get("kind") == "setup" or name == "setup":
        return "Emulator setup (the game's libraries)"
    m = re.match(r"^([a-z]+)_([0-9_]+)-[0-9a-f]+$", name)
    if m:
        return "%s %s" % (m.group(1).title(), m.group(2).replace("_", "."))
    return name
