"""PAD-291: on a Linux desktop the emulator rig gets the desktop's own
environment (not the AppImage's bundled libraries) and XWayland on Wayland."""

from pinball_decryptor.webui import emulate_core
from pinball_decryptor.webui import rig as _rig

_APP = "/tmp/.mount_PADxyz"


def _appimage_env(**extra):
    env = {
        "APPDIR": _APP,
        "LD_LIBRARY_PATH": _APP + "/usr/bin/_internal",
        "LD_LIBRARY_PATH_ORIG": "",
        "PATH": _APP + "/usr/bin:/usr/local/bin:/usr/bin",
        "HOME": "/home/aly",
    }
    env.update(extra)
    return env


def _host(monkeypatch, environ):
    from pinball_decryptor.core import desktop
    monkeypatch.setattr(_rig.sys, "platform", "linux")
    monkeypatch.setattr(desktop.os, "pathsep", ":")   # a Windows test host
    scrubbed = desktop.desktop_env(environ, bundle_dirs=[_APP])
    return _rig.linux_host_env(environ, scrubbed)


def test_bundle_libraries_are_dropped(monkeypatch):
    """The user's LD_PRELOAD of the system libmount was standing in for this:
    the AppImage's LD_LIBRARY_PATH must not reach the rig's system programs."""
    got = _host(monkeypatch, _appimage_env())
    assert got[:2] == ["-u", "LD_LIBRARY_PATH"]
    assert "PATH=/usr/local/bin:/usr/bin" in got
    assert not any(e.startswith("HOME=") for e in got)
    assert not any(e.startswith("GDK_BACKEND") for e in got)


def test_wayland_pins_xwayland(monkeypatch):
    got = _host(monkeypatch, _appimage_env(WAYLAND_DISPLAY="wayland-0",
                                           DISPLAY=":0"))
    assert "GDK_BACKEND=x11" in got and "EGL_PLATFORM=x11" in got


def test_wayland_respects_the_users_choice_and_no_xwayland(monkeypatch):
    got = _host(monkeypatch, _appimage_env(WAYLAND_DISPLAY="wayland-0",
                                           DISPLAY=":0",
                                           GDK_BACKEND="wayland"))
    assert not any(e.startswith("GDK_BACKEND") for e in got)
    assert "EGL_PLATFORM=x11" in got
    got = _host(monkeypatch, _appimage_env(WAYLAND_DISPLAY="wayland-0"))
    assert not any(e.endswith("=x11") for e in got)


def test_not_linux_is_untouched(monkeypatch):
    for plat in ("win32", "darwin"):
        monkeypatch.setattr(_rig.sys, "platform", plat)
        assert _rig.linux_host_env(_appimage_env(WAYLAND_DISPLAY="w",
                                                 DISPLAY=":0")) == []


def test_both_rig_cmds_carry_it_on_linux(monkeypatch):
    host = ["-u", "LD_LIBRARY_PATH", "GDK_BACKEND=x11"]
    monkeypatch.setattr(_rig, "linux_host_env", lambda: host)
    monkeypatch.setattr(_rig.sys, "platform", "linux")
    cmd = _rig.rig_cmd("/rig", "watch.sh", env=["A=1"])
    assert cmd[:6] == ["env", "-u", "LD_LIBRARY_PATH", "GDK_BACKEND=x11",
                       "A=1", "bash"]
    monkeypatch.setattr(emulate_core.sys, "platform", "linux")
    monkeypatch.setattr(emulate_core, "rig_dir", lambda: "/rig")
    cmd = emulate_core.rig_cmd("watch.sh", env=("B=2",))
    assert cmd[:6] == ["env", "-u", "LD_LIBRARY_PATH", "GDK_BACKEND=x11",
                       "B=2", "bash"]
