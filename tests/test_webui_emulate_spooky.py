"""The web Emulate Spooky tab (webui/tabs/emulate_spooky.py, PAD-266),
without ever touching a rig: the harness sets PAD_UI_NO_RIG, conftest points
the rig dir at an empty directory, and the tests that need more stub it."""

import json
import time

import pytest

from tests.webui_harness import web_app

NS = "emulate_spooky"


def _svc(w):
    return w.window.service(NS)


@pytest.fixture(autouse=True)
def _no_theme_probe(monkeypatch):
    """macOS asks for the theme through subprocess, which tests here spy on."""
    from pinball_decryptor.webui import theme
    monkeypatch.setattr(theme, "detect_system_theme", lambda: "light")


@pytest.fixture
def rig(monkeypatch):
    from pinball_decryptor.webui import emulate_spooky_core as core
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: True)


def _spooky(w):
    if "spooky" not in {m.key for m in w.window.manufacturers}:
        pytest.skip("no spooky plugin (its crypto dependency is missing)")


# ------------------------------------------------------------------ gating
def test_spooky_shows_the_tab_and_says_what_it_runs(rig, tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs[NS]["visible"] and tabs[NS]["label"] == "Emulate"
        for other in ("emulate", "emulate_jjp", "emulate_spike1",
                      "emulate_bof", "emulate_dp"):
            assert not tabs[other]["visible"]
        s = w.state(NS)
        assert s["supported"] == ["Beetlejuice"]
        assert "Supported so far: Beetlejuice" in s["intro"]
        assert "can't be emulated yet" in s["intro"]
        assert s["go_label"] == "Start" and s["go_enabled"]
        assert [c["label"] for c in s["cells"]] == [
            "Game", "Version", "Board", "Balls", "Memory", "Uptime"]


@pytest.mark.parametrize("mfr", ["stern", "jjp", "bof"])
def test_other_manufacturers_do_not_get_the_spooky_tab(tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs[NS]["visible"]


def test_a_missing_rig_says_so_and_greys_start(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        s = w.state(NS)
        assert not s["go_enabled"] and not s["rig_ok"]
        assert "tools/spooky_emu" in s["note"]


def test_the_shipped_rig_is_complete():
    """rig_available() checks the scripts the tab runs; the repo has them."""
    import os
    from pinball_decryptor.webui import emulate_spooky_core as core
    for s in ("watch.sh", "stop.sh", "status.sh", "cancel.sh", "ctl.sh",
              "spkshim.so", "spkwarden.py", "spkpf.py"):
        assert os.path.isfile(os.path.join(core.DEFAULT_RIG_DIR, s)), s


def test_browse_asks_for_a_beetlejuice_update(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        f = tmp_path / "v2026.09.15.11.beetlejuice"
        f.write_bytes(b"")
        w.answers.append(str(f))
        assert w.call(NS + ".browse")
        assert ["Beetlejuice update", "*.beetlejuice"] in w.asked[-1]["filetypes"]
        assert w.window.spooky_emulate_file_var.get() == str(f)


def test_an_empty_field_uses_a_beetlejuice_update_picked_on_select_card(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        svc = _svc(w)
        w.window.extract_input_var.set(r"D:\Pinball\images\Spooky\v2026.09.15.11.beetlejuice")
        assert svc.file_path().endswith(".beetlejuice")
        # a restore image or another title's update is not one it runs
        w.window.extract_input_var.set(r"D:\Pinball\images\Spooky\bj_production_base_image.zip")
        assert svc.file_path() == ""
        w.window.extract_input_var.set(r"D:\Pinball\images\Spooky\v2025.12.01.09.scooby")
        assert svc.file_path() == ""
        # its own field wins
        w.window.spooky_emulate_file_var.set(r"C:\mods\bj_mod.beetlejuice")
        assert svc.file_path() == r"C:\mods\bj_mod.beetlejuice"


def test_showing_the_tab_puts_up_its_ladder(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        w.call("ui.select_tab", NS)
        f = w.state("shell")["footer"]
        assert f["phases"] == ["Unpack", "Board", "Game", "Ready"]
        assert f["mode"] == "emulate"


def test_start_without_a_file_asks_and_runs_nothing(rig, monkeypatch, tmp_path):
    ran = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: ran.append(a))
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        w.call(NS + ".toggle")
        assert ran == [] and not _svc(w)._busy


# ------------------------------------------------------------ the poll
HW = {"switches": {"1": 1, "3": 1, "4": 1, "5": 1, "6": 1, "8": 1},
      "balls": {"trough": 5, "shooter": 1, "in_play": 0},
      "connected": True, "leds_lit": 0}
RUNNING = {"wsl": "1", "running": "1", "title": "beetlejuice",
           "version": "v2026.09.15.11", "pid": "42",
           "rss_kb": str(3 * 1048576), "uptime_s": "95", "display": ":0",
           "visible": "1", "slot": "0", "attract": "1", "hw": json.dumps(HW)}


def test_apply_running_fills_the_grid(rig, tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        _svc(w)._apply(dict(RUNNING))
        s = w.state(NS)
        assert s["up"] and s["ready"] and s["go_label"] == "Stop"
        assert s["state_label"] == "Running" and s["tone"] == "ok"
        v = {c["label"]: c["value"] for c in s["cells"]}
        assert v["Game"] == "Beetlejuice" and v["Version"] == "v2026.09.15.11"
        assert v["Board"] == "connected"
        assert v["Balls"] == "5 in trough, 0 in play, 1 in shooter lane"
        assert v["Memory"] == "3.0 GB" and v["Uptime"] == "1:35"


def test_loading_is_not_yet_running(rig, tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        _svc(w)._apply(dict(RUNNING, attract="0"))
        s = w.state(NS)
        assert s["state_label"] == "Starting" and not s["ready"]


def test_launch_lines_move_the_footer(rig, tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        svc = _svc(w)
        seen = []
        svc._footer = lambda kind, pct=None, text="": seen.append((kind, pct))
        for line in ("== Unpack ==", "progress 40", "== Board ==",
                     "== Game ==", "== Ready =="):
            svc._footer_line(line)
        assert seen == [("copy", 0), ("copy", 40), ("boot", None),
                        ("techalerts", None), ("run", None)]


def test_the_switch_window_command(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_spooky_core as core
    from pinball_decryptor.webui.tabs import emulate_spooky as tab
    monkeypatch.setattr(tab, "windows_python", lambda: "pythonw.exe")
    monkeypatch.setattr(core, "rig_distro", lambda: "PAD-Runtime")
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        cmd = _svc(w)._switch_window_cmd(dict(RUNNING))
        assert cmd[0] == "pythonw.exe" and cmd[1].endswith("spkpf.py")
        assert cmd[cmd.index("--slot") + 1] == "0"
        assert cmd[cmd.index("--distro") + 1] == "PAD-Runtime"


def test_quit_stops_only_a_run_this_app_started(rig, monkeypatch, tmp_path):
    import subprocess
    ran = []
    from pinball_decryptor.webui import emulate_spooky_core as core
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(
        "pinball_decryptor.webui.tabs.emulate_spooky.rig_off", lambda: False)
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        svc = _svc(w)
        svc._last_up = True
        svc._started_here = False
        svc.emulate_shutdown()
        assert ran == []
        svc._started_here = True
        svc.emulate_shutdown()
        assert len(ran) == 1 and "stop.sh" in " ".join(ran[0][0])


def test_while_starting_the_button_is_cancel(rig, monkeypatch, tmp_path):
    import subprocess
    from pinball_decryptor.webui import emulate_spooky_core as core
    ran = []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **k: ran.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, b"cancelled=1", b""))
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        svc = _svc(w)
        svc._busy = True
        svc._starting = True
        svc._set_go("Cancel", True)
        assert w.state(NS)["go_label"] == "Cancel"
        assert w.call(NS + ".toggle")
        end = time.time() + 5
        while not ran and time.time() < end:
            time.sleep(0.02)
        assert ran and ran[0][-1] == "cancel.sh"


def test_supported_file_is_by_suffix():
    from pinball_decryptor.webui import emulate_spooky_core as core
    assert core.supported_file(r"D:\x\v2026.09.15.11.beetlejuice")
    assert core.supported_file("/mnt/d/X.BEETLEJUICE")
    assert not core.supported_file("v2025.12.01.09.scooby")
    assert not core.supported_file("")
