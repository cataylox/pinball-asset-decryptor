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
# Attract = the game said so, and the board it talked to is the rig's.
BOARD=$(grep -m1 -o 'CONTROLLER: .*' "$SPK_RIG/player.log")
bash "$SPK_TOOLS/killgame.sh" > /dev/null
if grep -q 'Attract_mode started' "$SPK_RIG/player.log" && [ -n "$BOARD" ]; then
    echo "VERDICT $B pass attract mode, $BOARD, picture $OUT"
else
    echo "VERDICT $B fail no attract (board: ${BOARD:-none}), picture $OUT"
    exit 1
fi
