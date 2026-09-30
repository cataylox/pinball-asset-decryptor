#!/bin/bash
# status.sh - one key=value per line about this slot's rig, for the app.
# Never prose: the app parses it (webui/rig.parse_status).
#   wsl=1                 always (the app's "WSL answered")
#   running=0|1
#   title= version= build= pid= rss_kb= uptime_s= display= visible=0|1
#   window=WxH  switches=<count>  slot=                     (while running)
#   switches_json=<the rig's switch table, Linux path>
. "$(dirname "$0")/dppath.sh"
echo "wsl=1"
if dp_game_alive; then
    P=$(dp_game_pid)
    B=$(cat "$DP_RIG/build" 2>/dev/null)
    echo "running=1"
    echo "title=$(cat "$B/title" 2>/dev/null)"
    echo "version=$(cat "$DP_RIG/ver" 2>/dev/null)"
    echo "build=$(basename "$B")"
    echo "pid=$P"
    # The bootloader is the pid; the game is its child - count them all.
    rss=0
    for p in $P $(pgrep -P "$P"); do
        r=$(awk '/^VmRSS/ {print $2}' "/proc/$p/status" 2>/dev/null)
        rss=$((rss + ${r:-0}))
    done
    echo "rss_kb=$rss"
    echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
    echo "display=$(cat "$DP_RIG/display" 2>/dev/null)"
    echo "visible=$(cat "$DP_RIG/visible" 2>/dev/null)"
    # every window the game opened (AAIW has two: its LCD and the round one)
    echo "window=$(grep '^video:' "$DP_RIG/rig.log" 2>/dev/null | cut -d' ' -f2 | cut -d@ -f1 | sort -u | paste -sd' ')"
    echo "switches=$(grep -c '"n":' "$DP_RIG/switches.json" 2>/dev/null)"
    echo "kind=$(cat "$DP_RIG/kind" 2>/dev/null || echo tbl)"
    echo "switches_json=$DP_RIG/switches.json"
    echo "slot=$DP_SLOT"
else
    echo "running=0"
fi
