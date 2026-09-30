#!/bin/bash
# bootcheck.sh <build> [out.png] - does it boot to attract and take switches?
# Starts the build on this slot, waits for attract, puts in a coin, takes a
# picture, stops it and prints one
#   VERDICT <build> pass|fail <why>
# line.  Run as root; PAD_SLOT picks the slot.
. "$(dirname "$0")/pbpath.sh"
B=${1:?usage: bootcheck.sh <build> [out.png]}
OUT=${2:-$PB_ROOT/bootcheck_$(basename "$B").png}
LOG=$PB_ROOT/bootcheck_$(basename "$B").log
if ! bash "$PB_TOOLS/run_game.sh" "$B" > "$LOG" 2>&1; then
    echo "VERDICT $B fail $(tail -1 "$LOG")"
    exit 1
fi
sleep "${PB_SETTLE:-10}"
if ! pb_game_alive; then
    echo "VERDICT $B fail died after boot: $(tail -1 "$PB_RIG/game/raven.log")"
    exit 1
fi
# A switch the game must see: a coin gives a credit.
python3 "$PB_TOOLS/sw.py" tap "COIN 2" > /dev/null
sleep 2
bash "$PB_TOOLS/shot.sh" "$OUT" > /dev/null
COIN=no; grep -q "SWA5 COIN 2" "$PB_RIG/game/raven.log" && COIN=yes
DIAG=$(grep -oE "Running diags\.\.\.[0-9]+ [0-9]+ errors" "$PB_RIG/game/raven.log" | tail -1 | sed 's/.* \([0-9]* errors\)/\1/')
BOARD=$(python3 "$PB_TOOLS/sw.py" state 2>/dev/null | python3 -c '
import json, sys
try:
    s = json.load(sys.stdin)
except ValueError:
    sys.exit()
st = s["status"]
if st["net_id"] and st["nodes"]:
    print("board: %d nodes, exp %s, %d drivers configured, %d LEDs lit" % (
        st["nodes"], "/".join(st["exp"]), s["drivers_configured"], s["leds_lit"]))')
VID=no; grep -q "video created" "$PB_RIG/vidprog.out" 2>/dev/null && VID=yes
bash "$PB_TOOLS/killgame.sh" > /dev/null
if [ -n "$BOARD" ] && [ $COIN = yes ] && [ $VID = yes ]; then
    echo "VERDICT $B pass attract mode, diags ${DIAG:-?}, coin seen, video playing, $BOARD, picture $OUT"
else
    echo "VERDICT $B fail coin=$COIN video=$VID ${BOARD:-board not used}, picture $OUT"
    exit 1
fi
