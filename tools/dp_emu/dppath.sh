#!/bin/bash
# dppath.sh - sourced by every Dutch Pinball rig script.  Owns every path the
# rig uses; nothing else may hard-code one.
#
#   DP_SLOT     rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   DP_ROOT     /var/tmp/pad_dp              everything the rig writes
#   DP_CACHE    $DP_ROOT/cache/<build>       prepared builds (prepare.py):
#                                            assets/ + <version>/ + version
#   DP_RIG      $DP_ROOT/rig<slot>           this run: the game folder the
#                                            game runs in, logs, pids, FIFO
#   DP_USER     the account the game runs as (NEVER root: its operator menu
#               shells out to `date -s` and friends)
#   DP_DISPLAY  hidden Xvfb display for this slot (:120 + slot; BoF uses :90+)
DP_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DP_SLOT=${PAD_SLOT:-0}
DP_ROOT=${DP_ROOT:-/var/tmp/pad_dp}
DP_CACHE=$DP_ROOT/cache
DP_RIG=$DP_ROOT/rig$DP_SLOT
DP_DISPLAY=${DP_DISPLAY:-:$((120 + DP_SLOT))}
DP_SHIM=$DP_ROOT/dpinput.so

# The first ordinary account (uid 1000..59999): "pad" in PAD-Runtime.
if [ -z "${DP_USER:-}" ]; then
    DP_USER=$(getent passwd | awk -F: '$3>=1000 && $3<60000 {print $1; exit}')
fi

dp_game_pid() { cat "$DP_RIG/game.pid" 2>/dev/null; }

# Wait (up to 15 s) until an X display OPENS.  In PAD-Runtime
# /tmp/.X11-unix is WSLg's read-only mount, so a rig's Xvfb serves only on
# its abstract socket and waiting for the socket FILE never ends.  So ask
# libX11 itself: the display is up when XOpenDisplay succeeds.
# The Xvfb MUST run with -noreset: by default it regenerates whenever its
# last client disconnects, and a connection that arrives meanwhile is reset
# - this probe's own close, or the game's first open/close, then fails the
# game's real open ("Couldn't open X11 display" -> "video system not
# initialized", 3 starts in 5; PAD-263).
dp_wait_display() {
    python3 - "$1" <<'PY'
import ctypes, sys, time
x = ctypes.CDLL("libX11.so.6")
x.XOpenDisplay.restype = ctypes.c_void_p
x.XCloseDisplay.argtypes = [ctypes.c_void_p]
end = time.time() + 15
while time.time() < end:
    d = x.XOpenDisplay(sys.argv[1].encode())
    if d:
        x.XCloseDisplay(d)
        sys.exit(0)
    time.sleep(0.1)
sys.exit(1)
PY
}

# Empty the slot's folder for a new run - never while anything is mounted
# under it: an AAIW run binds /dev and /sys into its root, and a recursive
# delete through those would delete PAD-Runtime's own.  killgame.sh
# unmounts them; this refuses if it could not.
dp_clear_rig() {
    if findmnt -rn -o TARGET | grep -q "^$DP_RIG/"; then
        echo "the rig folder $DP_RIG still has mounts under it:" >&2
        findmnt -rn -o TARGET | grep "^$DP_RIG/" >&2
        return 1
    fi
    rm -rf --one-file-system "$DP_RIG"
}
dp_game_alive() {
    local p; p=$(dp_game_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
