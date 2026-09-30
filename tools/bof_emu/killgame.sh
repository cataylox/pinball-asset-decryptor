#!/bin/bash
# killgame.sh - stop this slot's game, boards and hidden display, and PROVE
# they stopped.  Exit 0 when nothing of the slot is left running, 1 otherwise.
. "$(dirname "$0")/bofpath.sh"

stop_pid() {        # <pid>: TERM, wait up to 3 s, then KILL
    local p=$1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || return 0
    kill -TERM "$p" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL "$p" 2>/dev/null
}

GP=$(bof_game_pid)
if [ -n "$GP" ]; then
    # The game was started with setsid: its whole session goes (it forks
    # nothing we want to keep).
    SID=$(ps -o sid= -p "$GP" 2>/dev/null | tr -d ' ')
    [ -n "$SID" ] && pkill -TERM -s "$SID" 2>/dev/null
    stop_pid "$GP"
fi
stop_pid "$(cat "$BOF_RIG/hw/bofhw.pid" 2>/dev/null)"
stop_pid "$(cat "$BOF_RIG/xvfb.pid" 2>/dev/null)"

left=0
for f in game.pid hw/bofhw.pid xvfb.pid; do
    p=$(cat "$BOF_RIG/$f" 2>/dev/null)
    if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
        echo "killgame.sh: $f ($p) still running" >&2
        left=1
    else
        rm -f "$BOF_RIG/$f"
    fi
done
[ $left = 0 ] && { rigboard_clear bof "$BOF_SLOT"; echo stopped; }
exit $left
