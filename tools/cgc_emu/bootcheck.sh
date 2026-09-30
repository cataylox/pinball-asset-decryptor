#!/bin/bash
# bootcheck.sh <build> [out.png] - does it boot to attract and take switches?
# Starts the build on this slot, waits for attract, puts in coins (the game
# books them: its FRAM changes), presses Start (the game serves a ball: the
# TROUGH EJECT coil fires and the ball model sees it reach the shooter
# lane), takes a picture, stops it and prints one
#   VERDICT <build> pass|fail <why>
# line.  Run as root; PAD_SLOT picks the slot.
. "$(dirname "$0")/cgcpath.sh"
B=${1:?usage: bootcheck.sh <build> [out.png]}
case "$B" in /*) ;; *) B=$CGC_CACHE/$B ;; esac
OUT=${2:-$CGC_ROOT/bootcheck_$(basename "$B").png}
LOG=$CGC_ROOT/bootcheck_$(basename "$B").log
if ! bash "$CGC_TOOLS/run_game.sh" "$B" > "$LOG" 2>&1; then
    echo "VERDICT $B fail $(tail -1 "$LOG")"
    exit 1
fi
sleep "${CGC_SETTLE:-5}"
NVF=$CGC_ROOT/nv$CGC_SLOT/$(cat "$B/.pad_title")/fram.bin
before=$(md5sum < "$NVF")
python3 "$CGC_TOOLS/sw.py" coin 4
sleep 2
COIN=no; [ "$(md5sum < "$NVF")" != "$before" ] && COIN=yes
EJECT=$(python3 -c 'import sys; print(dict(kv.split("=") for kv in open(sys.argv[1]).read().strip().split(";")).get("eject", ""))' "$CGC_RIG/balls")
: > "$CGC_RIG/events"
python3 "$CGC_TOOLS/sw.py" tap "START BUTTON"
SERVE=no
for _ in $(seq 1 20); do
    sleep 0.5
    grep -q "sol $EJECT\$" "$CGC_RIG/events" && python3 "$CGC_TOOLS/sw.py" state |
        grep -q '"shooter": true' && { SERVE=yes; break; }
done
bash "$CGC_TOOLS/shot.sh" "$OUT" --scale 2 > /dev/null
ALIVE=yes; cgc_game_alive || ALIVE=no
bash "$CGC_TOOLS/killgame.sh" > /dev/null
if [ $ALIVE = yes ] && [ $COIN = yes ] && [ $SERVE = yes ]; then
    echo "VERDICT $B pass attract mode, coins booked, Start served a ball (coil $EJECT), picture $OUT"
else
    echo "VERDICT $B fail alive=$ALIVE coins_booked=$COIN served=$SERVE, picture $OUT"
    exit 1
fi
