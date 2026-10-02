#!/bin/bash
# procpath.sh - sourced by every proc_emu script.  Owns every path the P-ROC
# rig uses; nothing else may hard-code one.
#
#   PROC_SLOT    rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   PROC_ROOT    /var/tmp/pad_proc          everything the rig writes
#   PROC_LIB     $PROC_ROOT/lib             built fakeftdi (libftdi1.so.2)
#   PROC_RIG     $PROC_ROOT/rig<slot>       this run: sockets, logs, pids
#   PROC_FPGA    $PROC_RIG/fpga.sock        the emulated board (prochw.py)
#   PROC_CTL     $PROC_RIG/ctl.sock         switches in, state out
#   PROC_STUB    the pure-Python pinproc (put first on PYTHONPATH)
PROC_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROC_SLOT=${PAD_SLOT:-0}
PROC_ROOT=${PROC_ROOT:-/var/tmp/pad_proc}
PROC_LIB=$PROC_ROOT/lib
PROC_RIG=$PROC_ROOT/rig$PROC_SLOT
PROC_FPGA=$PROC_RIG/fpga.sock
PROC_CTL=$PROC_RIG/ctl.sock
PROC_STUB=$PROC_TOOLS/pystub
PROC_FTDI=$PROC_LIB/libftdi1.so.2

# The rig board (PAD-296): tools/rigboard.sh, shared by every emulator, posts
# this rig's runs where the triage dashboard and the app can see them.
if [ -f "$PROC_TOOLS/../rigboard.sh" ]; then
    . "$PROC_TOOLS/../rigboard.sh"
else
    rigboard_post() { :; }; rigboard_clear() { :; }; rigboard_audio() { echo "${2:-0}"; }
    rigboard_visible() { echo "${PAD_VISIBLE:-1}"; }
fi

proc_hw_pid() { cat "$PROC_RIG/prochw.pid" 2>/dev/null; }
proc_hw_alive() {
    local p; p=$(proc_hw_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
proc_game_pid() { cat "$PROC_RIG/game.pid" 2>/dev/null; }
proc_game_alive() {
    local p; p=$(proc_game_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
