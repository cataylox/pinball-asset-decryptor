#!/bin/bash
# killgame.sh - stop this slot's game (pinprog, vidprog), its boards and
# hidden display, and PROVE they stopped.  Exit 0 when nothing of the slot is
# left running.
. "$(dirname "$0")/pbpath.sh"

stop_pid() {        # <pid>: TERM, wait up to 3 s, then KILL
    local p=$1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || return 0
    kill -TERM "$p" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL "$p" 2>/dev/null
}

# The game first (it saves nvram on TERM), then the rest.
stop_pid "$(pb_game_pid)"
for p in $(pb_slot_pids); do stop_pid "$p"; done
stop_pid "$(cat "$PB_RIG/xvfb.pid" 2>/dev/null)"

left=$(pb_slot_pids)
xp=$(cat "$PB_RIG/xvfb.pid" 2>/dev/null)
if [ -n "$xp" ] && kill -0 "$xp" 2>/dev/null; then left="$left xvfb:$xp"; fi
if [ -n "$left" ]; then
    echo "killgame.sh: still running:" $left >&2
    exit 1
fi
rm -f "$PB_RIG/game.pid" "$PB_RIG/xvfb.pid"
rigboard_clear pb "$PB_SLOT"
echo stopped
