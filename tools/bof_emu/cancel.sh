#!/bin/bash
# cancel.sh - the app's Cancel while a Start is in flight: end this slot's
# watch.sh and EVERYTHING it started (prepare.sh, gpg, tar), drop the
# half-unpacked build, and stop whatever of the game had come up.  As root.
# Last line is always `cancelled=1` (something was running) or `cancelled=0`.
#
# THE TREE, NOT THE PROCESS GROUP.  Launched by the app, watch.sh leads its
# own group - but started with `&` from a script it shares its caller's, and
# killing "its group" then killed the caller too (this script included, the
# first time it was tried, before it had cleaned up).
. "$(dirname "$0")/bofpath.sh"
PIDF=$BOF_ROOT/watch$BOF_SLOT.pid
WP=$(cat "$PIDF" 2>/dev/null)

tree() {    # <pid>: the pid and all its descendants, parents first
    local p=$1 c
    echo "$p"
    for c in $(ps -o pid= --ppid "$p"); do tree "$c"; done
}

did=0
if [ -n "$WP" ] && kill -0 "$WP" 2>/dev/null; then
    # Stop the parents first so nothing starts a new child mid-kill.
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
# A build still being unpacked is worth nothing; a finished one stays cached.
live=$(cat "$BOF_ROOT"/rig*/binary 2>/dev/null)
for d in "$BOF_CACHE"/*.partial; do
    [ -e "$d" ] || continue
    case "$live" in *"${d%.partial}"*) continue ;; esac
    rm -rf "$d"
done
bash "$BOF_TOOLS/killgame.sh" >/dev/null 2>&1
echo "cancelled=$did"
