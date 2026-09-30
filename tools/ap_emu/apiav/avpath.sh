#!/bin/bash
# avpath.sh - sourced by every script of the American Pinball apiav rig (the
# titles whose screens and sound come from AP's native `apiav` process:
# Barry-O's BBQ Challenge, Hot Wheels, Galactic Tank Force).  Owns every path
# the rig uses; nothing else may hard-code one.
#
#   AV_SLOT     rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   AV_ROOT     /var/tmp/pad_apav            everything the rig writes
#   AV_ENV      $AV_ROOT/env                 Python 3.12 + SDL2 + GStreamer
#                                            (setup.sh builds it)
#   AV_CACHE    $AV_ROOT/cache/<build>       unpacked .pkg builds (prepare.py)
#   AV_RIG      $AV_ROOT/rig<slot>           this run: /game, logs, pids
#   AV_USER     the account the game runs as (never root: the launcher
#               runs `umount /media/*`, the service menu runs iwctl, shutdown)
#   AV_DISPLAY  hidden Xvfb display for this slot (:160 + slot; BoF uses :90+,
#               Dutch Pinball :120+, the older AP titles :140+)
#
# apiav listens on localhost:16726 and the game dials it there (no option
# for either), so every slot runs both in a network namespace of its own
# (run_game.sh): slots never meet, and nothing else on the PC can.
AV_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
AV_PROC=$(cd "$AV_TOOLS/../../proc_emu" && pwd)
AV_SLOT=${PAD_SLOT:-0}
AV_ROOT=${AV_ROOT:-/var/tmp/pad_apav}
AV_ENV=$AV_ROOT/env
AV_CACHE=$AV_ROOT/cache
AV_RIG=$AV_ROOT/rig$AV_SLOT
AV_DISPLAY=${AV_DISPLAY:-:$((160 + AV_SLOT))}

if [ -z "${AV_USER:-}" ]; then
    AV_USER=$(getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 {print $1; exit}')
fi

av_pid() { cat "$AV_RIG/$1.pid" 2>/dev/null; }
av_alive() {
    local p; p=$(av_pid "$1")
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
