#!/bin/bash
# pbpath.sh - sourced by every Pinball Brothers rig script.  Owns every path
# the rig uses; nothing else may hard-code one.
#
#   PB_SLOT     rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   PB_ROOT     /var/tmp/pad_pb               everything the rig writes
#   PB_CACHE    $PB_ROOT/cache/<build>        unpacked updates (prepare.sh):
#                                             the machine's /opt/game
#   PB_ENV      $PB_ROOT/env                  the libraries the machine's OS
#                                             provided (setup.sh)
#   PB_RIG      $PB_ROOT/rig<slot>            this run: the /opt/game tree the
#                                             game sees, logs, pids, sockets
#   PB_USER     the account the game runs as (never root)
#   PB_DISPLAY  hidden Xvfb display for this slot (:180 + slot; BoF uses
#               :90+, Dutch Pinball :120+, American Pinball :140+, Spooky :160+)
#   PB_SHIM     the LD_PRELOAD shim that maps the FAST ports and the machine's
#               paths onto the rig (build.sh)
PB_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PB_SLOT=${PAD_SLOT:-0}
PB_ROOT=${PB_ROOT:-/var/tmp/pad_pb}
PB_CACHE=$PB_ROOT/cache
PB_ENV=$PB_ROOT/env
PB_RIG=$PB_ROOT/rig$PB_SLOT
PB_DISPLAY=${PB_DISPLAY:-:$((180 + PB_SLOT))}
PB_SHIM=$PB_TOOLS/pbshim.so

if [ -f "$PB_TOOLS/../rigboard.sh" ]; then
    . "$PB_TOOLS/../rigboard.sh"
else
    rigboard_post() { :; }; rigboard_clear() { :; }; rigboard_audio() { echo "${2:-0}"; }
    rigboard_visible() { echo "${PAD_VISIBLE:-1}"; }
fi

# The first ordinary account (uid 1000..59999): "pad" in PAD-Runtime.
if [ -z "${PB_USER:-}" ]; then
    PB_USER=$(getent passwd | awk -F: '$3>=1000 && $3<60000 {print $1; exit}')
fi

pb_game_pid() { cat "$PB_RIG/game.pid" 2>/dev/null; }
pb_game_alive() {
    local p; p=$(pb_game_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
# Every process of this slot (game, video, board), found by this rig's marker
# in their environment.
pb_slot_pids() {
    local p
    for p in $(pgrep -f 'pinprog|vidprog|pbfast\.py|Xvfb :'"${PB_DISPLAY#:}"); do
        tr '\0' '\n' 2>/dev/null < "/proc/$p/environ" | grep -qx "PB_MARK=$PB_RIG" && echo "$p"
    done
}
