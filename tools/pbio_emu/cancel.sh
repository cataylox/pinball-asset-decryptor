#!/bin/bash
# cancel.sh - the app's Cancel while a Start is in flight: end this slot's
# watch.sh and everything it started (prepare.sh, tar, partclone,
# run_game.sh), drop half-made cache entries, and stop whatever of the game
# had come up.  As root.  Last line: `cancelled=1` or `cancelled=0`.
. "$(dirname "$0")/pbiopath.sh"
PIDF=$PBIO_ROOT/watch$PBIO_SLOT.pid
WP=$(cat "$PIDF" 2>/dev/null)

tree() {    # <pid>: the pid and all its descendants, parents first
    local p=$1 c
    echo "$p"
    for c in $(ps -o pid= --ppid "$p"); do tree "$c"; done
}

did=0
if [ -n "$WP" ] && kill -0 "$WP" 2>/dev/null; then
    PIDS=$(tree "$WP")
    kill -STOP $PIDS 2>/dev/null
    kill -TERM $PIDS 2>/dev/null
    kill -CONT $PIDS 2>/dev/null
    for _ in $(seq 1 30); do
        alive=0
        for p in $PIDS; do kill -0 "$p" 2>/dev/null && alive=1; done
        [ $alive = 0 ] && break
        sleep 0.1
    done
    kill -KILL $PIDS 2>/dev/null
    did=1
fi
rm -f "$PIDF"
for m in "${PBIO_ROOT:?}"/isomnt.*; do [ -d "$m" ] && { umount "$m" 2>/dev/null; rmdir "$m"; }; done
rm -rf "${PBIO_CACHE:?}"/*/tree.partial "${PBIO_CACHE:?}"/*/root.img.partial
bash "$PBIO_TOOLS/killgame.sh" >/dev/null 2>&1
echo "cancelled=$did"
