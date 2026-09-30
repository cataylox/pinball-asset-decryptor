#!/bin/bash
# cgcpfpath.sh - sourced by every CGC Pulp Fiction rig script.  Owns every
# path the rig uses; nothing else may hard-code one.
#
#   CGCPF_SLOT    rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   CGCPF_ROOT    /var/tmp/pad_cgcpf            everything small the rig writes
#   CGCPF_CACHE   the machine's root filesystem, carved out of the installer
#                 image by prepare.py (<build>/rootfs.img, ~3.4 GB, 2.5 GB of
#                 it used).  PAD-Runtime's disk is small, so when its /var/tmp
#                 has under 4 GB free the cache goes to C:\tmp\pad_cgcpf.
#   CGCPF_RIG     $CGCPF_ROOT/rig<slot>         this run: the overlay (upper,
#                 work, root), io/ (the game sees it at /pfrig/io: io.bin,
#                 fb.bin, shim.log), tmp/ (its /tmp: z4.log), logs, pids
#   CGCPF_NV      $CGCPF_ROOT/nv<slot>/<build>  the FRAM (settings, audits,
#                 high scores), kept between runs (CGCPF_FRESH=1 starts over)
#   CGCPF_SHIM    pfshim.so (build.sh)
CGCPF_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CGCPF_SLOT=${PAD_SLOT:-0}
CGCPF_ROOT=${CGCPF_ROOT:-/var/tmp/pad_cgcpf}
CGCPF_RIG=$CGCPF_ROOT/rig$CGCPF_SLOT
CGCPF_SHIM=$CGCPF_TOOLS/pfshim.so
export CGCPF_RIG

if [ -z "${CGCPF_CACHE:-}" ]; then
    if [ -d "$CGCPF_ROOT/cache" ] && [ -n "$(ls -A "$CGCPF_ROOT/cache" 2>/dev/null)" ]; then
        CGCPF_CACHE=$CGCPF_ROOT/cache
    elif [ -d /mnt/c/tmp/pad_cgcpf ]; then
        CGCPF_CACHE=/mnt/c/tmp/pad_cgcpf
    else
        mkdir -p "$CGCPF_ROOT"
        free=$(df -Pk "$CGCPF_ROOT" | awk 'NR==2{print $4}')
        if [ "${free:-0}" -ge $((4 * 1024 * 1024)) ] || [ ! -d /mnt/c/tmp ]; then
            CGCPF_CACHE=$CGCPF_ROOT/cache
        else
            CGCPF_CACHE=/mnt/c/tmp/pad_cgcpf
        fi
    fi
fi

if [ -f "$CGCPF_TOOLS/../rigboard.sh" ]; then
    . "$CGCPF_TOOLS/../rigboard.sh"
else
    rigboard_post() { :; }; rigboard_clear() { :; }; rigboard_audio() { echo "${2:-0}"; }
fi

# The game's state word (pin 1.0.2: 0x4503b4): 1 attract, 2 a game,
# 4 a start waiting on a ball search.  Read through peek.py.
CGCPF_STATE_ADDR=0x4503b4
CGCPF_CREDITS_ADDR=0x44c208

cgcpf_game_pid() { cat "$CGCPF_RIG/game.pid" 2>/dev/null; }
cgcpf_game_alive() {
    local p; p=$(cgcpf_game_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
# The game process: qemu running ./pin with this slot's root as its root.
cgcpf_find_game() {
    local p
    for p in $(pgrep -f 'qemu.*pin|arm-binfmt.*pin'); do
        [ "$(readlink "/proc/$p/root" 2>/dev/null)" = "$CGCPF_RIG/root" ] && { echo "$p"; return 0; }
    done
    return 1
}
# Every other process of this slot (pfball.py, the namespace shell), found
# by this rig's marker in their environment.
cgcpf_slot_pids() {
    local p
    for p in $(pgrep -f 'pfball\.py|cgcpf_emu/ns\.sh|rig[0-9]+/ns\.sh'); do
        tr '\0' '\n' 2>/dev/null < "/proc/$p/environ" | grep -qx "CGCPF_MARK=$CGCPF_RIG" && echo "$p"
    done
}
cgcpf_peek() {      # <addr>: a u32 of the running game's memory
    python3 "$CGCPF_TOOLS/peek.py" "$(cgcpf_game_pid)" u32 "$1" 2>/dev/null
}
cgcpf_log() { echo "$CGCPF_RIG/tmp/z4.log"; }
