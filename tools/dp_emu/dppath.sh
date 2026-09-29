#!/bin/bash
# dppath.sh - sourced by every Dutch Pinball rig script.  Owns every path the
# rig uses; nothing else may hard-code one.
#
#   DP_SLOT     rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   DP_ROOT     /var/tmp/pad_dp              everything the rig writes
#   DP_CACHE    $DP_ROOT/cache/<build>       prepared builds (prepare.py):
#                                            assets/ + <version>/ + version
#   DP_RIG      $DP_ROOT/rig<slot>           this run: the game folder the
#                                            game runs in, logs, pids, FIFO
#   DP_USER     the account the game runs as (NEVER root: its operator menu
#               shells out to `date -s` and friends)
#   DP_DISPLAY  hidden Xvfb display for this slot (:120 + slot; BoF uses :90+)
DP_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DP_SLOT=${PAD_SLOT:-0}
DP_ROOT=${DP_ROOT:-/var/tmp/pad_dp}
DP_CACHE=$DP_ROOT/cache
DP_RIG=$DP_ROOT/rig$DP_SLOT
DP_DISPLAY=${DP_DISPLAY:-:$((120 + DP_SLOT))}
DP_SHIM=$DP_ROOT/dpinput.so

# The first ordinary account (uid 1000..59999): "pad" in PAD-Runtime.
if [ -z "${DP_USER:-}" ]; then
    DP_USER=$(getent passwd | awk -F: '$3>=1000 && $3<60000 {print $1; exit}')
fi

dp_game_pid() { cat "$DP_RIG/game.pid" 2>/dev/null; }
dp_game_alive() {
    local p; p=$(dp_game_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
