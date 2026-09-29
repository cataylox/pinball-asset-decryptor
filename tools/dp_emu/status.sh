#!/bin/bash
# status.sh - one line on this slot's game: running or not, which build, and
# the last lines it wrote.
. "$(dirname "$0")/dppath.sh"
if dp_game_alive; then
    echo "running: slot $DP_SLOT, $(basename "$(cat "$DP_RIG/build")") $(cat "$DP_RIG/ver"), display $(cat "$DP_RIG/display"), pid $(dp_game_pid)"
else
    echo "stopped: slot $DP_SLOT"
fi
[ -f "$DP_RIG/game.out" ] && tail -5 "$DP_RIG/game.out"
