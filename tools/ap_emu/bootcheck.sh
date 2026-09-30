#!/bin/bash
# bootcheck.sh <build> [out.png] - does it boot to attract?  Starts the build
# on this slot, waits for attract, takes a picture, stops it and prints one
#   VERDICT <build> pass|fail <why>
# line.  Run as root, PAD_SLOT picks the slot.
. "$(dirname "$0")/appath.sh"
B=${1:?usage: bootcheck.sh <build> [out.png]}
OUT=${2:-$AP_ROOT/bootcheck_$(basename "$B").png}
if ! bash "$AP_TOOLS/run_game.sh" "$B" > "$AP_ROOT/bootcheck_$(basename "$B").log" 2>&1; then
    echo "VERDICT $B fail $(tail -1 "$AP_ROOT/bootcheck_$(basename "$B").log")"
    exit 1
fi
sleep "${AP_SETTLE:-10}"
# Attract = still running, and an Attract mode went on the game's mode queue
# (aprun.py logs each kind of mode added).
if ! ap_game_alive; then
    echo "VERDICT $B fail died after boot: $(grep -v YAMLLoad "$AP_RIG/game.out" | tail -1)"
    exit 1
fi
bash "$AP_TOOLS/shot.sh" "$OUT" > /dev/null
MODE=$(grep -m1 -oE ' mode\+ [A-Za-z_]*[Aa]ttract[A-Za-z_]*' "$AP_RIG/rig.log" | awk '{print $NF}')
bash "$AP_TOOLS/killgame.sh" > /dev/null
if [ -n "$MODE" ]; then
    echo "VERDICT $B pass attract mode $MODE, picture $OUT"
else
    echo "VERDICT $B fail running but no attract mode on the queue, picture $OUT"
    exit 1
fi
