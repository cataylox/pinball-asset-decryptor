#!/bin/bash
# stop.sh - the app's Stop: end this slot's game and hidden display.
# Last line is always `game=G display=D` (1 = still running); exit 0 only
# when both are 0.
. "$(dirname "$0")/dppath.sh"
bash "$DP_TOOLS/killgame.sh" >/dev/null 2>&1
alive() { local p; p=$(cat "$DP_RIG/$1" 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo 1 || echo 0; }
G=$(alive game.pid); D=$(alive xvfb.pid)
echo "game=$G display=$D"
[ "$G$D" = 00 ]
