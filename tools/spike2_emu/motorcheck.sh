#!/bin/bash
# motorcheck.sh <key> <card> - boot, start a game, count a board motor's moves.
#
# The rigbatch job PAD-237 was proven with (bootcheck.sh is the template it
# follows): boot to attract in THIS rig slot (PAD_SLOT), latch the switches
# MOTOR_HOLD names ("77:1 84:0" - id:level), start a game with plunge.py, and
# count what node MOTOR_NODE (default 9) was sent for MOTOR_SAMPLE seconds
# (default 40) after Start. The last line is
#
#   VERDICT <key> pass c53=<n> c54=<n> c40=<n> [env...]
#
# c53/c54 are the motor's move commands - the count that was 35/31 while
# nothing answered john_wick_le's car and every send was a tyre screech, and
# is 0 now. c40 is coil fires on the same node, which on john_wick_le is the
# drop target cycling (see docs/plans/node_board_motor.md). It always passes
# when the run starts; the counts are the result. Knobs the sweeps varied
# (PAD_NB_CREPLY, PAD_NB_CFILL, PAD_NB_MOTOR, PAD_MOTOR_MS) are passed in the
# list's ENV and echoed on the verdict line so a results.tsv reads alone.
#
#   rigbatch.sh --who PAD-n <list> -- bash $RIG/motorcheck.sh
#
# A still of the game FBO at the end of the sample goes to
# $PAD_LOGDIR/motorcheck.<key>.png.
. "$(dirname "$0")/padpath.sh"
set -u
KEY=${1:?usage: motorcheck.sh <key> <card>}
CARD=${2:?usage: motorcheck.sh <key> <card>}
SAMPLE=${MOTOR_SAMPLE:-40}
NODE=${MOTOR_NODE:-9}
export PAD_CARD=$CARD PAD_CARD_CACHE=${PAD_CARD_CACHE:-0} PAD_AUDIO=${PAD_AUDIO:-0}
export PAD_PLAYFIELD=${PAD_PLAYFIELD:-0} PAD_HIDDEN=${PAD_HIDDEN:-1} PAD_NB_TRACE=1
OUT=$PAD_LOGDIR/motorcheck.$KEY.watch.out
GZ=$PAD_LOGDIR/gzwatch.log
mkdir -p "$PAD_LOGDIR"

stop() { bash "$RIG/killgame.sh" > /dev/null 2>&1 < /dev/null; }
field() { sed -n "s/^$1=//p" <<<"$2" | head -1; }

[ "$(bash "$RIG/alive.sh" --total 2>/dev/null < /dev/null)" = 0 ] || stop
t0=$(date +%s)
setsid bash "$RIG/watch.sh" 12 > "$OUT" 2>&1 < /dev/null &
WPID=$!
disown "$WPID"

while :; do
    sleep 3
    st=$(field state "$(bash "$RIG/status.sh" 2>/dev/null < /dev/null)")
    case "$st" in attract|running) break ;; esac
    if ! kill -0 "$WPID" 2>/dev/null; then
        echo "VERDICT $KEY fail the run ended before attract"
        exit 1
    fi
    if [ $(( $(date +%s) - t0 )) -ge 400 ]; then
        stop
        echo "VERDICT $KEY fail no attract in 400 s"
        exit 1
    fi
done
sleep 8                               # let attract settle before touching it
for kv in ${MOTOR_HOLD:-}; do
    python3 "$RIG/swhold.py" "${kv%%:*}" "${kv##*:}" > /dev/null
done
L0=$(wc -l < "$GZ")
python3 "$RIG/plunge.py" game > /dev/null 2>&1
sleep "$SAMPLE"
S=$(tail -n +"$L0" "$GZ" | grep -a "^\[nbts\].*node=$NODE ")
c53=$(grep -c 'cmd=53 ' <<<"$S")
c54=$(grep -c 'cmd=54 ' <<<"$S")
c40=$(grep -c 'cmd=40 ' <<<"$S")
bash "$RIG/glshot.sh" "$PAD_LOGDIR/motorcheck.$KEY.png" > /dev/null 2>&1
stop
kill "$WPID" 2>/dev/null
env=""
for v in MOTOR_HOLD PAD_NB_CREPLY PAD_NB_CFILL PAD_NB_MOTOR PAD_MOTOR_MS; do
    [ -n "${!v:-}" ] && env="$env $v=${!v}"
done
echo "VERDICT $KEY pass c53=$c53 c54=$c54 c40=$c40$env"
