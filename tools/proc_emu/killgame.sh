#!/bin/bash
# killgame.sh - stop this slot's game and board, and PROVE they stopped.
# Exit 0 when nothing of the slot is left running, 1 otherwise.
. "$(dirname "$0")/procpath.sh"

stop_pid() {        # <pid>: TERM, wait up to 3 s, then KILL
    local p=$1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || return 0
    kill -TERM "$p" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL "$p" 2>/dev/null
}

GP=$(proc_game_pid)
if [ -n "$GP" ] && kill -0 "$GP" 2>/dev/null; then
    # run_py.sh --detach starts the game with setsid: its session goes too.
    SID=$(ps -o sid= -p "$GP" 2>/dev/null | tr -d ' ')
    [ -n "$SID" ] && pkill -TERM -s "$SID" 2>/dev/null
    stop_pid "$GP"
fi
stop_pid "$(proc_hw_pid)"

left=0
for f in game.pid prochw.pid; do
    p=$(cat "$PROC_RIG/$f" 2>/dev/null)
    if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
        echo "killgame.sh: $f ($p) still running" >&2
        left=1
    else
        rm -f "$PROC_RIG/$f"
    fi
done
[ $left = 0 ] && echo stopped
exit $left
