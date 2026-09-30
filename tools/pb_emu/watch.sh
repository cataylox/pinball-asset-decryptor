#!/bin/bash
# watch.sh <update.upd> - the one command the app runs (as root): set up the
# libraries once, unpack the update (with the updates it builds on), bring up
# the board and the game, wait for attract mode, then print status.sh.
#
# <update.upd> is the version to play: a delta (pbpp_predator_game_1_0_1.upd)
# brings the full update it builds on from the same folder (pbupdates.py).
#
# Env (all optional):
#   PAD_VISIBLE   1 = draw on the desktop (the app's default), 0 = hidden
#   PAD_AUDIO     1 = sound on (a rig is silent unless asked)
#   PAD_AUDIO_CTL the app's audio_ctl.json (WSL path): Volume / Mute, live
#
# Prints `== step ==` headers for the app's footer ladder:
#   == Setup == (only when the libraries are missing), == Unpack ==,
#   == Board ==, == Game ==, == Ready ==
# and `progress <pct>` lines while unpacking.
# Exit: 0 ready, 2 bad args / not root, 3 no disk space, 4 not a game this
# emulator runs, 5 unpack failed / no game in it, 6 the game did not reach
# attract mode, 7 the one-time setup failed.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/pbpath.sh"
UPD=${1:-}
[ "$(id -u)" = 0 ] || { echo "watch.sh: run as root" >&2; exit 2; }
[ -f "$UPD" ] || { echo "watch.sh: no such update file: $UPD" >&2; exit 2; }

# cancel.sh ends this run by its process tree; it finds it here.
mkdir -p "$PB_ROOT"
echo $$ > "$PB_ROOT/watch$PB_SLOT.pid"
trap 'rm -f "$PB_ROOT/watch$PB_SLOT.pid"' EXIT

if [ ! -f "$PB_ENV/.ready" ]; then
    echo "== Setup =="
    bash "$HERE/setup.sh" || exit 7
fi

echo "== Unpack =="
mapfile -t CHAIN < <(python3 "$HERE/pbupdates.py" "$UPD")
for f in "${CHAIN[@]}"; do echo "update: $(basename "$f")"; done
PREP=$PB_ROOT/prepare$PB_SLOT.out
bash "$HERE/prepare.sh" "${CHAIN[@]}" | tee "$PREP"
rc=${PIPESTATUS[0]}
[ "$rc" = 0 ] || exit "$rc"
BUILD=$(sed -n 's/^build=//p' "$PREP" | tail -1)
[ -n "$BUILD" ] || exit 5

echo "== Board =="
ARGS=()
[ "${PAD_VISIBLE:-1}" = 1 ] && ARGS+=(--visible)
[ "${PAD_AUDIO:-0}" = 1 ] && ARGS+=(--audio)
echo "== Game =="
bash "$HERE/run_game.sh" "$BUILD" "${ARGS[@]}" || exit 6
echo "== Ready =="
bash "$HERE/status.sh"
exit 0
