#!/bin/bash
# cgcpath.sh - sourced by every Chicago Gaming rig script.  Owns every path
# the rig uses; nothing else may hard-code one.
#
#   CGC_SLOT     rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   CGC_ROOT     /var/tmp/pad_cgc              everything the rig writes
#   CGC_CACHE    $CGC_ROOT/cache/<build>       a card taken apart
#                                              (prepare.sh): the game folder
#                                              (emumm), its ROM, sounds and
#                                              art, and sysroot/ - the
#                                              machine's own armhf libraries
#   CGC_NV       $CGC_ROOT/nv<slot>/<title>    the game's FRAM (settings,
#                                              audits, high scores), kept
#   CGC_RIG      $CGC_ROOT/rig<slot>           this run: the game's home, the
#                                              frame buffer file, logs, pids
#   CGC_USER     the account the game runs as (never root: /dev/mem)
#   CGC_SHIM     the armhf LD_PRELOAD shim (build.sh)
CGC_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CGC_SLOT=${PAD_SLOT:-0}
CGC_ROOT=${CGC_ROOT:-/var/tmp/pad_cgc}
CGC_CACHE=$CGC_ROOT/cache
CGC_RIG=$CGC_ROOT/rig$CGC_SLOT
CGC_SHIM=$CGC_TOOLS/cgcshim.so

if [ -f "$CGC_TOOLS/../rigboard.sh" ]; then
    . "$CGC_TOOLS/../rigboard.sh"
else
    rigboard_post() { :; }; rigboard_clear() { :; }; rigboard_audio() { echo "${2:-0}"; }
    rigboard_visible() { echo "${PAD_VISIBLE:-1}"; }
fi

# The first ordinary account (uid 1000..59999): "pad" in PAD-Runtime.
if [ -z "${CGC_USER:-}" ]; then
    CGC_USER=$(getent passwd | awk -F: '$3>=1000 && $3<60000 {print $1; exit}')
fi

# qemu-arm-static: the runtime's, or any on PATH.
CGC_QEMU=$(command -v qemu-arm-static || command -v qemu-arm || true)

cgc_game_pid() { cat "$CGC_RIG/game.pid" 2>/dev/null; }
cgc_game_alive() {
    local p; p=$(cgc_game_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
# Every process of this slot (the game under qemu-arm), found by this rig's
# marker in its environment - never by name: other rigs run qemu-arm too.
cgc_slot_pids() {
    local p
    for p in $(pgrep -f 'qemu-arm'); do
        tr '\0' '\n' 2>/dev/null < "/proc/$p/environ" | grep -qx "CGC_MARK=$CGC_RIG" && echo "$p"
    done
}
