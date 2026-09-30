#!/bin/bash
# status.sh - one line about this slot's rig: running or not, which build,
# attract reached, the board's view (balls, LEDs).
. "$(dirname "$0")/pbpath.sh"
if ! pb_game_alive; then echo "rig $PB_SLOT: stopped"; exit 1; fi
b=$(basename "$(cat "$PB_RIG/build" 2>/dev/null)")
a=no; grep -qE "$(python3 "$PB_TOOLS/pbtitles.py" get "$(cat "$PB_RIG/title")" attract)" "$PB_RIG/game/raven.log" 2>/dev/null && a=yes
st=$(python3 "$PB_TOOLS/sw.py" state 2>/dev/null | python3 -c '
import json, sys
try:
    s = json.load(sys.stdin)
except ValueError:
    sys.exit()
b = s["balls"]
print("trough %d, in play %d, shooter %s, %d LEDs lit" % (
    b["trough"], b["in_play"], "yes" if b["shooter"] else "no", s["leds_lit"]))')
echo "rig $PB_SLOT: running $b on $(cat "$PB_RIG/display"), attract $a, ${st:-board not answering}"
