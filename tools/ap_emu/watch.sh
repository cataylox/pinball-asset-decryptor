#!/bin/bash
# watch.sh <game.pkg> - the one command the app runs (as root): set the rig's
# Python envs up the first time, unpack the .pkg (cached), start the game,
# wait until it has stayed up, write its switch table, then print status.sh.
#
# <game.pkg> is an American Pinball game-code package - the file the machine
# installs, or one the Write tab built.  It is only read.
#
# Env (all optional):
#   PAD_VISIBLE 1 = draw on the desktop, 0 = hidden. Unsaid: seen, except a
#               run for a ticket or a session (it has a label) - hidden (PAD-309)
#   PAD_AUDIO   1 = sound on (a rig is silent unless asked)
#   PAD_TITLE   the game's name, for the window titles and status.sh
#
# Prints `== step ==` headers for the app's footer ladder:
#   == Setup ==, == Prepare ==, == Game ==, == Ready ==
# (and `progress N` while unpacking).
# Exit: 0 ready, 2 bad args / not root, 3 no disk space, 4 not an American
# Pinball game-code .pkg, 6 the game did not start, 7 the first-time setup
# failed (it downloads the Python envs), 8 the game exited during start-up,
# 9 another slot runs an A/V title (Hot Wheels, Galactic Tank Force: one at
# a time), 10 Barry-O's BBQ Challenge (its own rig, apiav/ - not this one).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/appath.sh"
PKG=${1:-}
[ "$(id -u)" = 0 ] || { echo "watch.sh: run as root" >&2; exit 2; }
[ -f "$PKG" ] || { echo "watch.sh: no such file: $PKG" >&2; exit 2; }

# cancel.sh ends this run (and the setup or unpack under it) by its process
# tree.
mkdir -p "$AP_ROOT"
echo $$ > "$AP_ROOT/watch$AP_SLOT.pid"
trap 'rm -f "$AP_ROOT/watch$AP_SLOT.pid"' EXIT

echo "== Setup =="
if [ ! -f "$AP_PY/.ready" ]; then
    echo "note: first start - setting up the emulator's Python (a download of about 1 GB, a few minutes; once)"
    bash "$HERE/setup.sh" || exit 7
fi

echo "== Prepare =="
NAME=$(basename "$PKG"); NAME=${NAME%.*}; NAME=${NAME/-gamecode/}
# The unpacked game is about the size of the .pkg, and the decrypted zip sits
# beside it until it is unpacked: room for three.
need=$(( $(stat -c %s "$PKG") * 3 / 1024 ))
have=$(df -Pk "$AP_ROOT" | awk 'NR==2 {print $4}')
if [ ! -f "$AP_CACHE/$NAME/launcher" ] && [ "${have:-0}" -lt "$need" ]; then
    echo "watch.sh: not enough space in $AP_ROOT: $((have / 1024)) MB free, $((need / 1024)) MB needed" >&2
    exit 3
fi
mkdir -p "$AP_CACHE"
python3 "$HERE/prepare.py" "$PKG" --name "$NAME"
rc=$?
[ "$rc" = 0 ] || exit "$rc"
BUILD=$AP_CACHE/$NAME
echo "build=$BUILD"
if [ "$(cat "$BUILD/machine_dir" 2>/dev/null)" = bbq ]; then
    echo "watch.sh: Barry-O's BBQ Challenge runs on tools/ap_emu/apiav, not this rig" >&2
    exit 10
fi

echo "== Game =="
ARGS=()
# unsaid, a run for a ticket or a session is hidden (rigboard_visible, PAD-309)
[ "$(rigboard_visible)" = 1 ] && ARGS+=(--visible)
[ "${PAD_AUDIO:-0}" = 1 ] && ARGS+=(--audio)
bash "$HERE/run_game.sh" "$BUILD" "${ARGS[@]}"
rc=$?
[ "$rc" = 9 ] && exit 9
[ "$rc" = 0 ] || exit 6

# Its run loop is going; attract comes a few seconds later.  "Ready" once it
# has stayed up through that.
for _ in $(seq 1 8); do
    ap_game_alive || { echo "watch.sh: the game exited during start-up:" >&2; tail -15 "$AP_RIG/game.out" >&2; exit 8; }
    sleep 1
done
"$AP_PY3/bin/python3" "$HERE/apswitches.py" "$AP_RIG" "$BUILD" "${PAD_TITLE:-}" \
    || echo "note: no switch table for the switch window"
chown "$AP_USER": "$AP_RIG/switches.json" 2>/dev/null
echo "== Ready =="
bash "$HERE/status.sh"
