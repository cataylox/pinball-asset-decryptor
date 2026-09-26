"""A Barrels of Fun Extract on a machine without gpg says so, up front,
instead of "bash: gpg: command not found" under "check that the .fun file
is not corrupted" (PAD-220, cooltoy's Mac)."""

from pinball_decryptor.plugins.bof import pipeline as bp
from pinball_decryptor.plugins.bof.executor import CommandError, CommandExecutor
from tests._runner import run_pipeline_sync


class _NoGpg(CommandExecutor):
    """A Mac with no GnuPG: every gpg command dies the way bash says it."""

    def __init__(self):
        super().__init__()
        self.commands = []

    def run(self, bash_cmd, timeout=120):
        self.commands.append(bash_cmd)
        if "gpg" in bash_cmd:
            raise CommandError(bash_cmd, 127, "bash: gpg: command not found")
        return ""

    def stream(self, bash_cmd, timeout=600):
        return iter(())

    def to_exec_path(self, host_path):
        return host_path

    def check_available(self):
        return True, "macOS native"


def _extract(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(bp.sys, "platform", platform)
    fun = tmp_path / "lab.fun"
    fun.write_bytes(bytes(4096))
    out = tmp_path / "out"
    ex = _NoGpg()
    p = bp.DecryptPipeline(
        str(fun), str(out), ex,
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None, done_cb=lambda *a, **k: None)
    return run_pipeline_sync(p), ex


def test_extract_without_gpg_names_the_tool_not_the_file(tmp_path,
                                                        monkeypatch):
    r, ex = _extract(tmp_path, monkeypatch, "darwin")
    assert r.success is False
    assert "GnuPG (gpg) is not installed" in r.summary
    assert "brew install gnupg" in r.summary
    assert "Install Missing" in r.summary
    assert "corrupted" not in r.summary
    # nothing was decrypted with a bare "gpg" that bash could not find
    assert not any("--decrypt" in c for c in ex.commands)


def test_missing_gpg_text_is_spelled_per_desktop():
    mac = bp.missing_gpg_text("darwin")
    win = bp.missing_gpg_text("win32")
    lin = bp.missing_gpg_text("linux")
    for text in (mac, win, lin):
        assert text.startswith("GnuPG (gpg) is not installed")
        assert "GPG-encrypted" in text
    assert "Homebrew" in mac and "WSL" not in mac
    assert "WSL" in win and "apt-get install gnupg" in win
    assert "apt-get install gnupg" in lin and "WSL" not in lin


def test_a_decrypt_that_dies_on_a_missing_gpg_is_the_same_answer():
    """The second door: gpg resolved (a stale path, say) and the shell still
    says command not found - that is not a corrupt .fun either."""
    assert bp._gpg_absent_output("bash: gpg: command not found")
    assert bp._gpg_absent_output("/usr/local/bin/gpg: No such file or "
                                 "directory")
    assert not bp._gpg_absent_output("gpg: decryption failed: Bad session key")
    assert not bp._gpg_absent_output("")


def test_resolve_gpg_is_none_when_nothing_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(bp.sys, "platform", "win32")
    p = bp.DecryptPipeline(
        str(tmp_path / "lab.fun"), str(tmp_path / "out"), _NoGpg(),
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None, done_cb=lambda *a, **k: None)
    assert p._resolve_gpg() is None
