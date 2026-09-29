#!/bin/bash
# watch.sh <game.fun> - the one command the app runs (as root): decrypt the
# build, bring up the boards and the game, wait for the game to find its
# hardware, then print status.sh.
#
# Env (all optional):
#   BOF_TITLE   profile name (dune, winchester, labyrinth); worked out from the
#               file name, else by trying each title's passphrase
#   BOF_KEYS    "title:passphrase,..." - the app passes its own table
#               (plugins/bof/games.py); the rig never hard-codes one
#   PAD_VISIBLE 1 = draw on the desktop (the app's default), 0 = hidden
#   PAD_AUDIO   1 = sound on (a rig is silent unless asked)
#
# Prints `== step ==` headers for the app's footer ladder:
#   == Decrypt ==, == Boards ==, == Game ==, == Ready ==
# Exit: 0 ready, 2 bad args / not root, 3 no disk space, 4 unknown title or
# decrypt failed, 5 no game binary, 6 game did not start, 8 game did not stay
# up, 9 game up but never found its boards.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/bofpath.sh"
FUN=${1:-}
[ "$(id -u)" = 0 ] || { echo "watch.sh: run as root" >&2; exit 2; }
[ -f "$FUN" ] || { echo "watch.sh: no such .fun file: $FUN" >&2; exit 2; }

key_for() {     # <title> -> passphrase from BOF_KEYS
    echo "${BOF_KEYS:-}" | tr ',' '\n' | awk -F: -v t="$1" '$1==t {print $2; exit}'
}

echo "== Decrypt =="
TITLE=${BOF_TITLE:-}
if [ -z "$TITLE" ]; then
    case "$(basename "$FUN" | tr 'A-Z' 'a-z')" in
        dune*) TITLE=dune ;;
        winchester*) TITLE=winchester ;;
        lab*) TITLE=labyrinth ;;
    esac
fi
if [ -z "$TITLE" ] || [ -z "$(key_for "$TITLE")" ]; then
    # A renamed build (a mod saved as anything.fun): the title whose
    # passphrase opens it is the title it is.
    TITLE=""
    for pair in $(echo "${BOF_KEYS:-}" | tr ',' ' '); do
        t=${pair%%:*}; p=${pair#*:}
        if gpg --batch --quiet --pinentry-mode loopback --passphrase-fd 3 \
               --decrypt "$FUN" 3<<<"$p" 2>/dev/null | head -c 16 | grep -q .; then
            TITLE=$t; break
        fi
    done
fi
PROFILE=$HERE/profiles/$TITLE.json
if [ -z "$TITLE" ] || [ ! -f "$PROFILE" ]; then
    echo "watch.sh: $(basename "$FUN") is not a build of a title this emulator knows" >&2
    exit 4
fi
echo "title=$TITLE"
mkdir -p "$BOF_ROOT"
PREP=$BOF_ROOT/prepare$BOF_SLOT.out
BOF_PASS=$(key_for "$TITLE") bash "$HERE/prepare.sh" "$FUN" | tee "$PREP"
rc=${PIPESTATUS[0]}
[ "$rc" = 0 ] || exit "$rc"
BIN=$(sed -n 's/^binary=//p' "$PREP" | tail -1)
[ -n "$BIN" ] || exit 5

echo "== Boards =="
ARGS=(--detach)
[ "${PAD_VISIBLE:-1}" = 1 ] && ARGS+=(--visible)
[ "${PAD_AUDIO:-0}" = 1 ] && ARGS+=(--audio)
echo "== Game =="
bash "$HERE/run_game.sh" "$BIN" "$PROFILE" "${ARGS[@]}" || exit 6

# The game finds its boards within ~15 s of starting (Labyrinth's 4 GB
# binary takes longest); the rig is "ready" once it has asked for the switch
# states, which it does only after every board answered.
for i in $(seq 1 120); do
    bof_game_alive || { echo "watch.sh: the game exited during start-up:" >&2; tail -15 "$BOF_RIG/game.log" >&2; exit 8; }
    if python3 "$HERE/bofctl.py" --slot "$BOF_SLOT" state 2>/dev/null | grep -q '"hardware_connected": true'; then
        echo "== Ready =="
        bash "$HERE/status.sh"
        exit 0
    fi
    sleep 1
done
echo "watch.sh: the game is running but never finished finding its boards" >&2
bash "$HERE/status.sh"
exit 9
