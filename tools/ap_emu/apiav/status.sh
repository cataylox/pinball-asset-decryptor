#!/bin/bash
# status.sh - one key=value per line about this slot's rig, for the app.
# Never prose: callers parse it.
#   wsl=1 slot=
#   running=0|1                 the game and apiav both up
#   build=                      the prepared build it runs
#   av=1 connected=0|1          apiav up; the game has reached it
#   pid= rss_kb= uptime_s=      the game, while it runs
#   board=... hw=...            tools/proc_emu's status lines
. "$(dirname "$0")/avpath.sh"
echo "wsl=1"
echo "slot=$AV_SLOT"
if av_alive game && av_alive apiav; then echo "running=1"; else echo "running=0"; fi
echo "build=$(basename "$(cat "$AV_RIG/build" 2>/dev/null)")"
if av_alive apiav; then echo "av=1"; else echo "av=0"; fi
if grep -q 'Connected to A/V Controller' "$AV_RIG/game.out" 2>/dev/null; then echo "connected=1"; else echo "connected=0"; fi
if av_alive game; then
    P=$(av_pid game)
    echo "pid=$P"
    echo "rss_kb=$(awk '/^VmRSS/ {print $2}' "/proc/$P/status" 2>/dev/null)"
    echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
fi
PATH=$AV_ENV/bin:$PATH PAD_SLOT=$AV_SLOT bash "$AV_PROC/status.sh" | grep -E '^(board|hw)='
