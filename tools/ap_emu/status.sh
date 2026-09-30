#!/bin/bash
# status.sh - one key=value per line about this slot's rig, for the app (and
# for you).  Never prose: the app parses it (webui/rig.parse_status).
#   wsl=1                 always (the app's "WSL answered")
#   running=0|1
#   title= build= version= pid= rss_kb= uptime_s= display= visible=0|1
#   window=WxH ...  av=0|1  switches=<count>  slot=           (while running)
#   switches_json=<the rig's switch table, Linux path>        (once written)
#   ready=0|1             1 = setup.sh has built the envs
# The game's last lines: `tail $AP_RIG/game.out`.
. "$(dirname "$0")/appath.sh"
echo "wsl=1"
[ -f "$AP_PY/.ready" ] && echo "ready=1" || echo "ready=0"
if ap_game_alive; then
    P=$(ap_game_pid)
    B=$(cat "$AP_RIG/build" 2>/dev/null)
    echo "running=1"
    echo "title=$(cat "$AP_RIG/title" 2>/dev/null)"
    echo "build=$(basename "$B")"
    # houdini_21.10.25 -> 21.10.25
    echo "version=$(basename "$B" | sed -n 's/^[^_]*_//p')"
    echo "pid=$P"
    # the game and (A/V titles) apiav
    rss=0
    for p in $(ap_slot_pids); do
        r=$(awk '/^VmRSS/ {print $2}' "/proc/$p/status" 2>/dev/null)
        rss=$((rss + ${r:-0}))
    done
    echo "rss_kb=$rss"
    echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
    echo "display=$(cat "$AP_RIG/display" 2>/dev/null)"
    echo "visible=$(cat "$AP_RIG/visible" 2>/dev/null)"
    # every on-screen window the game opened (one parked off-screen is not)
    echo "window=$(awk '/ window: / {split($3, a, /[x+]/); if (a[3] < 2560) print a[1] "x" a[2]}' \
        "$AP_RIG/rig.log" 2>/dev/null | sort -u | paste -sd' ')"
    [ -f "$AP_RIG/av" ] && echo "av=1" || echo "av=0"
    echo "switches=$(grep -c '"n":' "$AP_RIG/switches.json" 2>/dev/null || grep -c . "$AP_RIG/switches" 2>/dev/null)"
    [ -f "$AP_RIG/switches.json" ] && echo "switches_json=$AP_RIG/switches.json"
    echo "slot=$AP_SLOT"
else
    echo "running=0"
fi
