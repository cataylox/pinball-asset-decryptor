#!/bin/bash
# bofpath.sh - sourced by every rig script.  Owns every path the BoF rig uses;
# nothing else may hard-code one.
#
#   BOF_SLOT     rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   BOF_ROOT     /var/tmp/pad_bof            everything the rig writes
#   BOF_CACHE    $BOF_ROOT/cache             decrypted builds, one dir each
#   BOF_HOMES    $BOF_ROOT/home/<title>      the game's user:// (settings,
#                                            audits, high scores) - per title,
#                                            kept between runs like a machine
#   BOF_RIG      $BOF_ROOT/rig<slot>         this run: ports, logs, pids
#   BOF_USER     the account the game runs as (NEVER root: see run_game.sh)
#   BOF_DISPLAY  hidden Xvfb display for this slot
BOF_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BOF_SLOT=${PAD_SLOT:-0}
BOF_ROOT=${BOF_ROOT:-/var/tmp/pad_bof}
BOF_CACHE=$BOF_ROOT/cache
BOF_HOMES=$BOF_ROOT/home
BOF_RIG=$BOF_ROOT/rig$BOF_SLOT
BOF_DISPLAY=${BOF_DISPLAY:-:$((90 + BOF_SLOT))}
BOF_SHIM=${BOF_SHIM:-$BOF_TOOLS/bofhwshim.so}

# The first ordinary account (uid 1000..59999): "pad" in PAD-Runtime.
if [ -z "${BOF_USER:-}" ]; then
    BOF_USER=$(getent passwd | awk -F: '$3>=1000 && $3<60000 {print $1; exit}')
fi

bof_game_pid() { cat "$BOF_RIG/game.pid" 2>/dev/null; }
bof_game_alive() {
    local p; p=$(bof_game_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
