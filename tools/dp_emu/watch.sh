#!/bin/bash
# watch.sh <disk.img> [update.zip ...] - the one command the app runs (as
# root): prepare the build (cached), start the game, wait for its window,
# then print status.sh.
#
# <disk.img> is a Dutch Pinball machine's disk image: the only place the
# base assets and the installed version folder exist (prepare.py says why).
# Update zips - the factory's, or one the Write tab built - are laid over
# its installed version in version order, as the machine's updater does.
#
# Env (all optional):
#   PAD_VISIBLE 1 = draw on the desktop (the app's default), 0 = hidden
#   PAD_AUDIO   1 = sound on (a rig is silent unless asked)
#
# Prints `== step ==` headers for the app's footer ladder:
#   == Prepare ==, == Game ==, == Ready ==   (and `progress N` while copying)
# Exit: 0 ready, 2 bad args / not root, 3 no disk space, 4 no Dutch Pinball
# game on the image, 5 an update that does not install onto it, 6 the game
# did not start, 8 the game exited during start-up.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/dppath.sh"
IMG=${1:-}; shift 2>/dev/null || true
[ "$(id -u)" = 0 ] || { echo "watch.sh: run as root" >&2; exit 2; }
[ -f "$IMG" ] || { echo "watch.sh: no such disk image: $IMG" >&2; exit 2; }
for z in "$@"; do [ -f "$z" ] || { echo "watch.sh: no such update: $z" >&2; exit 2; }; done

# cancel.sh ends this run (and the copy under it) by its process tree.
mkdir -p "$DP_ROOT"
echo $$ > "$DP_ROOT/watch$DP_SLOT.pid"
trap 'rm -f "$DP_ROOT/watch$DP_SLOT.pid"' EXIT

echo "== Prepare =="
NAME=$(basename "$IMG"); NAME=${NAME%.*}
# progress lines pass straight through to the app (its footer shows them)
python3 "$HERE/prepare.py" image "$IMG" --name "$NAME" --keep 2 | tee "$DP_ROOT/prepare$DP_SLOT.out"
rc=${PIPESTATUS[0]}
[ "$rc" = 0 ] || exit "$rc"
BUILD=$DP_CACHE/$NAME
if [ $# -gt 0 ] && [ "$(cat "$BUILD/kind" 2>/dev/null)" = aaiw ]; then
    echo "watch.sh: Alice's Adventures in Wonderland installs its updates from a USB stick; play the disk image as it is" >&2
    exit 5
fi
if [ $# -gt 0 ]; then
    ZNAME=$NAME
    for z in "$@"; do b=$(basename "$z"); ZNAME="$ZNAME+${b%.*}"; done
    python3 "$HERE/prepare.py" zip "$@" --base "$BUILD" --name "$ZNAME" || exit $?
    BUILD=$DP_CACHE/$ZNAME
fi
echo "build=$BUILD"

echo "== Game =="
ARGS=()
[ "${PAD_VISIBLE:-1}" = 1 ] && ARGS+=(--visible)
[ "${PAD_AUDIO:-0}" = 1 ] && ARGS+=(--audio)
bash "$HERE/run_game.sh" "$BUILD" "${ARGS[@]}" || exit 6

# The window is up; the game then loads every asset (a few seconds) before
# attract.  It is "ready" once it has stayed up through that.
for _ in $(seq 1 20); do
    dp_game_alive || { echo "watch.sh: the game exited during start-up:" >&2; tail -15 "$DP_RIG/game.out" >&2; exit 8; }
    sleep 1
done
echo "== Ready =="
bash "$HERE/status.sh"
