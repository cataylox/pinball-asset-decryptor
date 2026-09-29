#!/bin/bash
# killgame.sh - stop this slot's game and hidden display, and PROVE they
# stopped.  Exit 0 when nothing of the slot is left running, 1 otherwise.
. "$(dirname "$0")/dppath.sh"

stop_pid() {        # <pid>: TERM, wait up to 3 s, then KILL
    local p=$1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || return 0
    kill -TERM "$p" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL "$p" 2>/dev/null
}

# Every process of the game: the PyInstaller bootloader, the game it
# re-executes, and the workers it forks all run in the rig's game folder.
slot_pids() {
    local p
    for p in $(pgrep -f '^\./start fakepinproc'); do
        case "$(readlink "/proc/$p/cwd" 2>/dev/null)" in
            "$DP_RIG"/game/*) echo "$p" ;;
        esac
    done
}

for p in $(slot_pids); do kill -TERM "$p" 2>/dev/null; done
for p in $(slot_pids); do stop_pid "$p"; done
stop_pid "$(cat "$DP_RIG/xvfb.pid" 2>/dev/null)"

left=$(slot_pids)
xp=$(cat "$DP_RIG/xvfb.pid" 2>/dev/null)
if [ -n "$xp" ] && kill -0 "$xp" 2>/dev/null; then left="$left xvfb:$xp"; fi
if [ -n "$left" ]; then
    echo "killgame.sh: still running:" $left >&2
    exit 1
fi
rm -f "$DP_RIG/game.pid" "$DP_RIG/xvfb.pid"
echo stopped
