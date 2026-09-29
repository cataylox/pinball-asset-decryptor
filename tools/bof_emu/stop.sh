#!/bin/bash
# stop.sh - the app's Stop: end this slot's game, boards and hidden display.
# Last line is always `game=G boards=B display=D` (1 = still running);
# exit 0 only when all three are 0.
. "$(dirname "$0")/bofpath.sh"
bash "$BOF_TOOLS/killgame.sh" >/dev/null 2>&1
alive() { local p; p=$(cat "$BOF_RIG/$1" 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo 1 || echo 0; }
G=$(alive game.pid); B=$(alive hw/bofhw.pid); D=$(alive xvfb.pid)
echo "game=$G boards=$B display=$D"
[ "$G$B$D" = 000 ]
