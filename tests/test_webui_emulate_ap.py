"""The web Emulate AP tab (webui/tabs/emulate_ap.py, PAD-292), without ever
touching a rig: the harness sets PAD_UI_NO_RIG, conftest points the rig dir
at an empty directory, and the tests that need more stub it."""

import time

import pytest

from tests.webui_harness import web_app

NS = "emulate_ap"


def _svc(w):
    return w.window.service(NS)


@pytest.fixture(autouse=True)
def _no_theme_probe(monkeypatch):
    """On macOS the app asks ``defaults read -g AppleInterfaceStyle`` for the
    theme through subprocess, which the tests here spy on to see what the tab
    runs: answer the theme without running anything."""
    from pinball_decryptor.webui import theme
    monkeypatch.setattr(theme, "detect_system_theme", lambda: "light")


@pytest.fixture
def rig(monkeypatch):
    from pinball_decryptor.webui import emulate_ap_core as core
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: True)


# ------------------------------------------------------------------ gating
def test_ap_shows_the_tab_with_its_idle_state(rig, tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs[NS]["visible"] and tabs[NS]["label"] == "Emulate"
        for other in ("emulate", "emulate_jjp", "emulate_spike1",
                      "emulate_bof"):
            assert not tabs[other]["visible"]
        s = w.state(NS)
        assert s["go_label"] == "Start" and s["go_enabled"]
        assert s["note"] == ""
        assert [c["label"] for c in s["cells"]] == [
            "Game", "Version", "Switches", "Window", "Memory", "Uptime"]
        assert _svc(w)._poll_job is None


@pytest.mark.parametrize("mfr", ["stern", "jjp", "bof"])
def test_other_manufacturers_do_not_get_the_ap_tab(tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs[NS]["visible"]


def test_a_missing_rig_says_so_and_greys_start(tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        s = w.state(NS)
        assert not s["go_enabled"] and not s["rig_ok"]
        assert "tools/ap_emu" in s["note"]


def test_off_windows_it_says_windows_only(monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_ap_core as core
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: False)
    with web_app(tmp_path, mfr="ap") as w:
        s = w.state(NS)
        assert not s["go_enabled"] and "Windows only" in s["note"]


def test_the_repo_ships_a_whole_rig(monkeypatch):
    from pinball_decryptor.webui import emulate_ap_core as core
    monkeypatch.setenv("PAD_AP_EMU_DIR", core.DEFAULT_RIG_DIR)
    assert core.rig_available()


def test_the_pkg_var_is_the_windows_export(tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        var = w.window.ap_emulate_pkg_var
        assert var is _svc(w).ap_emulate_pkg_var
        w.call("ui.set", NS, "pkg", r"D:\Pinball\images\AP\lov-gamecode_25.08.27.pkg")
        assert var.get() == r"D:\Pinball\images\AP\lov-gamecode_25.08.27.pkg"


def test_browse_asks_for_a_pkg(tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        f = tmp_path / "lov-gamecode_25.08.27.pkg"
        f.write_bytes(b"")
        w.answers.append(str(f))
        assert w.call(NS + ".browse")
        spec = w.asked[-1]
        assert ["American Pinball game code", "*.pkg"] in spec["filetypes"]
        assert w.window.ap_emulate_pkg_var.get() == str(f)


def test_showing_the_tab_puts_up_the_ap_ladder(tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        w.call("ui.select_tab", NS)
        f = w.state("shell")["footer"]
        assert f["phases"] == ["Unpack", "Game", "Ready"]
        assert f["mode"] == "emulate"


def test_an_empty_field_uses_the_pkg_picked_on_select_card(tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        svc = _svc(w)
        assert svc.pkg_path() == ""
        w.window.extract_input_var.set(r"D:\Pinball\images\AP\lov-gamecode_25.08.27.pkg")
        assert svc.pkg_path().endswith("lov-gamecode_25.08.27.pkg")
        w.window.ap_emulate_pkg_var.set(r"C:\mods\lov_mod.pkg")
        assert svc.pkg_path() == r"C:\mods\lov_mod.pkg"
        w.window.ap_emulate_pkg_var.set("")
        w.window.extract_input_var.set(r"D:\somewhere\else.iso")
        assert svc.pkg_path() == ""


# ------------------------------------------------------------- starting
def test_start_without_a_file_asks_and_runs_nothing(rig, monkeypatch, tmp_path):
    ran = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: ran.append(a))
    with web_app(tmp_path, mfr="ap") as w:
        w.call(NS + ".toggle")
        assert ran == []
        assert not _svc(w)._busy


def test_start_is_refused_while_the_rig_is_switched_off(rig, tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        f = tmp_path / "lov-gamecode_25.08.27.pkg"
        f.write_bytes(b"x")
        w.window.ap_emulate_pkg_var.set(str(f))
        w.call(NS + ".toggle")
        assert not _svc(w)._busy


def test_barry_os_bbq_is_refused_with_a_reason(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui import compat
    said = []
    monkeypatch.setattr(compat.messagebox, "showinfo",
                        lambda title, msg, **k: said.append(msg))
    with web_app(tmp_path, mfr="ap") as w:
        f = tmp_path / "bbq-gamecode_24.07.04.pkg"
        f.write_bytes(b"x")
        w.window.ap_emulate_pkg_var.set(str(f))
        w.call(NS + ".toggle")
        assert not _svc(w)._busy
        assert said and "BBQ" in said[-1]


def test_start_runs_watch_with_the_pkg_and_the_games_name(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_ap_core as core
    from pinball_decryptor.webui.tabs import emulate_ap as tab
    got = []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: got.append((a, k)) or ["true"])
    monkeypatch.setattr(tab, "rig_off", lambda: False)
    with web_app(tmp_path, mfr="ap") as w:
        svc = _svc(w)
        monkeypatch.setattr(svc, "_refuse_off", lambda: False)
        monkeypatch.setattr(svc, "_run_streaming", lambda *a, **k: 1)
        f = tmp_path / "lov-gamecode_25.08.27.pkg"
        f.write_bytes(b"x")
        w.window.ap_emulate_pkg_var.set(str(f))
        w.call(NS + ".toggle")
        end = time.time() + 5
        while not got and time.time() < end:
            time.sleep(0.02)
        args, kw = got[0]
        assert args[0] == "watch.sh" and args[1].endswith("lov-gamecode_25.08.27.pkg")
        assert "PAD_TITLE=Legends of Valhalla" in kw["env"]
        assert "PAD_VISIBLE=1" in kw["env"]
        # sound always on, the level following the shared control file
        assert "PAD_AUDIO=1" in kw["env"]
        assert any(e.startswith("PAD_AUDIO_CTL=") and e.endswith("audio_ctl.json")
                   for e in kw["env"])


# ------------------------------------------------------------ the poll
RUNNING = {"wsl": "1", "ready": "1", "running": "1",
           "title": "Legends of Valhalla", "build": "lov_25.08.27",
           "version": "25.08.27", "pid": "42", "rss_kb": str(2 * 1048576),
           "uptime_s": "75", "display": ":0", "visible": "1",
           "window": "1366x768", "av": "0", "switches": "56", "slot": "0",
           "switches_json": "/var/tmp/pad_ap/rig0/switches.json"}


def test_apply_running_fills_the_grid(rig, tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        _svc(w)._apply(dict(RUNNING))
        s = w.state(NS)
        assert s["up"] and s["go_label"] == "Stop" and s["game"] == "Legends of Valhalla"
        assert s["state_label"] == "Running" and s["tone"] == "ok"
        v = {c["label"]: c["value"] for c in s["cells"]}
        assert v["Game"] == "Legends of Valhalla" and v["Version"] == "25.08.27"
        assert v["Switches"] == "56" and v["Window"] == "1366 × 768"
        assert v["Memory"] == "2.0 GB" and v["Uptime"] == "1:15"


def test_an_av_title_says_who_draws_it(rig, tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        _svc(w)._apply(dict(RUNNING, av="1", window=""))
        v = {c["label"]: c["value"] for c in w.state(NS)["cells"]}
        assert v["Window"] == "AP's A/V player"


def test_stopped_before_the_first_setup_warns_of_the_download(rig, tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        _svc(w)._apply({"wsl": "1", "running": "0", "ready": "0"})
        s = w.state(NS)
        assert not s["up"] and s["state_label"] == "Stopped"
        assert "downloads" in s["state_hint"] and s["go_label"] == "Start"
        _svc(w)._apply({"wsl": "1", "running": "0", "ready": "1"})
        assert w.state(NS)["state_hint"] == ""


# ------------------------------------------------------- the switch window
def test_the_switch_window_command(rig, monkeypatch, tmp_path):
    """appf.py on the app's Windows Python, told the title, the slot, the
    distro, and the table through the distro's share."""
    from pinball_decryptor.webui import emulate_ap_core as core
    from pinball_decryptor.webui.tabs import emulate_ap as tab
    monkeypatch.setattr(tab, "windows_python", lambda: "pythonw.exe")
    monkeypatch.setattr(core, "rig_distro", lambda: "PAD-Runtime")
    with web_app(tmp_path, mfr="ap") as w:
        cmd = _svc(w)._switch_window_cmd(dict(RUNNING))
        assert cmd[0] == "pythonw.exe" and cmd[1].endswith("appf.py")
        assert cmd[cmd.index("--title") + 1] == "Legends of Valhalla"
        assert cmd[cmd.index("--slot") + 1] == "0"
        assert cmd[cmd.index("--distro") + 1] == "PAD-Runtime"
        assert cmd[cmd.index("--table") + 1] == \
            "\\\\wsl.localhost\\PAD-Runtime\\var\\tmp\\pad_ap\\rig0\\switches.json"
        # no table (no game), no window
        assert _svc(w)._switch_window_cmd({"running": "0"}) is None


def test_switches_button_needs_a_running_game(rig, tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        assert not w.call(NS + ".switches")


def test_launch_lines_move_the_footer(rig, tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        w.call("ui.select_tab", NS)
        svc = _svc(w)
        seen = []
        svc._footer = lambda kind, pct=None, text="": seen.append((kind, pct, text))
        for line in ("== Setup ==", "note: first start - setting up",
                     "== Prepare ==", "progress 40", "== Game ==", "== Ready =="):
            svc._footer_line(line)
        assert [(k, p) for k, p, _t in seen] == [
            ("copy", 0), ("copy", 0), ("copy", 0), ("copy", 40), ("boot", None),
            ("run", None)]
        assert "once" in seen[1][2]
        assert seen[3][2].startswith("Decrypting")
        svc._footer_line("progress 75")
        assert seen[-1] == ("copy", 75, "Unpacking the game… 75%")


# ------------------------------------------------------------ stop / quit
def test_quit_stops_only_a_run_this_app_started(rig, monkeypatch, tmp_path):
    import subprocess
    ran = []
    from pinball_decryptor.webui import emulate_ap_core as core
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(
        "pinball_decryptor.webui.tabs.emulate_ap.rig_off", lambda: False)
    with web_app(tmp_path, mfr="ap") as w:
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
    from pinball_decryptor.webui import emulate_ap_core as core
    ran = []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **k: ran.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, b"cancelled=1", b""))
    with web_app(tmp_path, mfr="ap") as w:
        svc = _svc(w)
        svc._busy = True
        svc._starting = True
        svc._set_go("Cancel", True)
        s = w.state(NS)
        assert s["go_label"] == "Cancel" and s["go_enabled"] and s["starting"]
        assert w.call(NS + ".toggle")
        assert w.state(NS)["go_label"] == "Cancelling…"
        end = time.time() + 5
        while not ran and time.time() < end:
            time.sleep(0.02)
        assert ran and ran[0][-1] == "cancel.sh"
        assert not w.call(NS + ".cancel")


def test_game_info_names_the_game_from_the_plugin():
    from pinball_decryptor.webui import emulate_ap_core as core
    assert core.game_info(r"D:\x\lov-gamecode_25.08.27.pkg") == ("legends_of_valhalla", "Legends of Valhalla")
    assert core.game_info(r"D:\x\bbq-gamecode_24.07.04.pkg")[0] in core.NOT_HERE
    assert core.game_info(r"D:\x\notes.txt") == ("", "")


# ------------------------------------------------------------ the cache
CACHE_LIST = (
    "entry=lov_25.08.27 kind=build kb=1072236 used=1790727544 src=/mnt/d/Pinball/images/AP/lov-gamecode_25.08.27.pkg\n"
    "entry=tank_26.07.27B kind=build kb=7001248 used=1790720000 src=/mnt/c/My Games/tank-gamecode_26.07.27B.pkg\n"
    "entry=envs kind=envs kb=3876740 used=1790700000 src=\n"
    "disk=24759708 102101944\n")


def test_parse_cache_reads_entries_and_the_disk():
    from pinball_decryptor.webui import emulate_ap_core as core
    entries, disk = core.parse_cache(CACHE_LIST + "junk line\n")
    assert [e["name"] for e in entries] == ["lov_25.08.27", "tank_26.07.27B", "envs"]
    assert entries[1]["src"] == "/mnt/c/My Games/tank-gamecode_26.07.27B.pkg"   # spaces kept
    assert entries[0]["kb"] == 1072236 and entries[2]["kind"] == "envs"
    assert disk == (24759708, 102101944)
    assert core.cache_label(entries[2]).startswith("Emulator setup")
    assert core.parse_cache("") == ([], None)


def test_the_cache_window_lists_selects_and_deletes(rig, monkeypatch, tmp_path):
    import subprocess
    from pinball_decryptor.webui import compat
    from pinball_decryptor.webui import emulate_ap_core as core
    from pinball_decryptor.webui.tabs import emulate_ap as tab
    ran = []

    def fake_run(cmd, **k):
        ran.append(cmd)
        out = CACHE_LIST if "--list" in cmd else "dropped lov_25.08.27\nrefused=envs in use\ndropped=1\n"
        return subprocess.CompletedProcess(cmd, 0, out.encode(), b"")
    monkeypatch.setattr(core, "rig_cmd_root", lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(tab, "rig_off", lambda: False)
    asked = []
    monkeypatch.setattr(compat.messagebox, "askyesno",
                        lambda title, msg, **k: asked.append(msg) or True)
    with web_app(tmp_path, mfr="ap") as w:
        assert w.call(NS + ".open_cache")
        end = time.time() + 5
        while (w.state(NS).get("cache") or {}).get("busy") and time.time() < end:
            time.sleep(0.02)
        c = w.state(NS)["cache"]
        assert [r["name"] for r in c["rows"]] == ["lov_25.08.27", "tank_26.07.27B", "envs"]
        assert c["rows"][1]["size"] == "6.7 GB" and "free of" in c["head"]
        assert w.call(NS + ".cache_select", ["lov_25.08.27", "envs", "nope"]) == 2
        assert w.call(NS + ".cache_delete")
        assert "downloads again" in asked[-1]                # envs warned about
        end = time.time() + 5
        while not any("--drop" in x for x in ran) and time.time() < end:
            time.sleep(0.02)
        drop = next(x for x in ran if "--drop" in x)
        assert drop[1:] == ["cache.sh", "--drop", "lov_25.08.27", "envs"]
        assert w.call(NS + ".cache_close") and w.state(NS)["cache"] is None


def test_the_cache_window_needs_the_rig(tmp_path):
    with web_app(tmp_path, mfr="ap") as w:
        assert not w.call(NS + ".open_cache")


def test_stop_asks_the_switch_window_to_close_then_kills_its_tree(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui.tabs import emulate_ap as tab
    killed = []
    monkeypatch.setattr(tab, "_kill_tree", lambda p: killed.append(p))

    class Proc:
        def __init__(self, exits):
            self.exits, self.closed = exits, False
            self.stdin = self

        def close(self):
            self.closed = True

        def poll(self):
            return None

        def wait(self, timeout=None):
            if not self.exits:
                import subprocess
                raise subprocess.TimeoutExpired("appf", timeout)
            return 0
    with web_app(tmp_path, mfr="ap") as w:
        svc = _svc(w)
        svc.SW_CLOSE_S = 0.01
        polite = Proc(exits=True)
        svc._sw_proc = polite
        svc._close_switches(wait=True)
        assert polite.closed and killed == [] and svc._sw_proc is None
        stuck = Proc(exits=False)
        svc._sw_proc = stuck
        svc._close_switches(wait=True)
        assert stuck.closed and killed == [stuck]


def test_the_switch_window_is_told_to_watch_its_pipe(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_ap_core as core
    from pinball_decryptor.webui.tabs import emulate_ap as tab
    monkeypatch.setattr(tab, "windows_python", lambda: "pythonw.exe")
    monkeypatch.setattr(core, "rig_distro", lambda: "PAD-Runtime")
    with web_app(tmp_path, mfr="ap") as w:
        cmd = _svc(w)._switch_window_cmd(dict(RUNNING))
        assert "--parent-pipe" in cmd
