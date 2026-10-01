"""PAD-305: every emulator rig the same.  Rig N >= 1 is the ordinary rig seen
through its own overlay, mounted by a run when it starts - after the
preparation that installs a project's modes into it.  So a rig that had never
run refused the modes ("no guest rootfs"), and after a WSL restart an install
wrote into the bare mount point, which the run's mount then hid.  The Start
now mounts the rig's layer before anything is prepared."""

import os
import sys

import pytest

from pinball_decryptor.webui import emulate_core

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")


def test_rig_zero_has_no_layer_to_mount(monkeypatch):
    monkeypatch.delenv("PAD_SLOT", raising=False)
    assert emulate_core.slot_up_cmd() is None


@pytest.mark.skipif(sys.platform != "win32", reason="wsl -u root is Windows")
def test_a_numbered_rig_is_mounted_as_root(monkeypatch):
    monkeypatch.setenv("PAD_SLOT", "3")
    cmd = emulate_core.slot_up_cmd()
    assert cmd is not None
    assert "-u" in cmd and "root" in cmd
    assert cmd[-3:] == [cmd[-3], "up", "3"] and cmd[-3].endswith("slot.sh")


def test_the_start_refuses_when_the_layer_will_not_mount(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    with web_app(tmp_path, mfr="stern") as w:
        emu = w.window.service("emulate")
        monkeypatch.setattr(emulate_core, "slot_up_cmd",
                            lambda: ["false"])
        from pinball_decryptor.webui import emulate_rig
        monkeypatch.setattr(emulate_rig, "slot_up_cmd", lambda: ["false"])

        class R:
            returncode = 1
            stdout = b"[slot] could not mount slot 3's overlay"
            stderr = b""
        monkeypatch.setattr(emu, "_run", lambda *a, **k: R())
        assert emu._rig_layer_up() is False
        w.drain()
        s = w.state("emulate")
        assert s.get("ovr_refused") is True
        assert "could not mount slot 3" in s.get("ovr_hint", "")

        R.returncode = 0
        R.stdout = b"[slot] slot 3 mounted: /x/padslots/3/root"
        assert emu._rig_layer_up() is True


def test_tryit_mounts_or_refuses_before_it_installs():
    """The rig script must never install into an unmounted rig's mount
    point: it asks pad_slot_ready (mount as root, or the remedy) first."""
    src = open(os.path.join(RIG, "modes", "tryit.sh"), encoding="utf-8").read()
    ready = src.index("pad_slot_ready ||")
    assert ready < src.index('[ -d "$ROOT" ]')
    assert ready < src.index("case \"$cmd\" in")
