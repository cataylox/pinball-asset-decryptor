#!/bin/bash
# appath.sh - sourced by every American Pinball rig script.  Owns every path
# the rig uses; nothing else may hard-code one.
#
#   AP_SLOT     rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   AP_ROOT     /var/tmp/pad_ap              everything the rig writes
#   AP_PY       $AP_ROOT/py27                the Python 2.7 the games run on
#                                            (setup.sh builds it)
#   AP_PY3      $AP_ROOT/py3                 Python 3.14 for Galactic Tank
#                                            Force's 2026 build (setup.sh)
#   AP_AV       $AP_ROOT/av                  GStreamer + SDL2 for AP's native
#                                            apiav (setup.sh builds it)
#   AP_CACHE    $AP_ROOT/cache/<build>       unpacked .pkg builds (prepare.py)
#   AP_RIG      $AP_ROOT/rig<slot>           this run: the game folder the
#                                            game runs in, logs, pids, FIFO
#   AP_USER     the account the game runs as (NEVER root: the launchers
#               shell out to unlock-root, cp into /usr/bin and friends)
#   AP_DISPLAY  hidden Xvfb display for this slot (:140 + slot; BoF uses
#               :90+, Dutch Pinball :120+)
AP_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
AP_SLOT=${PAD_SLOT:-0}
AP_ROOT=${AP_ROOT:-/var/tmp/pad_ap}
AP_PY=$AP_ROOT/py27
AP_PY3=$AP_ROOT/py3
AP_AV=$AP_ROOT/av
AP_CACHE=$AP_ROOT/cache
AP_RIG=$AP_ROOT/rig$AP_SLOT
AP_DISPLAY=${AP_DISPLAY:-:$((140 + AP_SLOT))}

# The rig board (PAD-296): tools/rigboard.sh, shared by every emulator, posts
# this rig's runs where the triage dashboard and the app can see them.
if [ -f "$AP_TOOLS/../rigboard.sh" ]; then
    . "$AP_TOOLS/../rigboard.sh"
else
    rigboard_post() { :; }; rigboard_clear() { :; }; rigboard_audio() { echo "${2:-0}"; }
fi

# The first ordinary account (uid 1000..59999): "pad" in PAD-Runtime.
if [ -z "${AP_USER:-}" ]; then
    AP_USER=$(getent passwd | awk -F: '$3>=1000 && $3<60000 {print $1; exit}')
fi

ap_game_pid() { cat "$AP_RIG/game.pid" 2>/dev/null; }
ap_game_alive() {
    local p; p=$(ap_game_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
# Every process of this slot's game: python2 running aprun.py (and apiav) with this
# rig's log in its environment (its cwd is inside its own mount namespace, so
# it does not show which rig it is).
ap_slot_pids() {
    local p
    for p in $(pgrep -f 'aprun\.py |apiav '); do
        tr '\0' '\n' < "/proc/$p/environ" 2>/dev/null | grep -qx "AP_LOG=$AP_RIG/rig.log" && echo "$p"
    done
}
