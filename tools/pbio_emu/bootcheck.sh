#!/bin/bash
# bootcheck.sh <build> [out.png] - does it boot to attract?  Starts the build
# hidden on this slot, waits for attract, takes a picture, stops it and
# prints one `VERDICT <build> pass|fail <why>` line.  As root; PAD_SLOT
# picks the slot (rigbatch.sh's job contract).
. "$(dirname "$0")/pbiopath.sh"
B=${1:?usage: bootcheck.sh <build> [out.png]}
OUT=${2:-$PBIO_ROOT/bootcheck_$(basename "$B").png}
LOG=$PBIO_ROOT/bootcheck_$(basename "$B").log
if ! bash "$PBIO_TOOLS/run_game.sh" "$B" > "$LOG" 2>&1; then
    echo "VERDICT $B fail $(tail -1 "$LOG")"
    exit 1
fi
sleep "${PBIO_SETTLE:-10}"
if ! pbio_game_alive; then
    echo "VERDICT $B fail died after boot: $(tail -1 "$PBIO_RIG/pinprog.log")"
    exit 1
fi
bash "$PBIO_TOOLS/shot.sh" "$OUT" > /dev/null
BOARD=$(python3 "$PBIO_TOOLS/pbioctl.py" --slot "$PBIO_SLOT" state 2>/dev/null | python3 -c '
import json, sys
try:
    s = json.load(sys.stdin)
except ValueError:
    sys.exit()
if s["connected"]:
    print("board: %d frames, %d coils configured, %d LEDs lit" % (
        s["frames"], s["coils"]["configured"], s["leds_lit"]))')
VID=$(grep -c "hp_video_init: accepted connection" "$PBIO_RIG/pinprog.log")
bash "$PBIO_TOOLS/killgame.sh" > /dev/null
if pbio_attract && [ -n "$BOARD" ] && [ "$VID" -gt 0 ]; then
    echo "VERDICT $B pass attract mode, $BOARD, display connected, picture $OUT"
else
    echo "VERDICT $B fail no attract (${BOARD:-board not used}, display connections $VID), picture $OUT"
    exit 1
fi
