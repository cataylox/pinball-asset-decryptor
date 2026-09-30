#!/bin/bash
# killgame.sh - stop this slot's game and hidden display, and PROVE they
# stopped.  Exit 0 when nothing of the slot is left running, 1 otherwise.
. "$(dirname "$0")/appath.sh"

stop_pid() {        # <pid>: TERM, wait up to 3 s, then KILL
    local p=$1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || return 0
    kill -TERM "$p" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL "$p" 2>/dev/null
}

for p in $(ap_slot_pids); do stop_pid "$p"; done
# the volume follower (apvol.py) ends with the game; this is for a hard stop
pkill -f "apvol\.py .*--rig $AP_RIG " 2>/dev/null
stop_pid "$(cat "$AP_RIG/xvfb.pid" 2>/dev/null)"

left=$(ap_slot_pids)
xp=$(cat "$AP_RIG/xvfb.pid" 2>/dev/null)
if [ -n "$xp" ] && kill -0 "$xp" 2>/dev/null; then left="$left xvfb:$xp"; fi
if [ -n "$left" ]; then
    echo "killgame.sh: still running:" $left >&2
    exit 1
fi
rm -f "$AP_RIG/game.pid" "$AP_RIG/xvfb.pid"
rigboard_clear ap "$AP_SLOT"
echo stopped
