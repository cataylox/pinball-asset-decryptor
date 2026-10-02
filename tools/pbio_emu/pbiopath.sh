#!/bin/bash
# pbiopath.sh - sourced by every PB I/O-board rig script.  Owns every path
# the rig uses; nothing else may hard-code one.
#
#   PBIO_SLOT     rig slot (PAD_SLOT, default 0) - several rigs at once
#   PBIO_ROOT     /var/tmp/pad_pbio          everything the rig writes
#   PBIO_CACHE    $PBIO_ROOT/cache           prepared layers (prepare.sh):
#                   os-<image>/root.img      the machine's root partition,
#                                            from a Clonezilla restore ISO
#                   upd-<update>/tree        an update's game/ folder
#                   build-<name>/            a stack of them: layers, title
#   PBIO_RIG      $PBIO_ROOT/rig<slot>       this run: board, logs, pids
#   PBIO_NV       $PBIO_ROOT/nv<slot>        each title's nvram, kept
#   PBIO_DISPLAY  hidden Xvfb display (:200 + slot; BoF :90+, Dutch
#                 Pinball :120+, American Pinball :140+, Spooky :160+,
#                 Predator (tools/pb_emu) :180+)
#
# Alien, ABBA and Queen share their program names (pinprog, vidprog) with
# Predator's rig, so this rig's processes are found by PBIO_MARK in their
# environment, never by name alone.
PBIO_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PBIO_SLOT=${PAD_SLOT:-0}
PBIO_ROOT=${PBIO_ROOT:-/var/tmp/pad_pbio}
PBIO_CACHE=$PBIO_ROOT/cache
PBIO_RIG=$PBIO_ROOT/rig$PBIO_SLOT
PBIO_NV=$PBIO_ROOT/nv$PBIO_SLOT
PBIO_DISPLAY=${PBIO_DISPLAY:-:$((200 + PBIO_SLOT))}

if [ -f "$PBIO_TOOLS/../rigboard.sh" ]; then
    . "$PBIO_TOOLS/../rigboard.sh"
else
    rigboard_post() { :; }; rigboard_clear() { :; }; rigboard_audio() { echo "${2:-0}"; }
    rigboard_visible() { echo "${PAD_VISIBLE:-1}"; }
fi

pbio_game_pid() { cat "$PBIO_RIG/game.pid" 2>/dev/null; }
pbio_game_alive() {
    local p; p=$(pbio_game_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
# Every process of this slot: the namespace holder, the board, Xvfb, pinprog,
# vidprog and anything they started.
pbio_slot_pids() {
    local p
    for p in $(pgrep -f 'pinprog|vidprog|pbioboard\.py|Xvfb|pbio_ns'); do
        tr '\0' '\n' 2>/dev/null < "/proc/$p/environ" | grep -qx "PBIO_MARK=$PBIO_RIG" && echo "$p"
    done
}
# Has this slot's game reached attract mode?  pinprog logs the attract
# display effect once its self-test is done.
pbio_attract() {
    grep -q "System initialized" "$PBIO_RIG/pinprog.log" 2>/dev/null &&
        grep -q "deff_start 01 AMODE" "$PBIO_RIG/pinprog.log" 2>/dev/null
}
# Run a command inside this slot's network namespace (Xvfb's socket and the
# game's port 5555 live there).
pbio_in_net() {
    local x; x=$(cat "$PBIO_RIG/xvfb.pid" 2>/dev/null)
    if [ -n "$x" ] && [ -e "/proc/$x/ns/net" ] && [ "$(cat "$PBIO_RIG/visible" 2>/dev/null)" != 1 ]; then
        nsenter --net="/proc/$x/ns/net" "$@"
    else
        "$@"
    fi
}
