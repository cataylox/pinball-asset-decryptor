#!/bin/bash
# status.sh - one line on this slot's game: running or not, which build, and
# the last lines it wrote.
. "$(dirname "$0")/appath.sh"
if ap_game_alive; then
    echo "running: slot $AP_SLOT, $(basename "$(cat "$AP_RIG/build")"), display $(cat "$AP_RIG/display"), pid $(ap_game_pid)"
else
    echo "stopped: slot $AP_SLOT"
fi
[ -f "$AP_RIG/game.out" ] && tail -5 "$AP_RIG/game.out"
