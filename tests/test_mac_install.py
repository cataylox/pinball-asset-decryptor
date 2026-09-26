"""Install Missing on a Mac installs the missing host tools itself
(core.mac_install) - PAD-220, where a Mac without gpg was told to check its
.fun file for corruption.  No real brew, no real Mac needed."""

import io
import sys
import time

from pinball_decryptor.core import mac_install
from pinball_decryptor.core.prereqs import Prerequisite, PrerequisiteResult

GPG = Prerequisite(name="gpg", where="native", probe="command -v gpg",
                   reason="x", install_hint="brew install gnupg",
                   mac_pkg="gnupg")
TAR = Prerequisite(name="tar", where="native", probe="command -v tar",
                   reason="x")
BREW = ("Homebrew", "/opt/homebrew/bin/brew", False)
PORT = ("MacPorts", "/opt/local/bin/port", True)


def test_plan_is_the_argv_and_the_sentences_for_homebrew():
    plan = mac_install.install_plan([GPG, TAR], manager=BREW)
    assert plan["install"] == ["/opt/homebrew/bin/brew", "install", "gnupg"]
    assert plan["admin"] is False
    assert plan["packages"] == ["gnupg"]
    assert "gnupg" in plan["steps"][0] and "Homebrew" in plan["steps"][0]
    assert not any("password" in s for s in plan["steps"])


def test_macports_spells_the_port_and_asks_for_the_password_once():
    plan = mac_install.install_plan([GPG], manager=PORT)
    assert plan["install"] == ["/opt/local/bin/port", "-N", "install",
                               "gnupg2"]
    assert plan["admin"] is True
    assert any("password" in s for s in plan["steps"])


def test_no_plan_without_a_mac_package_or_a_manager(monkeypatch):
    assert mac_install.install_plan([TAR], manager=BREW) is None
    assert mac_install.install_plan([], manager=BREW) is None
    monkeypatch.setattr(mac_install, "package_manager", lambda: None)
    assert mac_install.install_plan([GPG]) is None


def test_package_manager_prefers_homebrew(monkeypatch):
    monkeypatch.setattr(mac_install.os.path, "isfile",
                        lambda p: p in ("/usr/local/bin/brew",
                                        "/opt/local/bin/port"))
    assert mac_install.package_manager() == (
        "Homebrew", "/usr/local/bin/brew", False)
    monkeypatch.setattr(mac_install.os.path, "isfile",
                        lambda p: p == "/opt/local/bin/port")
    assert mac_install.package_manager() == PORT
    monkeypatch.setattr(mac_install.os.path, "isfile", lambda p: False)
    assert mac_install.package_manager() is None


class _Proc:
    def __init__(self, lines, rc):
        self.stdout = io.BytesIO(b"".join(l + b"\n" for l in lines))
        self._rc = rc

    def wait(self):
        return self._rc


def test_run_plan_streams_every_line_into_the_log_and_reports_the_exit():
    plan = mac_install.install_plan([GPG], manager=BREW)
    calls = []
    lines = []

    def popen(argv, **kw):
        calls.append((argv, kw))
        return _Proc([b"==> Downloading gnupg", b"==> Pouring gnupg"], 0)

    assert mac_install.run_plan(plan, lines.append, popen=popen) is True
    assert calls[0][0] == plan["install"]
    # brew runs with the Mac tool folders on PATH and never asks a question
    env = calls[0][1]["env"]
    assert env["PATH"].startswith("/opt/homebrew/bin")
    assert env["NONINTERACTIVE"] == "1"
    assert "==> Pouring gnupg" in lines

    lines.clear()
    assert mac_install.run_plan(
        plan, lines.append,
        popen=lambda argv, **kw: _Proc([b"Error: no bottle"], 1)) is False
    assert any("did not finish (exit 1)" in l for l in lines)


def test_run_plan_says_when_the_manager_cannot_start():
    plan = mac_install.install_plan([GPG], manager=BREW)
    lines = []

    def popen(argv, **kw):
        raise OSError("No such file or directory: brew")

    assert mac_install.run_plan(plan, lines.append, popen=popen) is False
    assert any("could not start" in l for l in lines)


# --------------------------------------------------------------- the app
def test_install_missing_on_a_mac_runs_the_plan_in_the_window(tmp_path,
                                                             monkeypatch):
    """The strip's Install Missing (shellx.install_prereqs) on a Mac with
    gpg missing: asks once, runs brew in a thread, logs, re-checks."""
    from tests.webui_harness import web_app

    with web_app(tmp_path, mfr="bof") as w:
        app = w.app
        app._prereq_results = {
            "gpg": PrerequisiteResult(name="gpg", ok=False,
                                      message="bash: gpg: command not found",
                                      install_hint="brew install gnupg"),
            "tar": PrerequisiteResult(name="tar", ok=True, message="on PATH"),
        }
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(mac_install, "package_manager", lambda: BREW)
        ran = []

        def run_plan(plan, log, popen=None):
            ran.append(plan["install"])
            log("==> Pouring gnupg")
            return True

        monkeypatch.setattr(mac_install, "run_plan", run_plan)
        w.answers.append("yes")
        assert w.call("shellx.install_prereqs") is True
        end = time.time() + 10
        while time.time() < end and not ran:
            time.sleep(0.05)
        assert ran == [["/opt/homebrew/bin/brew", "install", "gnupg"]]
        assert w.asked and w.asked[-1]["title"] == "Install Prerequisites"
        assert "gnupg" in w.asked[-1]["message"]
        assert "Go ahead?" in w.asked[-1]["message"]
        end = time.time() + 10
        while time.time() < end:
            w.drain()
            log = "\n".join(e.get("text", "")
                            for e in w.window._log.get("bof", []))
            if "installed; checking again" in log:
                break
            time.sleep(0.05)
        assert "==> Pouring gnupg" in log
        assert "installed; checking again" in log


def test_install_missing_on_a_mac_with_nothing_missing_says_so(tmp_path,
                                                              monkeypatch):
    from tests.webui_harness import web_app

    with web_app(tmp_path, mfr="bof") as w:
        w.app._prereq_results = {
            p.name: PrerequisiteResult(name=p.name, ok=True, message="ok")
            for p in w.app._current_mfr.prerequisites}
        monkeypatch.setattr(sys, "platform", "darwin")
        assert w.call("shellx.install_prereqs") is True
        w.drain()
        assert w.asked[-1]["title"] == "Install Prerequisites"
        assert "Nothing is missing" in w.asked[-1]["message"]


# ------------------------------------------- a MacPorts that will not run
# cooltoy's log (PAD-221): MacPorts installed for macOS 15, the Mac moved to
# macOS 26, and every `port` command refuses with this.
MISMATCH = (
    b'Error: Current platform "darwin 25" does not match expected platform '
    b'"darwin 24"\n'
    b"Error: Please run 'sudo port migrate' or follow the migration "
    b"instructions: https://trac.macports.org/wiki/Migration\n"
    b"OS platform mismatch\n"
    b"    while executing\n"
    b'"mportinit ui_options global_options global_variations"\n'
    b"Error: /opt/local/bin/port: Failed to initialize MacPorts, OS "
    b"platform mismatch\n")


class _Done:
    def __init__(self, rc, out):
        self.returncode = rc
        self.stdout = out


def test_macports_health_reads_the_platform_mismatch():
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return _Done(1, MISMATCH)

    h = mac_install.macports_health("/opt/local/bin/port", run=run)
    assert calls == [["/opt/local/bin/port", "version"]]
    assert h["kind"] == "migrate"
    assert h["current"] == "darwin 25" and h["expected"] == "darwin 24"
    assert "macOS 15 (darwin 24)" in h["text"]
    assert "macOS 26 (darwin 25)" in h["text"]
    assert "migrated" in h["text"]
    assert h["lines"][0].startswith("Error: Current platform")
    assert all(l.startswith("Error") for l in h["lines"])


def test_macports_health_is_none_when_port_runs_and_broken_otherwise():
    assert mac_install.macports_health(
        "/opt/local/bin/port",
        run=lambda argv, **kw: _Done(0, b"Version: 2.10.5\n")) is None
    h = mac_install.macports_health(
        "/opt/local/bin/port",
        run=lambda argv, **kw: _Done(1, b"Error: Xcode is not installed\n"))
    assert h["kind"] == "broken"
    assert "Xcode is not installed" in h["text"]

    def run(argv, **kw):
        raise OSError("No such file or directory")

    assert mac_install.macports_health("/opt/local/bin/port",
                                       run=run)["kind"] == "broken"


def test_macos_name_spells_the_darwin_major():
    assert mac_install.macos_name("darwin 24") == "macOS 15 (darwin 24)"
    assert mac_install.macos_name("darwin 25") == "macOS 26 (darwin 25)"
    assert mac_install.macos_name("darwin 99") == "darwin 99"
    assert mac_install.macos_name("") == ""


def test_a_macports_that_needs_migrating_migrates_first_in_the_same_run():
    health = mac_install.macports_health(
        "/opt/local/bin/port", run=lambda argv, **kw: _Done(1, MISMATCH))
    plan = mac_install.install_plan([GPG], manager=PORT, health=health)
    assert plan["commands"] == [
        ["/opt/local/bin/port", "-N", "migrate"],
        ["/opt/local/bin/port", "-N", "install", "gnupg2"]]
    assert plan["install"] == plan["commands"][-1]
    assert plan["migrate"] is True and not plan.get("blocked")
    # the consent says why, what migrate does, and how long it can take
    assert "macOS 15 (darwin 24)" in plan["steps"][0]
    assert "macOS 26 (darwin 25)" in plan["steps"][0]
    assert "port migrate" in plan["steps"][0]
    assert "long time" in plan["steps"][0]
    assert "Install gnupg2 with MacPorts" in plan["steps"][1]
    assert sum("password" in s for s in plan["steps"]) == 1
    assert mac_install.plan_command_line(plan) == (
        "/opt/local/bin/port -N migrate && "
        "/opt/local/bin/port -N install gnupg2")
    # a healthy MacPorts is the old one-command plan
    plan = mac_install.install_plan([GPG], manager=PORT, health=None)
    assert plan["commands"] == [["/opt/local/bin/port", "-N", "install",
                                 "gnupg2"]]
    assert plan["migrate"] is False
    assert "migrate" not in " ".join(plan["steps"])


def test_a_broken_macports_blocks_the_plan_with_its_own_words():
    health = mac_install.macports_health(
        "/opt/local/bin/port",
        run=lambda argv, **kw: _Done(1, b"Error: Xcode is not installed\n"))
    plan = mac_install.install_plan([GPG], manager=PORT, health=health)
    assert "Xcode is not installed" in plan["blocked"]
    assert plan["commands"] == []


def test_plan_for_checks_macports_but_not_homebrew(monkeypatch):
    checked = []
    monkeypatch.setattr(mac_install, "macports_health",
                        lambda tool: checked.append(tool) or None)
    monkeypatch.setattr(mac_install, "package_manager", lambda: BREW)
    assert mac_install.plan_for([GPG])["manager"] == "Homebrew"
    assert checked == []
    monkeypatch.setattr(mac_install, "package_manager", lambda: PORT)
    assert mac_install.plan_for([GPG])["manager"] == "MacPorts"
    assert checked == ["/opt/local/bin/port"]
    monkeypatch.setattr(mac_install, "package_manager", lambda: None)
    assert mac_install.plan_for([GPG]) is None


def test_failure_lines_quote_the_error_lines_else_the_tail():
    lines = ["/opt/local/bin/port -N install gnupg2"] + [
        l.decode() for l in MISMATCH.splitlines()] + [
        "gnupg2 did not finish (exit 1)."]
    why = mac_install.failure_lines(lines)
    assert why[0].startswith("Error: Current platform")
    assert all(l.startswith("Error") for l in why)
    assert mac_install.failure_lines(["a", "b", "c", "d", "e", ""]) == [
        "b", "c", "d", "e"]


class _Osa:
    """osascript, as run_plan drives it: the script it was handed is read
    back before the real one is deleted."""
    def __init__(self, argv, rc=0, err=b""):
        import re
        self.returncode = rc
        self.stderr = io.BytesIO(err)
        # shlex.quote'd for sh, then backslash-doubled for AppleScript; on
        # a Windows test host that leaves 'C:\\...' in quotes (PAD-220's
        # lesson: a test must not assume the host it was written on)
        path = re.search(r"/bin/sh (.+?) > ", argv[2]).group(1)
        path = path.strip("'").replace("\\\\", "\\")
        with open(path, encoding="utf-8") as f:
            self.script = f.read()

    def poll(self):
        return self.returncode


def test_run_plan_runs_every_admin_command_under_one_password():
    health = mac_install.macports_health(
        "/opt/local/bin/port", run=lambda argv, **kw: _Done(1, MISMATCH))
    plan = mac_install.install_plan([GPG], manager=PORT, health=health)
    procs = []
    lines = []

    def popen(argv, **kw):
        assert argv[:2] == ["osascript", "-e"]
        assert "with administrator privileges" in argv[2]
        procs.append(_Osa(argv))
        return procs[-1]

    assert mac_install.run_plan(plan, lines.append, popen=popen) is True
    assert len(procs) == 1                      # one osascript = one password
    script = procs[0].script
    assert script.index("port -N migrate") < script.index(
        "port -N install gnupg2")
    assert "port -N migrate || exit $?" in script   # a failed migrate stops
    assert "echo '==> /opt/local/bin/port -N migrate'" in script
    assert lines[:2] == ["/opt/local/bin/port -N migrate",
                         "/opt/local/bin/port -N install gnupg2"]

    # a single command keeps the old plain script
    plan = mac_install.install_plan([GPG], manager=PORT)
    procs.clear()
    assert mac_install.run_plan(plan, lines.append, popen=popen) is True
    assert "==>" not in procs[0].script and "|| exit" not in procs[0].script


def _mac_with_macports(w, monkeypatch, health, run_ok, run_lines):
    w.app._prereq_results = {
        "gpg": PrerequisiteResult(name="gpg", ok=False,
                                  message="exit code 1",
                                  install_hint="Install Missing"),
        "tar": PrerequisiteResult(name="tar", ok=True, message="on PATH"),
    }
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(mac_install, "package_manager", lambda: PORT)
    monkeypatch.setattr(mac_install, "macports_health", lambda tool: health)
    ran = []

    def run_plan(plan, log, popen=None):
        ran.append(plan)
        for l in run_lines:
            log(l)
        return run_ok

    monkeypatch.setattr(mac_install, "run_plan", run_plan)
    return ran


def _wait_for(w, pred, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_install_missing_on_a_macports_mac_that_needs_migrating(tmp_path,
                                                                monkeypatch):
    """cooltoy's Mac (PAD-221): the consent names the migration first, the
    run is the two commands, and a failure comes back in a box that quotes
    MacPorts' own Error lines - not only the log."""
    from tests.webui_harness import web_app

    health = mac_install.macports_health(
        "/opt/local/bin/port", run=lambda argv, **kw: _Done(1, MISMATCH))
    with web_app(tmp_path, mfr="bof") as w:
        ran = _mac_with_macports(
            w, monkeypatch, health, False,
            ["/opt/local/bin/port -N migrate",
             "Error: Xcode Command Line Tools are not installed",
             "gnupg2 did not finish (exit 1)."])
        w.answers.append("yes")
        w.answers.append("ok")
        assert w.call("shellx.install_prereqs") is True
        assert _wait_for(w, lambda: ran)
        consent = w.asked[0]
        assert consent["title"] == "Install Prerequisites"
        assert "macOS 15 (darwin 24)" in consent["message"]
        assert "macOS 26 (darwin 25)" in consent["message"]
        assert "port migrate" in consent["message"]
        assert "Install gnupg2 with MacPorts" in consent["message"]
        assert "Go ahead?" in consent["message"]
        assert ran[0]["commands"][0] == ["/opt/local/bin/port", "-N",
                                         "migrate"]
        assert _wait_for(w, lambda: len(w.asked) >= 2)
        box = w.asked[1]
        assert box["icon"] == "error"
        assert "gnupg2 did not install" in box["message"]
        assert "MacPorts said" in box["message"]
        assert "Xcode Command Line Tools are not installed" in box["message"]
        assert "Current platform" not in box["message"]
        log = "\n".join(e.get("text", "")
                        for e in w.window._log.get("bof", []))
        assert "port -N migrate && /opt/local/bin/port -N install gnupg2" \
            in log
        assert "the install did not finish" in log


def test_install_missing_on_a_broken_macports_says_so_without_asking(
        tmp_path, monkeypatch):
    from tests.webui_harness import web_app

    health = mac_install.macports_health(
        "/opt/local/bin/port",
        run=lambda argv, **kw: _Done(1, b"Error: Xcode is not installed\n"))
    with web_app(tmp_path, mfr="bof") as w:
        ran = _mac_with_macports(w, monkeypatch, health, True, [])
        w.answers.append("ok")
        assert w.call("shellx.install_prereqs") is True
        w.drain()
        assert ran == []
        assert len(w.asked) == 1
        assert w.asked[0]["icon"] == "error"
        assert "Xcode is not installed" in w.asked[0]["message"]
        assert "Go ahead?" not in w.asked[0]["message"]


def test_a_healthy_macports_is_asked_the_old_way(tmp_path, monkeypatch):
    from tests.webui_harness import web_app

    with web_app(tmp_path, mfr="bof") as w:
        ran = _mac_with_macports(w, monkeypatch, None, True,
                                 ["---> Installing gnupg2"])
        w.answers.append("yes")
        assert w.call("shellx.install_prereqs") is True
        assert _wait_for(w, lambda: ran)
        assert "migrate" not in w.asked[0]["message"]
        assert ran[0]["commands"] == [["/opt/local/bin/port", "-N",
                                       "install", "gnupg2"]]
        assert _wait_for(w, lambda: "installed; checking again" in "\n".join(
            e.get("text", "") for e in w.window._log.get("bof", [])))
        assert len(w.asked) == 1                 # no box on success
