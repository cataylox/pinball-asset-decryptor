#!/bin/bash
# status.sh - one line on this slot's game: running or not, which build, and
# the last lines it logged.
. "$(dirname "$0")/spkpath.sh"
if spk_game_alive; then
    echo "running: slot $SPK_SLOT, $(basename "$(cat "$SPK_RIG/build")"), display $(cat "$SPK_RIG/display"), pid $(spk_game_pid)"
else
    echo "stopped: slot $SPK_SLOT"
fi
[ -f "$SPK_RIG/player.log" ] && grep -v '^\s*$' "$SPK_RIG/player.log" | tail -5
