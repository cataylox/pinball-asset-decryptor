#!/bin/bash
# status.sh - one key=value per line about this slot's rig, for the app (and
# for you).  The same keys as the AP and Spooky rigs:
#   wsl=1 running=0|1
#   title= title_name= build= version= pid= rss_kb= uptime_s= display=
#   visible=0|1 window=WxH switches=<count> switches_json= slot= attract=0|1
. "$(dirname "$0")/pbiopath.sh"
echo "wsl=1"
if pbio_game_alive; then
    P=$(pbio_game_pid)
    B=$(cat "$PBIO_RIG/build" 2>/dev/null)
    T=$(cat "$PBIO_RIG/title" 2>/dev/null)
    echo "running=1"
    echo "title=$T"
    echo "title_name=$(python3 "$PBIO_TOOLS/pbiotitles.py" get "$T" name)"
    echo "build=$(basename "$B")"
    echo "version=$(sed -n 's/^[0-9]* Game Revision //p' "$PBIO_RIG/pinprog.log" 2>/dev/null | head -1)"
    echo "pid=$P"
    echo "rss_kb=$(awk '/^VmRSS/ {print $2}' "/proc/$P/status" 2>/dev/null)"
    echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
    echo "display=$(cat "$PBIO_RIG/display" 2>/dev/null)"
    echo "visible=$(cat "$PBIO_RIG/visible" 2>/dev/null)"
    echo "window=$(cat "$PBIO_RIG/window" 2>/dev/null)"
    echo "switches=$(grep -c '"n":' "$PBIO_RIG/switches.json" 2>/dev/null)"
    [ -f "$PBIO_RIG/switches.json" ] && echo "switches_json=$PBIO_RIG/switches.json"
    echo "slot=$PBIO_SLOT"
    pbio_attract && echo "attract=1" || echo "attract=0"
else
    echo "running=0"
fi
