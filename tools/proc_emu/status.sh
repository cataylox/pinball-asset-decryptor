#!/bin/bash
# status.sh - one key=value per line about this slot's rig, for the app.
# Never prose: callers parse it.
#   wsl=1 slot=
#   running=0|1                 the game (run_py.sh --detach)
#   pid= rss_kb= uptime_s=      while the game runs
#   board=0|1                   prochw.py
#   hw=<prochw.py state JSON, one line>   while the board runs
. "$(dirname "$0")/procpath.sh"
echo "wsl=1"
echo "slot=$PROC_SLOT"
if proc_game_alive; then
    P=$(proc_game_pid)
    echo "running=1"
    echo "pid=$P"
    echo "rss_kb=$(awk '/^VmRSS/ {print $2}' "/proc/$P/status" 2>/dev/null)"
    echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
else
    echo "running=0"
fi
if proc_hw_alive; then
    echo "board=1"
    echo "hw=$(python3 "$PROC_TOOLS/procctl.py" --slot "$PROC_SLOT" state 2>/dev/null)"
else
    echo "board=0"
fi
