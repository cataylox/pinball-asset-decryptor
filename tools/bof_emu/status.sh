#!/bin/bash
# status.sh - one key=value per line about this slot's rig, for the app.
#   running=0|1  title=  pid=  display=  visible=0|1
#   hw=<bofhw.py state JSON>   (only while running)
. "$(dirname "$0")/bofpath.sh"
if bof_game_alive; then
    echo "running=1"
    echo "title=$(cat "$BOF_RIG/title" 2>/dev/null)"
    echo "pid=$(bof_game_pid)"
    echo "display=$(cat "$BOF_RIG/display" 2>/dev/null)"
    echo "visible=$(cat "$BOF_RIG/visible" 2>/dev/null)"
    echo "hw=$(python3 "$BOF_TOOLS/bofctl.py" --slot "$BOF_SLOT" state 2>/dev/null)"
else
    echo "running=0"
fi
