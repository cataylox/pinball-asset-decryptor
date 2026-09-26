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
