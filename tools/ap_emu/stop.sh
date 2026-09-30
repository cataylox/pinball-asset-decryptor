#!/bin/bash
# stop.sh - the app's Stop: end this slot's game (and apiav) and hidden
# display.  Last line is always `game=G display=D` (1 = still running); exit
# 0 only when both are 0.
. "$(dirname "$0")/appath.sh"
bash "$AP_TOOLS/killgame.sh" >/dev/null 2>&1
alive() { local p; p=$(cat "$AP_RIG/$1" 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo 1 || echo 0; }
G=0; [ -n "$(ap_slot_pids)" ] && G=1
D=$(alive xvfb.pid)
echo "game=$G display=$D"
[ "$G$D" = 00 ]
