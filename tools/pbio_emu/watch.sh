#!/bin/bash
# watch.sh <file> [<file>...] - the one command the app runs (as root):
# prepare the build (prepare.sh: a restore ISO and/or updates), bring up the
# board and the game, wait for attract mode, then print status.sh.
#
# ONE update is the version to play: the updates it builds on (or its
# title's restore ISO) come from the same folder (pbiofiles.py chain, as
# tools/pb_emu's pbupdates.py does for Predator).  Several files are stacked
# as given.
#
# Env: PAD_VISIBLE 1 = draw on the desktop, 0 = hidden (unsaid: as the other
# rigs - seen, except a labelled run, PAD-309); PAD_AUDIO is not supported
# yet (always muted).
# Prints `== Unpack ==`, `== Board ==`, `== Game ==`, `== Ready ==`.
# Exit: 0 ready, 2 bad args / not root, 3 no disk space, 4 not a title this
# rig knows, 5 no game in it / damaged, 6 the game did not reach attract.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/pbiopath.sh"
[ "$(id -u)" = 0 ] || { echo "watch.sh: run as root" >&2; exit 2; }
[ $# -ge 1 ] || { echo "usage: watch.sh <iso|upd> [<upd>...]" >&2; exit 2; }

mkdir -p "$PBIO_ROOT"
echo $$ > "$PBIO_ROOT/watch$PBIO_SLOT.pid"
trap 'rm -f "$PBIO_ROOT/watch$PBIO_SLOT.pid"' EXIT

echo "== Unpack =="
FILES=("$@")
if [ $# = 1 ]; then
    mapfile -t FILES < <(python3 "$HERE/pbiofiles.py" chain "$1")
    for f in "${FILES[@]}"; do echo "file: $(basename "$f")"; done
fi
PREP=$PBIO_ROOT/prepare$PBIO_SLOT.out
bash "$HERE/prepare.sh" "${FILES[@]}" | tee "$PREP"
rc=${PIPESTATUS[0]}
[ "$rc" = 0 ] || exit "$rc"
BUILD=$(sed -n 's/^build=//p' "$PREP" | tail -1)
[ -n "$BUILD" ] || exit 5

echo "== Board =="
ARGS=()
# unsaid, a run for a ticket or a session is hidden (rigboard_visible, PAD-309)
[ "$(rigboard_visible)" = 1 ] && ARGS+=(--visible)
[ "${PAD_AUDIO:-0}" = 1 ] && ARGS+=(--audio)
echo "== Game =="
bash "$HERE/run_game.sh" "$BUILD" "${ARGS[@]}" || exit 6
echo "== Ready =="
bash "$HERE/status.sh"
exit 0
