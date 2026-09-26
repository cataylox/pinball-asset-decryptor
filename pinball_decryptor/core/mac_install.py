"""Install a Mac's missing host tools with the package manager it has.

Install Missing on the prerequisites strip used to be hidden on macOS, and
the gear menu's entry showed a box that said ``brew install gnupg ffmpeg``
and left the typing to the user.  A Mac that is handed a command to type is
being asked to do the app's job (David, 2026-08-19, on the Emulate tab's
"Set up emulator…"), so this does the work itself: the missing rows that
name a Mac package (:attr:`..core.prereqs.Prerequisite.mac_pkg`) become one
``brew install`` / ``port install`` run in the app's own log.

CHOSEN BY WHAT IS ALREADY ON THIS MAC.  Homebrew first because it never
runs as root and needs no password; MacPorts when that is what the machine
has (it installs system-wide, so macOS asks for the password once, in its
own dialog).  Neither is installed for the user here - without one there is
no plan, and the caller keeps its advice box.

The first Mac that needed this was cooltoy's, on Barrels of Fun (PAD-220):
gpg missing, the strip green, the Extract Failed box blaming the .fun file.
"""

import os
import shlex
import shutil
import subprocess
import tempfile
import time

from .prereqs import MAC_TOOL_DIRS

HOMEBREW_PATHS = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
MACPORTS_PATHS = ("/opt/local/bin/port",)

#: Homebrew formula -> MacPorts port, where the two spell a tool differently.
PORT_NAMES = {"gnupg": "gnupg2"}


def package_manager():
    """``(name, tool, admin)`` for the package manager this Mac has, or
    None: Homebrew (never root) ahead of MacPorts (needs admin)."""
    for p in HOMEBREW_PATHS:
        if os.path.isfile(p):
            return "Homebrew", p, False
    for p in MACPORTS_PATHS:
        if os.path.isfile(p):
            return "MacPorts", p, True
    return None


def install_plan(missing, manager=None):
    """What Install Missing will DO for the *missing* prerequisites, or None
    when none of them names a Mac package or this Mac has no package
    manager.

    Like the Emulate tab's ``engine_setup_plan``, the consent list and the
    work are ONE object: ``install`` is the argv, ``steps`` the sentences
    the dialog shows, and the package names tie the two together.
    """
    packages = []
    for p in missing:
        pkg = getattr(p, "mac_pkg", "") or ""
        if pkg and pkg not in packages:
            packages.append(pkg)
    if not packages:
        return None
    mgr = manager or package_manager()
    if mgr is None:
        return None
    name, tool, admin = mgr
    if name == "MacPorts":
        packages = [PORT_NAMES.get(p, p) for p in packages]
        # -N: no question this app cannot see gets asked half way through.
        install = [tool, "-N", "install"] + packages
    else:
        install = [tool, "install"] + packages
    label = " and ".join(packages)
    steps = ["Install %s with %s. Nothing already on this Mac is changed or "
             "removed." % (label, name)]
    if admin:
        steps.append("macOS will ask for your password once, in its own "
                     "dialog, because %s installs system-wide." % name)
    steps.append("Check the prerequisites again once it is done.")
    return {"manager": name, "packages": packages, "label": label,
            "admin": admin, "install": install, "steps": steps}


def run_plan(plan, log, popen=subprocess.Popen):
    """Run *plan*'s install, every line of its output to ``log(line)``.
    True when it finished with exit 0.  Blocks; call it off the UI thread."""
    argv = list(plan["install"])
    log(" ".join(shlex.quote(a) for a in argv))
    try:
        if plan.get("admin"):
            rc = _run_admin(argv, log, popen)
        else:
            rc = _run_plain(argv, log, popen)
    except OSError as exc:
        log("could not start %s: %s" % (argv[0], exc))
        return False
    if rc:
        log("%s did not finish (exit %s)." % (plan["label"], rc))
    return rc == 0


def _env():
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(MAC_TOOL_DIRS + (env.get("PATH", ""),))
    # Homebrew asks nothing when it knows nobody is there to answer.
    env["NONINTERACTIVE"] = "1"
    env["HOMEBREW_NO_ENV_HINTS"] = "1"
    return env


def _run_plain(argv, log, popen):
    proc = popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                 env=_env())
    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip() if isinstance(
            raw, bytes) else str(raw).rstrip()
        if line:
            log(line)
    return proc.wait()


def _run_admin(argv, log, popen):
    """The MacPorts case: macOS's own password dialog via osascript, the
    output tailed from a file since the elevated shell has no pipe to us."""
    work = tempfile.mkdtemp(prefix="pad_prereq_")
    script = os.path.join(work, "install.sh")
    out = os.path.join(work, "install.log")
    with open(script, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nexport PATH=%s:$PATH\n%s\n" % (
            shlex.quote(":".join(MAC_TOOL_DIRS)),
            " ".join(shlex.quote(a) for a in argv)))
    shell = "/bin/sh %s > %s 2>&1" % (shlex.quote(script), shlex.quote(out))
    osa = ('do shell script "%s" with administrator privileges'
           % shell.replace("\\", "\\\\").replace('"', '\\"'))
    try:
        proc = popen(["osascript", "-e", osa], stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE)
        seen = 0
        while proc.poll() is None:
            seen = _tail(out, seen, log)
            time.sleep(0.5)
        _tail(out, seen, log)
        err = (proc.stderr.read() or b"")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        if proc.returncode and err.strip():
            log(err.strip())
        return proc.returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _tail(path, seen, log):
    try:
        with open(path, "rb") as f:
            f.seek(seen)
            data = f.read()
    except OSError:
        return seen
    for line in data.decode("utf-8", "replace").splitlines():
        if line.strip():
            log(line.rstrip())
    return seen + len(data)
