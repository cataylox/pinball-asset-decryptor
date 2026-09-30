#!/bin/bash
# killgame.sh - stop this slot's game and PROVE it stopped.  Exit 0 when
# nothing of the slot is left running.  Only this slot's processes (by
# CGC_MARK): other rigs run qemu-arm too.
. "$(dirname "$0")/cgcpath.sh"

stop_pid() {        # <pid>: TERM, wait up to 3 s, then KILL
    local p=$1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || return 0
    kill -TERM "$p" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL "$p" 2>/dev/null
}

stop_pid "$(cgc_game_pid)"
for p in $(cgc_slot_pids); do stop_pid "$p"; done
# run_game.sh's namespace shell exec'd into runuser; a runuser whose game
# is gone may linger - checked by command line, so a reused pid is left alone.
ns=$(cat "$CGC_RIG/ns.pid" 2>/dev/null)
if [ -n "$ns" ] && [ -r "/proc/$ns/cmdline" ] &&
   tr '\0' ' ' 2>/dev/null < "/proc/$ns/cmdline" | grep -q "CGC_MARK=$CGC_RIG"; then
    kill -KILL "$ns" 2>/dev/null
fi
rm -f "$CGC_RIG/ns.pid"

left=$(cgc_slot_pids)
if [ -n "$left" ]; then
    echo "killgame.sh: still running:" $left >&2
    exit 1
fi
rm -f "$CGC_RIG/game.pid"
rigboard_clear cgc "$CGC_SLOT"
echo stopped
