#!/bin/bash
# killgame.sh - stop this slot's Pulp Fiction (the game, its namespace,
# pfball.py) and PROVE they stopped.  Exit 0 when nothing of the slot is
# left running.
. "$(dirname "$0")/cgcpfpath.sh"

stop_pid() {        # <pid>: TERM, wait up to 3 s, then KILL
    local p=$1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || return 0
    kill -TERM "$p" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL "$p" 2>/dev/null
}

# Never `pkill pin`: another slot's game has the same name.  The game is
# found by its root (this slot's overlay), the rest by CGCPF_MARK.
stop_pid "$(cgcpf_find_game || cgcpf_game_pid)"
for p in $(cgcpf_slot_pids); do stop_pid "$p"; done
# The namespace's first process (ns.sh) ends when the game does; this is
# for one left waiting on a mount.
ns=$(cat "$CGCPF_RIG/ns.pid" 2>/dev/null)
if [ -n "$ns" ] && tr '\0' ' ' < "/proc/$ns/cmdline" 2>/dev/null | grep -q "$CGCPF_RIG/ns.sh"; then
    kill -KILL "$ns" 2>/dev/null
fi
rm -f "$CGCPF_RIG/ns.pid"

left="$(cgcpf_find_game) $(cgcpf_slot_pids)"
if [ -n "${left// /}" ]; then
    echo "killgame.sh: still running:" $left >&2
    exit 1
fi
rm -f "$CGCPF_RIG/game.pid"
rigboard_clear cgcpf "$CGCPF_SLOT"
echo stopped
