"""Every emulator posts its runs to the rig board (PAD-296).

Only the Spike 2 rig used to write %USERPROFILE%\\.pad-rig; a hidden run of any
other emulator (Beetlejuice, PAD-266) played with no window and nothing on the
triage dashboard. tools/rigboard.sh is the one helper every other emulator's
launcher sources: <emu>-<n>.run, kept fresh by a beater while the game's pid
lives, removed by the beater when it dies and by killgame.sh on a stop.

The helper runs under bash with a scratch board, so nothing real is touched.
Environment is set INSIDE the script: `bash` on a Windows dev box is WSL's,
which does not inherit this process's environment.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
BASH = shutil.which("bash")

needs_bash = pytest.mark.skipif(not BASH, reason="no bash")


def _src(*parts):
    with open(os.path.join(TOOLS, *parts), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _sh(body, timeout=60):
    """Run `body` in bash with the helper sourced and a scratch board in $B."""
    t = TOOLS.replace("\\", "/")
    head = ""
    if re.match(r"^[A-Za-z]:/", t):
        # Git Bash spells C:/ as /c/, WSL's bash as /mnt/c/.
        d, rest = t[0].lower(), t[2:]
        head = ('T=/mnt/%s%s; [ -d "$T" ] || T=/%s%s\n' % (d, rest, d, rest))
    else:
        head = 'T="%s"\n' % t
    script = head + r'''
for v in $(env | sed -n 's/^\(PAD_[A-Z_]*\)=.*/\1/p'); do unset "$v"; done
B=$(mktemp -d); export PAD_BOARD=$B
. "$T/rigboard.sh"
''' + body + '\nrm -rf "$B"\n'
    out = subprocess.run([BASH, "-c", script], capture_output=True, text=True,
                         timeout=timeout)
    return out.returncode, out.stdout, out.stderr


@needs_bash
def test_a_run_posts_what_the_dashboard_shows():
    rc, out, err = _sh(r'''
sleep 30 & P=$!
PAD_LABEL=PAD PAD_TICKET=PAD-296 rigboard_post ap 2 "$P" lov "Legends of Valhalla" 0 1
cat "$B/ap-2.run"
kill $P
''')
    assert rc == 0, err
    rec = json.loads(out.splitlines()[0])
    assert rec["emu"] == "ap" and rec["slot"] == 2
    assert rec["game"] == "lov" and rec["title"] == "Legends of Valhalla"
    # the app labels its windows "PAD"; the board wants the ticket
    assert rec["label"] == "PAD-296"
    assert rec["hidden"] is True and rec["audio"] is True
    assert isinstance(rec["pid"], int) and rec["started"] > 0


@needs_bash
def test_a_visible_muted_run_and_an_apostrophe_title():
    rc, out, err = _sh(r'''
sleep 30 & P=$!
PAD_LABEL=PAD-12 rigboard_post dp 0 "$P" aaiw "Alice's Adventures in Wonderland" 1 0
cat "$B/dp-0.run"
kill $P
''')
    assert rc == 0, err
    rec = json.loads(out.splitlines()[0])
    assert rec["title"] == "Alice's Adventures in Wonderland"
    assert rec["label"] == "PAD-12"
    assert rec["hidden"] is False and rec["audio"] is False


@needs_bash
def test_the_record_goes_when_the_game_dies():
    rc, out, err = _sh(r'''
command -v setsid >/dev/null && [ -d /proc/self ] || { echo SKIP; exit 0; }
sleep 1 & P=$!
RIGBOARD_BEAT_S=0.2 rigboard_post bof 1 "$P" dune "" 0 0
[ -f "$B/bof-1.run" ] && echo posted
for _ in $(seq 1 50); do [ -f "$B/bof-1.run" ] || break; sleep 0.1; done
[ -f "$B/bof-1.run" ] && echo still || echo gone
''')
    assert rc == 0, err
    if out.strip() == "SKIP":
        pytest.skip("no setsid or /proc")
    assert out.split() == ["posted", "gone"]


@needs_bash
def test_a_new_run_on_the_rig_is_not_removed_by_the_old_beater():
    rc, out, err = _sh(r'''
command -v setsid >/dev/null && [ -d /proc/self ] || { echo SKIP; exit 0; }
sleep 1 & OLD=$!
RIGBOARD_BEAT_S=0.2 rigboard_post proc 3 "$OLD" game.py Beetlejuice 0 0
sleep 30 & NEW=$!
RIGBOARD_BEAT_S=0.2 rigboard_post proc 3 "$NEW" game.py Beetlejuice 0 0
sleep 2
grep -q "\"pid\":$NEW," "$B/proc-3.run" && echo new-kept
rigboard_clear proc 3
[ -f "$B/proc-3.run" ] && echo still || echo cleared
kill $NEW
''')
    assert rc == 0, err
    if out.strip() == "SKIP":
        pytest.skip("no setsid or /proc")
    assert out.split() == ["new-kept", "cleared"]


@needs_bash
def test_a_hidden_run_is_muted_unless_sound_was_asked_for():
    rc, out, err = _sh(r'''
rigboard_audio 0 1
PAD_AUDIO_ASKED=1 rigboard_audio 0 1
rigboard_audio 1 1
rigboard_audio 0 0
''')
    assert rc == 0, err
    assert out.split() == ["0", "1", "1", "0"]
    assert "hidden run plays no sound" in err


@needs_bash
def test_no_pid_posts_nothing():
    rc, out, err = _sh(r'''
rigboard_post ap 0 "" lov "" 1 0
ls "$B" | wc -l
''')
    assert rc == 0, err
    assert out.split() == ["0"]


@needs_bash
def test_the_board_is_the_windows_profile_the_tools_live_under():
    rc, out, err = _sh(r'''
unset PAD_BOARD
RIGBOARD_HERE=/mnt/c/Users/pat/AppData/Local/PAD/tools rigboard_dir
PAD_BOARD=/x/y rigboard_dir
''')
    assert rc == 0, err
    assert out.splitlines() == ["/mnt/c/Users/pat/.pad-rig", "/x/y"]


# --------------------------------------------------------------------------
# Every emulator's run path posts, and its stop clears
# --------------------------------------------------------------------------

POSTS = {
    ("ap_emu", "run_game.sh"): "rigboard_post ap ",
    ("bof_emu", "run_game.sh"): "rigboard_post bof ",
    ("dp_emu", "run_game.sh"): "rigboard_post dp ",
    ("dp_emu", "run_aaiw.sh"): "rigboard_post dp ",
    ("jjp_emu", "run_game.sh"): "rigboard_post jjp ",
    ("pb_emu", "run_game.sh"): "rigboard_post pb ",
    ("proc_emu", "run_py.sh"): "rigboard_post proc ",
    ("spike1_emu", "start.sh"): "rigboard_post spike1 ",
    ("spooky_emu", "run_game.sh"): "rigboard_post spooky ",
}
CLEARS = {
    ("ap_emu", "killgame.sh"): "rigboard_clear ap ",
    ("bof_emu", "killgame.sh"): "rigboard_clear bof ",
    ("dp_emu", "killgame.sh"): "rigboard_clear dp ",
    ("jjp_emu", "killgame.sh"): "rigboard_clear jjp ",
    ("pb_emu", "killgame.sh"): "rigboard_clear pb ",
    ("proc_emu", "killgame.sh"): "rigboard_clear proc ",
    ("spike1_emu", "stop.sh"): "rigboard_clear spike1 ",
    ("spooky_emu", "killgame.sh"): "rigboard_clear spooky ",
}


@pytest.mark.parametrize("where,call", sorted(POSTS.items()))
def test_every_emulator_posts_its_run(where, call):
    assert call in _src(*where)


@pytest.mark.parametrize("where,call", sorted(CLEARS.items()))
def test_every_emulator_clears_on_stop(where, call):
    assert call in _src(*where)


@pytest.mark.parametrize("emu", ["ap_emu", "bof_emu", "dp_emu", "pb_emu", "spooky_emu"])
def test_the_hidden_mute_runs_before_the_launch(emu):
    s = _src(emu, "run_game.sh")
    assert 'AUDIO=$(rigboard_audio "$VISIBLE" "$AUDIO")' in s
    assert s.index("rigboard_audio") < s.index("rigboard_post")


@pytest.mark.parametrize("path", ["ap_emu/appath.sh", "bof_emu/bofpath.sh",
                                  "dp_emu/dppath.sh", "proc_emu/procpath.sh",
                                  "jjp_emu/padpath.sh", "pb_emu/pbpath.sh",
                                  "spooky_emu/spkpath.sh"])
def test_a_missing_helper_is_a_no_op(path):
    """An old install's tools folder without rigboard.sh still runs."""
    s = _src(*path.split("/"))
    assert "../rigboard.sh" in s
    assert "rigboard_post() { :; }" in s


def test_spike2_record_says_which_emulator_and_whether_it_plays_sound():
    s = _src("spike2_emu", "watch.sh")
    assert '{"emu":"spike2","slot":%s' in s
    assert '"hidden":%s,"audio":%s}' in s


def test_the_installer_ships_the_helper():
    with open(os.path.join(REPO, "installer", "pinball_decryptor.iss"),
              encoding="utf-8", errors="replace") as fh:
        assert r'Source: "{#ProjectDir}\tools\rigboard.sh"; DestDir: "{app}\tools"' in fh.read()


# --------------------------------------------------------------------------
# The app hands the board and the ticket to every emulator it launches
# --------------------------------------------------------------------------

def test_board_env_names_the_board_and_the_ticket(monkeypatch, tmp_path):
    from pinball_decryptor.core import rigslot
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PAD_BOARD_WIN", r"C:\Users\pat\.pad-rig")
    monkeypatch.setenv("PAD_TICKET", "PAD-296")
    monkeypatch.delenv("PAD_LABEL", raising=False)
    assert rigslot.board_env() == ["PAD_BOARD=/mnt/c/Users/pat/.pad-rig",
                                   "PAD_TICKET=PAD-296"]
    monkeypatch.delenv("PAD_TICKET")
    assert rigslot.board_env() == ["PAD_BOARD=/mnt/c/Users/pat/.pad-rig"]


def test_board_env_is_empty_off_windows(monkeypatch):
    from pinball_decryptor.core import rigslot
    monkeypatch.setattr(sys, "platform", "linux")
    assert rigslot.board_env() == []


@pytest.mark.parametrize("tab", ["emulate_ap", "emulate_bof", "emulate_dp",
                                 "emulate_jjp", "emulate_spike1",
                                 "emulate_spooky"])
def test_every_emulate_tab_launch_carries_the_board(tab):
    with open(os.path.join(REPO, "pinball_decryptor", "webui", "tabs", tab + ".py"),
              encoding="utf-8") as fh:
        assert "rigslot.board_env()" in fh.read()
