#!/bin/bash
# cancel.sh - the app's Cancel while a Start is in flight: end this slot's
# watch.sh and everything it started (the first-time setup or the unpack
# included), drop a half-unpacked build, and stop whatever of the game had
# come up.  As root.  Last line is always `cancelled=1` (something was
# running) or `cancelled=0`.
#
# The process TREE, not the group (tools/bof_emu/cancel.sh says why).
. "$(dirname "$0")/appath.sh"
PIDF=$AP_ROOT/watch$AP_SLOT.pid
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
# A build is finished once prepare.py wrote its `launcher`; one without it
# was being unpacked, and is worth nothing (nor is its decrypted zip).
for b in "$AP_CACHE"/*/; do
    [ -d "$b" ] && [ ! -f "$b/launcher" ] && rm -rf "$b"
done
rm -f "$AP_CACHE"/*.zip
bash "$AP_TOOLS/killgame.sh" >/dev/null 2>&1
echo "cancelled=$did"
