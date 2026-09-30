#!/bin/bash
# bootcheck.sh <build> [out.png] - does it boot to attract and take switches?
# Starts the build on this slot, waits for attract, puts in coins and
# presses Start, checks the game took them (credits, then a game with its
# first ball served into the shooter lane), takes a picture, stops it and
# prints one
#   VERDICT <build> pass|fail <why>
# line.  Run as root; PAD_SLOT picks the slot.
. "$(dirname "$0")/cgcpfpath.sh"
B=${1:?usage: bootcheck.sh <build> [out.png]}
OUT=${2:-$CGCPF_ROOT/bootcheck_$(basename "$B").png}
LOG=$CGCPF_ROOT/bootcheck_$(basename "$B").log
mkdir -p "$CGCPF_ROOT"
SW="python3 $CGCPF_TOOLS/sw.py"
if ! bash "$CGCPF_TOOLS/run_game.sh" "$B" > "$LOG" 2>&1; then
    bash "$CGCPF_TOOLS/killgame.sh" > /dev/null
    echo "VERDICT $B fail $(grep -m1 . "$LOG")"
    exit 1
fi
sleep "${CGCPF_SETTLE:-5}"
c0=$(cgcpf_peek $CGCPF_CREDITS_ADDR)
# A coin mech closes its switch for tens of ms; one held much longer is
# refused as a jam.
for _ in 1 2 3 4; do $SW tap "coin left" 50; sleep 0.6; done
sleep 1
c1=$(cgcpf_peek $CGCPF_CREDITS_ADDR)
$SW tap start 120
for _ in $(seq 1 30); do
    grep -q "ball in the shooter lane" "$CGCPF_RIG/ball.log" 2>/dev/null && break
    sleep 1
done
sleep 1
st=$(cgcpf_peek $CGCPF_STATE_ADDR)
LANE=no; grep -q "ball in the shooter lane" "$CGCPF_RIG/ball.log" && LANE=yes
SHOOTER=no; grep -q "game_ball_shooter: ball in shooter" "$(cgcpf_log)" && SHOOTER=yes
bash "$CGCPF_TOOLS/shot.sh" "$OUT" > /dev/null
bash "$CGCPF_TOOLS/killgame.sh" > /dev/null
if [ "${c1:-0}" -gt "${c0:-0}" ] && [ "$st" = 2 ] && [ $LANE = yes ] && [ $SHOOTER = yes ]; then
    echo "VERDICT $B pass attract, coins -> credits $c0->$c1, Start -> game (state 2), ball served to the shooter lane and seen by the game, picture $OUT"
else
    echo "VERDICT $B fail credits $c0->$c1 state=$st lane=$LANE game_saw_shooter=$SHOOTER, picture $OUT"
    exit 1
fi
