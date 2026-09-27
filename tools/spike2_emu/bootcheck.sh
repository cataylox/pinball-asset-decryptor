#!/bin/bash
# bootcheck.sh <key> <card> [deadline-seconds] - does this build boot to attract?
#
# One card, one verdict, in THIS rig slot (PAD_SLOT): start the run muted and
# without a playfield window, wait until status.sh says attract (autoattract
# clears Tech Alerts on the way), then stop the slot's run. The last line is
#
#   VERDICT <key> pass|fail <seconds> state=<state> fps=<n> [why]
#
# which rigbatch.sh collects. It is rigbatch's default job - "does every build
# still come up after my change" is the commonest library-wide question - and
# the template for a ticket's own job: take <key> <card>, use PAD_SLOT as given,
# print one VERDICT line, leave the slot clean.
#
# The deadline is the run's own: watch.sh is started with a minute cap a little
# past it and this script stops the slot when it gives up. Never `timeout` the
# game (it signals only the wrapper and the guest survives).
. "$(dirname "$0")/padpath.sh"
set -u
KEY=${1:?usage: bootcheck.sh <key> <card> [deadline-seconds]}
CARD=${2:?usage: bootcheck.sh <key> <card> [deadline-seconds]}
DEADLINE=${3:-${PAD_BOOT_DEADLINE:-420}}
LOG=$PAD_LOGDIR/bootcheck.$KEY.watch.out
mkdir -p "$PAD_LOGDIR"

# A card image is opened read-only in place: no multi-GB cache copy per build
# (a sweep of 36 would fill the disk), no audio, no playfield window.
export PAD_CARD=$CARD PAD_CARD_CACHE=${PAD_CARD_CACHE:-0} PAD_AUDIO=${PAD_AUDIO:-0}
export PAD_PLAYFIELD=${PAD_PLAYFIELD:-0}

stop() { bash "$RIG/killgame.sh" > /dev/null 2>&1 < /dev/null; }
field() { sed -n "s/^$1=//p" <<<"$2" | head -1; }

[ "$(bash "$RIG/alive.sh" --total 2>/dev/null < /dev/null)" = 0 ] || stop
t0=$(date +%s)
setsid bash "$RIG/watch.sh" $(( DEADLINE / 60 + 2 )) > "$LOG" 2>&1 < /dev/null &
WPID=$!
disown "$WPID"                    # its end is ours to cause; no "Killed" notice

verdict=fail why="deadline ${DEADLINE}s passed" st=booting fps=
while :; do
    sleep 3
    s=$(bash "$RIG/status.sh" 2>/dev/null < /dev/null)
    st=$(field state "$s"); fps=$(field fps "$s")
    case "$st" in
        attract|running) verdict=pass why=; break ;;
    esac
    if ! kill -0 "$WPID" 2>/dev/null; then
        # Only the rig's own report lines - the log also carries echoed
        # program text (watch.sh's event filter) that matches any keyword.
        why="the run ended by itself: $(grep -aE '^\[(watch|segv|run|card)\] ' "$LOG" \
            | grep -av '^\[watch\] cfg' \
            | grep -aiE 'watchdog|segv|refus|cannot|fail|died|never|stopped responding' \
            | grep -av 'segv\]   ' | tail -1 | cut -c1-200)"
        break
    fi
    [ $(( $(date +%s) - t0 )) -ge "$DEADLINE" ] && break
done
secs=$(( $(date +%s) - t0 ))
stop
kill "$WPID" 2>/dev/null
echo "VERDICT $KEY $verdict ${secs}s state=${st:-?} fps=${fps:-?}${why:+ $why}"
[ "$verdict" = pass ]
