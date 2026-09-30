#!/bin/bash
# status.sh - one key=value per line about this slot's rig.  Never prose:
# callers parse it.
#   wsl=1 slot=
#   running=0|1                 the game is up (and, for Alice Cooper, its
#                               Unity player)
#   build= title=               the prepared build it runs (rm | ac)
#   attract=0|1                 it has reached attract
#   pid= rss_kb= uptime_s=      the game, while it runs
#   board=... hw=...            tools/proc_emu's status lines
. "$(dirname "$0")/sppath.sh"
echo "wsl=1"
echo "slot=$SPP_SLOT"
T=$(cat "$SPP_RIG/title" 2>/dev/null)
if spp_alive game && { [ "$T" != ac ] || spp_alive unity; }; then echo "running=1"; else echo "running=0"; fi
echo "build=$(basename "$(cat "$SPP_RIG/build" 2>/dev/null)")"
echo "title=$T"
if [ -f "$SPP_RIG/attract" ]; then echo "attract=1"; else echo "attract=0"; fi
if spp_alive game; then
    P=$(spp_pid game)
    echo "pid=$P"
    echo "rss_kb=$(awk '/^VmRSS/ {print $2}' "/proc/$P/status" 2>/dev/null)"
    echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
fi
PATH=$SPP_PY3/bin:$PATH PAD_SLOT=$SPP_SLOT bash "$SPP_PROC/status.sh" | grep -E '^(board|hw)='
