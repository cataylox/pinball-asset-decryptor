#!/bin/bash
# killgame.sh - stop this slot's game, its board and hidden display, and
# PROVE they stopped.  Exit 0 when nothing of the slot is left running.
. "$(dirname "$0")/pbiopath.sh"

stop_pid() {        # <pid>: TERM, wait up to 3 s, then KILL
    local p=$1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || return 0
    kill -CONT "$p" 2>/dev/null
    kill -TERM "$p" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL "$p" 2>/dev/null
}

for p in $(pbio_slot_pids); do stop_pid "$p"; done
left=$(pbio_slot_pids)
if [ -n "$left" ]; then
    echo "killgame.sh: still running:" $left >&2
    exit 1
fi
rm -f "$PBIO_RIG/game.pid" "$PBIO_RIG/game.pids" "$PBIO_RIG/xvfb.pid"
rigboard_clear pbio "$PBIO_SLOT"
echo stopped
