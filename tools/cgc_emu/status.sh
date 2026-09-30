#!/bin/bash
# status.sh - one key=value per line about this slot's rig (the same keys as
# the other rigs' status.sh, so an Emulate tab can read it):
#   wsl=1  running=0|1  title= title_name= build= pid= rss_kb= uptime_s=
#   slot= attract=0|1 balls=<trough>/<shooter>/<in play> frames=
#   summary=<one line for a person>
. "$(dirname "$0")/cgcpath.sh"
echo "wsl=1"
if ! cgc_game_alive; then
    echo "running=0"
    echo "summary=rig $CGC_SLOT: stopped"
    exit 0
fi
P=$(cgc_game_pid)
B=$(cat "$CGC_RIG/build" 2>/dev/null)
T=$(cat "$CGC_RIG/title" 2>/dev/null)
echo "running=1"
echo "title=$T"
echo "title_name=$(python3 "$CGC_TOOLS/cgctitles.py" get "$T" title)"
echo "build=$(basename "$B")"
echo "pid=$P"
echo "rss_kb=$(awk '/^VmRSS/ {print $2}' "/proc/$P/status" 2>/dev/null)"
echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
echo "slot=$CGC_SLOT"
A=0
grep -q '^lamps ' "$CGC_RIG/state" 2>/dev/null && ! grep -q '^lamps 0000000000000000$' "$CGC_RIG/state" && A=1
echo "attract=$A"
python3 "$CGC_TOOLS/sw.py" state 2>/dev/null | python3 -c '
import json, sys
try:
    s = json.load(sys.stdin)
except ValueError:
    sys.exit()
b = s["balls"]
print("balls=%d/%d/%d" % (b["trough"], 1 if b["shooter"] else 0, b["in_play"]))
print("frames=%d" % s["frames"])'
echo "summary=rig $CGC_SLOT: running $(basename "$B"), lamps $([ $A = 1 ] && echo lit || echo dark)"
