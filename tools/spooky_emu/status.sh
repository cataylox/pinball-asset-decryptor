#!/bin/bash
# status.sh - one key=value per line about this slot's rig, for the app.
# Never prose: the app parses it (webui/rig.parse_status).
#   wsl=1                 always (the app's "WSL answered")
#   running=0|1
#   title= version= pid= rss_kb= uptime_s= display= visible=0|1 slot=
#   attract=0|1           the game has reached attract mode       (while running)
#   hw=<the board's state JSON, one line>                          (while running)
. "$(dirname "$0")/spkpath.sh"
echo "wsl=1"
if spk_game_alive; then
    P=$(spk_game_pid)
    B=$(cat "$SPK_RIG/build" 2>/dev/null)
    echo "running=1"
    echo "title=beetlejuice"
    echo "version=$(tr -d '\r\n ' < "$B/version.txt" 2>/dev/null)"
    echo "pid=$P"
    echo "rss_kb=$(awk '/^VmRSS/ {print $2}' "/proc/$P/status" 2>/dev/null)"
    echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
    echo "display=$(cat "$SPK_RIG/display" 2>/dev/null)"
    echo "visible=$(cat "$SPK_RIG/visible" 2>/dev/null)"
    echo "slot=$SPK_SLOT"
    grep -q 'Attract_mode started' "$SPK_RIG/player.log" 2>/dev/null && echo "attract=1" || echo "attract=0"
    echo "hw=$(python3 "$SPK_TOOLS/spkctl.py" --slot "$SPK_SLOT" state 2>/dev/null)"
else
    echo "running=0"
fi
