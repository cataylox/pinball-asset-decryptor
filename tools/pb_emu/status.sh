#!/bin/bash
# status.sh - one key=value per line about this slot's rig, for the app (and
# for you).  Never prose: the app parses it (webui/rig.parse_status).  The
# same keys as tools/ap_emu's and tools/spooky_emu's, so the Emulate tabs
# read alike:
#   wsl=1                 always (the app's "WSL answered")
#   ready=0|1             the libraries setup.sh installs are in place
#   running=0|1
#   title=<pbtitles key> title_name= build= version= pid= rss_kb= uptime_s=
#   display= visible=0|1 window=WxH slot= attract=0|1          (while running)
#   switches=<count>  switches_json=<the virtual playfield's table>
#   balls=<trough>/<shooter>/<in play>  leds_lit=<count>       (the board's view)
#   summary=<one line for a person>
. "$(dirname "$0")/pbpath.sh"
echo "wsl=1"
[ -f "$PB_ENV/.ready" ] && echo "ready=1" || echo "ready=0"
if ! pb_game_alive; then
    echo "running=0"
    echo "summary=rig $PB_SLOT: stopped"
    exit 0
fi
P=$(pb_game_pid)
B=$(cat "$PB_RIG/build" 2>/dev/null)
T=$(cat "$PB_RIG/title" 2>/dev/null || echo predator)
echo "running=1"
echo "title=$T"
echo "title_name=$(python3 "$PB_TOOLS/pbtitles.py" get "$T" title)"
echo "build=$(basename "$B")"
echo "version=$(cat "$PB_RIG/version" 2>/dev/null)"
echo "pid=$P"
echo "rss_kb=$(awk '/^VmRSS/ {print $2}' "/proc/$P/status" 2>/dev/null)"
echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
echo "display=$(cat "$PB_RIG/display" 2>/dev/null)"
echo "visible=$(cat "$PB_RIG/visible" 2>/dev/null)"
echo "window=$(cat "$PB_RIG/window" 2>/dev/null)"
echo "slot=$PB_SLOT"
A=0
grep -qE "$(python3 "$PB_TOOLS/pbtitles.py" get "$T" attract)" "$PB_RIG/game/raven.log" 2>/dev/null && A=1
echo "attract=$A"
if [ -f "$PB_RIG/switches.json" ]; then
    echo "switches=$(grep -c '"n":' "$PB_RIG/switches.json")"
    echo "switches_json=$PB_RIG/switches.json"
fi
python3 "$PB_TOOLS/sw.py" state 2>/dev/null | python3 -c '
import json, sys
try:
    s = json.load(sys.stdin)
except ValueError:
    sys.exit()
b = s["balls"]
print("balls=%d/%d/%d" % (b["trough"], 1 if b["shooter"] else 0, b["in_play"]))
print("leds_lit=%d" % s["leds_lit"])
print("paused=%d" % (1 if s.get("paused") else 0))'
echo "summary=rig $PB_SLOT: running $(basename "$B") on $(cat "$PB_RIG/display" 2>/dev/null), attract $([ $A = 1 ] && echo yes || echo no)"
