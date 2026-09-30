#!/bin/bash
# stop.sh - Stop: end this slot's game and ball helper.  Last line is always
# `game=G helper=H` (1 = still running); exit 0 only when both are 0.
. "$(dirname "$0")/cgcpfpath.sh"
bash "$CGCPF_TOOLS/killgame.sh" >/dev/null 2>&1
G=0; cgcpf_find_game >/dev/null && G=1
H=0; [ -n "$(cgcpf_slot_pids)" ] && H=1
echo "game=$G helper=$H"
[ "$G$H" = 00 ]
