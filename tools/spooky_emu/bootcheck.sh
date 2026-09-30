#!/bin/bash
# bootcheck.sh <build> [out.png] - does it boot to attract?  Starts the build
# on this slot, waits for attract, takes a picture, stops it and prints one
#   VERDICT <build> pass|fail <why>
# line.  Run as root, PAD_SLOT picks the slot.
. "$(dirname "$0")/spkpath.sh"
B=${1:?usage: bootcheck.sh <build> [out.png]}
OUT=${2:-$SPK_ROOT/bootcheck_$(basename "$B").png}
LOG=$SPK_ROOT/bootcheck_$(basename "$B").log
if ! bash "$SPK_TOOLS/run_game.sh" "$B" > "$LOG" 2>&1; then
    echo "VERDICT $B fail $(tail -1 "$LOG")"
    exit 1
fi
sleep "${SPK_SETTLE:-10}"
if ! spk_game_alive; then
    echo "VERDICT $B fail died after boot: $(grep -v '^\s*$' "$SPK_RIG/player.log" | tail -1)"
    exit 1
fi
bash "$SPK_TOOLS/shot.sh" "$OUT" > /dev/null
# Attract = the game said so, and it talked to the rig's board: asked it
# for switch states and configured its coils.
HW=$(python3 "$SPK_TOOLS/spkctl.py" --slot "$SPK_SLOT" state 2>/dev/null)
BOARD=$(printf '%s' "$HW" | python3 -c '
import json, sys
try:
    s = json.load(sys.stdin)
except ValueError:
    sys.exit()
if s["connected"]:
    print("board: %d coils configured, %d fired, %d LEDs lit" % (
        s["coils"]["configured"], sum(s["coils"]["fired"].values()),
        s["leds_lit"]))')
bash "$SPK_TOOLS/killgame.sh" > /dev/null
if spk_attract && [ -n "$BOARD" ]; then
    echo "VERDICT $B pass attract mode, $BOARD, picture $OUT"
else
    echo "VERDICT $B fail no attract (${BOARD:-board not used}), picture $OUT"
    exit 1
fi
