#!/bin/bash
# stop.sh - the app's Stop: end this slot's game, board and hidden display.
# Last line is always `game=G board=B display=D` (1 = still running);
# exit 0 only when all three are 0.
. "$(dirname "$0")/pbpath.sh"
bash "$PB_TOOLS/killgame.sh" >/dev/null 2>&1
G=0; pb_game_alive && G=1
B=0; [ -n "$(pb_slot_pids)" ] && B=1
D=0; p=$(cat "$PB_RIG/xvfb.pid" 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null && D=1
echo "game=$G board=$B display=$D"
[ "$G$B$D" = 000 ]
