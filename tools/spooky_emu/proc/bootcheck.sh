#!/bin/bash
# bootcheck.sh <build> [out.png] - does it boot to attract?  Starts the build
# on this slot, waits for attract, takes a picture, stops it and prints one
#   VERDICT <build> pass|fail <why>
# line.  Run as root, PAD_SLOT picks the slot.
. "$(dirname "$0")/sppath.sh"
B=${1:?usage: bootcheck.sh <build> [out.png]}
N=$(basename "$B")
OUT=${2:-$SPP_ROOT/bootcheck_$N.png}
if ! bash "$SPP_TOOLS/run_game.sh" "$B" > "$SPP_ROOT/bootcheck_$N.log" 2>&1; then
    echo "VERDICT $B fail $(tail -1 "$SPP_ROOT/bootcheck_$N.log")"
    bash "$SPP_TOOLS/killgame.sh" > /dev/null
    exit 1
fi
sleep "${SPP_SETTLE:-15}"
# Attract = still running, and an Attract mode went on the game's mode queue
# (spprun.py logs it).
if ! spp_alive game; then
    echo "VERDICT $B fail died after boot: $(tail -1 "$SPP_RIG/game.out")"
    bash "$SPP_TOOLS/killgame.sh" > /dev/null
    exit 1
fi
bash "$SPP_TOOLS/shot.sh" "$OUT" > /dev/null
MODE=$(grep -m1 -oE ' attract: [A-Za-z_]+' "$SPP_RIG/rig.log" | awk '{print $NF}')
bash "$SPP_TOOLS/killgame.sh" > /dev/null
if [ -n "$MODE" ]; then
    echo "VERDICT $B pass attract mode $MODE, picture $OUT"
else
    echo "VERDICT $B fail running but no attract mode on the queue, picture $OUT"
    exit 1
fi
