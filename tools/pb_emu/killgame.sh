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
# The namespace shell (run_game.sh's ns.sh) and its runuser wrappers: they
# have no PB_MARK, and once their programs are gone the wrappers sit stopped
# with zombies under them.  Checked by name, so a reused pid is left alone.
ns=$(cat "$PB_RIG/ns.pid" 2>/dev/null)
if [ -n "$ns" ] && tr '\0' ' ' < "/proc/$ns/cmdline" 2>/dev/null | grep -q "$PB_RIG/ns.sh"; then
    for c in $(ps -o pid= --ppid "$ns"); do kill -KILL "$c" 2>/dev/null; done
    kill -KILL "$ns" 2>/dev/null
fi
rm -f "$PB_RIG/ns.pid"

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
