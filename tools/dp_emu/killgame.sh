#!/bin/bash
# killgame.sh - stop this slot's game and hidden display, take down an AAIW
# run's root, and PROVE they stopped.  Exit 0 when nothing of the slot is
# left running, 1 otherwise.
. "$(dirname "$0")/dppath.sh"

stop_pid() {        # <pid>: TERM, wait up to 3 s, then KILL
    local p=$1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || return 0
    kill -TERM "$p" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL "$p" 2>/dev/null
}

# Every process of the game.  The Big Lebowski: the PyInstaller bootloader,
# the game it re-executes and its workers all run in the rig's game folder.
# Alice: everything whose root is the rig's chroot (pinterface ignores TERM,
# so stop_pid's KILL is what ends it).
slot_pids() {
    local p
    for p in $(pgrep -f '^\./start fakepinproc'); do
        case "$(readlink "/proc/$p/cwd" 2>/dev/null)" in
            "$DP_RIG"/game/*) echo "$p" ;;
        esac
    done
    if mountpoint -q "$DP_RIG/root" 2>/dev/null; then
        for p in $(ls /proc | grep -E '^[0-9]+$'); do
            [ "$(readlink "/proc/$p/root" 2>/dev/null)" = "$DP_RIG/root" ] && echo "$p"
        done
    fi
}

for p in $(slot_pids); do kill -TERM "$p" 2>/dev/null; done
for p in $(slot_pids); do stop_pid "$p"; done
stop_pid "$(cat "$DP_RIG/xvfb.pid" 2>/dev/null)"
# Alice's sound relay (run_aaiw.sh): its ffmpeg ends with the game's FIFO,
# but a relay still waiting for the game's first sound would not.
AP=$(cat "$DP_RIG/audio.pid" 2>/dev/null)
if [ -n "$AP" ]; then
    pkill -TERM -P "$AP" 2>/dev/null
    stop_pid "$AP"
    rm -f "$DP_RIG/audio.pid"
fi

# An AAIW root: every mount under it was made rslave when it was made
# (run_aaiw.sh), so this recursive unmount cannot reach PAD-Runtime's own.
if mountpoint -q "$DP_RIG/root" 2>/dev/null; then
    umount -R "$DP_RIG/root" 2>/dev/null || umount -R -l "$DP_RIG/root" 2>/dev/null
fi

left=$(slot_pids)
xp=$(cat "$DP_RIG/xvfb.pid" 2>/dev/null)
if [ -n "$xp" ] && kill -0 "$xp" 2>/dev/null; then left="$left xvfb:$xp"; fi
mountpoint -q "$DP_RIG/root" 2>/dev/null && left="$left root-mounted"
if [ -n "$left" ]; then
    echo "killgame.sh: still running:" $left >&2
    exit 1
fi
rm -f "$DP_RIG/game.pid" "$DP_RIG/xvfb.pid"
rigboard_clear dp "$DP_SLOT"
echo stopped
