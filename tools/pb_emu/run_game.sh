#!/bin/bash
# run_game.sh [<build>] [--visible] [--audio]
#
# Start Pinball Brothers' Predator on this PC, on the rig's emulated FAST
# boards (pbfast.py).  <build> is a folder prepare.sh made (a name under
# $PB_CACHE or a path; default: the newest there).  Run as root; the game
# runs as $PB_USER.  Returns once the game reached attract mode (or died).
#
#   --visible    draw on the WSLg desktop instead of the slot's hidden Xvfb
#                (the default: windows popping up are disruptive; shot.sh
#                shows a hidden run)
#   --audio      play sound through WSLg's PulseAudio (default: none - a
#                hidden rig nobody can find must never be heard); with
#                PAD_AUDIO_CTL (the app's audio_ctl.json, a WSL path) pbvol.py
#                holds it at the app's Volume / Mute, live
#
# The machine is two programs in /opt/game, both started by the machine's
# init: pinprog (rules + the FAST boards, writes raven.log and nvram/ in its
# cwd) and vidprog (the screen: pinprog's TCP 5555 client).  The game sees
# /opt/game in a private mount namespace: $PB_RIG/game, the build hard-linked
# (pinprog writes its log beside itself), with nvram/ -> this slot's kept
# settings, audits and high scores ($PB_ROOT/nv<slot>/<title>; PB_FRESH=1
# starts over).  Its shell-outs (amixer, the update and vidprog init
# scripts) are logging no-ops or ours ($PB_RIG/shell.log).
# Switches: sw.py.  Picture: shot.sh.  Stop: killgame.sh.
set -u
. "$(dirname "$0")/pbpath.sh"
BUILD=; VISIBLE=0; AUDIO=0
while [ $# -gt 0 ]; do
    case "$1" in
        --visible) VISIBLE=1 ;;
        --audio) AUDIO=1 ;;
        -*) echo "run_game.sh: unknown option $1" >&2; exit 2 ;;
        *) BUILD=$1 ;;
    esac
    shift
done
[ -z "$BUILD" ] && BUILD=$(ls -1td "$PB_CACHE"/*/ 2>/dev/null | head -1)
case "$BUILD" in /*) ;; "") ;; *) BUILD=$PB_CACHE/$BUILD ;; esac
BUILD=${BUILD%/}
[ -n "$BUILD" ] && [ -x "$BUILD/pinprog" ] && [ -x "$BUILD/vidprog" ] ||
    { echo "run_game.sh: not a prepared build: ${BUILD:-<none>} (prepare.sh)" >&2; exit 2; }
[ -f "$PB_ENV/.ready" ] || { echo "run_game.sh: no libraries in $PB_ENV (setup.sh)" >&2; exit 2; }
[ -f "$PB_SHIM" ] || { echo "run_game.sh: no $PB_SHIM (build.sh)" >&2; exit 2; }
AUDIO=$(rigboard_audio "$VISIBLE" "$AUDIO")
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to $PB_USER itself)" >&2; exit 2; }
[ -n "$PB_USER" ] || { echo "run_game.sh: no ordinary user account to run the game as" >&2; exit 2; }

TITLE=$(cat "$BUILD/.pad_title" 2>/dev/null || echo predator)
tget() { python3 "$PB_TOOLS/pbtitles.py" get "$TITLE" "$1"; }
ATTRACT=$(tget attract)
[ -n "$ATTRACT" ] || { echo "run_game.sh: unknown title $TITLE" >&2; exit 2; }

bash "$PB_TOOLS/killgame.sh" >/dev/null 2>&1

rm -rf "$PB_RIG"
G=$PB_RIG/game
mkdir -p "$PB_RIG"/{bin,initd,utils,home}
# The shim is preloaded from this slot's folder, never from the rig's: an
# installed app's rig is /mnt/c/Program Files/..., and both the launch line
# below (word-split) and LD_PRELOAD itself (a space-separated list) break a
# path at its spaces - env ran "Files/Pinball" and the game never started
# (PAD-313).
cp "$PB_SHIM" "$PB_RIG/pbshim.so"
cp -al "$(realpath "$BUILD")" "$G"
rm -f "$G/.pad_title"
NV=$PB_ROOT/nv$PB_SLOT/$TITLE
[ "${PB_FRESH:-0}" = 1 ] && rm -rf "$NV"
mkdir -p "$NV/nvram"
rm -rf "$G/nvram"; ln -s "$NV/nvram" "$G/nvram"
chown -R "$PB_USER": "$NV"
for c in amixer hwclock reboot shutdown poweroff sudo; do
    printf '#!/bin/sh\necho "$(date +%%T) %s $*" >> %s/shell.log\nexit 0\n' \
        "$c" "$PB_RIG" > "$PB_RIG/bin/$c"
done
printf '#!/bin/sh\necho "$(date +%%T) game_update.sh $*" >> %s/shell.log\nexit 0\n' \
    "$PB_RIG" > "$PB_RIG/utils/game_update.sh"
# The machine's init script for the screen program: pinprog restarts vidprog
# through it.  Ours logs, and starts the one vidprog this slot runs.
cat > "$PB_RIG/initd/S11vidprog" <<EOF
#!/bin/sh
echo "\$(date +%T) S11vidprog \$*" >> $PB_RIG/shell.log
case "\$1" in
    stop) for p in \$(pgrep -u $PB_USER -xf ./vidprog); do
              tr '\0' '\n' < /proc/\$p/environ | grep -qx PB_MARK=$PB_RIG && kill \$p
          done ;;
    start) cd /opt/game && ./vidprog >> $PB_RIG/vidprog.out 2>&1 & ;;
esac
exit 0
EOF
chmod 755 "$PB_RIG"/bin/* "$PB_RIG"/utils/* "$PB_RIG"/initd/*
echo "$BUILD" > "$PB_RIG/build"
echo "$TITLE" > "$PB_RIG/title"
echo "$VISIBLE" > "$PB_RIG/visible"
# the version the machine would show: the last update's name, 1_0_1 -> 1.0.1
tail -1 "$BUILD/.pad_sources" 2>/dev/null | sed -n 's/.*_game_\([0-9_]*\)\.upd$/\1/p' |
    tr _ . > "$PB_RIG/version"
touch "$(realpath "$BUILD")/.used"
chown -R "$PB_USER": "$PB_RIG"

# The boards first: pinprog opens both ports at start, then retries.
PRIO="nice -n -10"
chrt -r 10 true 2>/dev/null && PRIO="chrt -r 10"
setsid -f env PB_MARK="$PB_RIG" PBFAST_TRACE=${PBFAST_TRACE:-0} $PRIO python3 -u "$PB_TOOLS/pbfast.py" \
    --dir "$PB_RIG" --title "$TITLE" < /dev/null > "$PB_RIG/pbfast.out" 2>&1
for _ in $(seq 1 50); do [ -S "$PB_RIG/ctl.sock" ] && break; sleep 0.1; done
[ -S "$PB_RIG/ctl.sock" ] || { echo "run_game.sh: the board did not come up:" >&2; cat "$PB_RIG/pbfast.out" >&2; exit 1; }

W=1920; H=1080
if [ $VISIBLE = 1 ]; then
    DISP=${DISPLAY:-:0}
else
    DISP=$PB_DISPLAY
    # A display lock left by a killed Xvfb refuses the next one.
    LOCK=/tmp/.X${DISP#:}-lock
    if [ -f "$LOCK" ] && ! kill -0 "$(tr -dc 0-9 < "$LOCK")" 2>/dev/null; then rm -f "$LOCK"; fi
    setsid -f env PB_MARK="$PB_RIG" Xvfb "$DISP" -screen 0 ${W}x${H}x24 -nolisten tcp \
        < /dev/null > "$PB_RIG/xvfb.log" 2>&1
    # PAD-Runtime's Xvfb listens only on its abstract socket.
    for _ in $(seq 1 50); do grep -q "@/tmp/.X11-unix/X${DISP#:}\$" /proc/net/unix && break; sleep 0.1; done
    pgrep -xf "Xvfb $DISP .*" | head -1 > "$PB_RIG/xvfb.pid"
fi
echo "$DISP" > "$PB_RIG/display"
echo "${W}x${H}" > "$PB_RIG/window"

if [ $AUDIO = 1 ] && [ -S /mnt/wslg/PulseServer ]; then
    AUDIO_ENV="PULSE_SERVER=unix:/mnt/wslg/PulseServer"
else
    AUDIO_ENV="PULSE_SERVER=unix:/nonexistent SDL_AUDIODRIVER=dummy"
fi
# The video link: pinprog's fixed TCP 5555, moved per slot by the shim.
VIDPORT=$((15555 + PB_SLOT))
GST="GST_PLUGIN_SYSTEM_PATH=$PB_ENV/lib/gstreamer-1.0 GST_PLUGIN_SCANNER=$PB_ENV/libexec/gstreamer-1.0/gst-plugin-scanner GST_REGISTRY=$PB_ROOT/gst-registry.bin"
ENVS="PATH=$PB_RIG/bin:/usr/local/bin:/usr/bin:/bin HOME=$PB_RIG/home USER=$PB_USER LANG=C.UTF-8 \
DISPLAY=$DISP $AUDIO_ENV PB_MARK=$PB_RIG PB_DEV=$PB_RIG/dev PB_VIDPORT=$VIDPORT \
PB_WINDOWED=${PB_WINDOWED:-$VISIBLE} LD_LIBRARY_PATH=$PB_ENV/lib LD_PRELOAD=$PB_RIG/pbshim.so PB_FPS_LOG=$PB_RIG/fps.log $GST"

# vidprog (the game's user) writes its frame rate here (pbshim.c)
: > "$PB_RIG/fps.log"; chmod 666 "$PB_RIG/fps.log"

# ns.sh records itself: neither it nor the runuser wrappers it starts carry
# PB_MARK, and a wrapper whose program was killed sits STOPPED (T) with a
# zombie under it, forever - killgame.sh ends them by this pid.
cat > "$PB_RIG/ns.sh" <<EOF
echo \$\$ > $PB_RIG/ns.pid
mount -t tmpfs -o mode=755 tmpfs /opt || exit 1
mkdir -p /opt/game /opt/utils
mount --bind "$G" /opt/game || exit 1
mount --bind "$PB_RIG/utils" /opt/utils
[ -d /etc/init.d ] && mount --bind "$PB_RIG/initd" /etc/init.d
cd /opt/game || exit 1
runuser -u $PB_USER -- env -i $ENVS ./pinprog >> $PB_RIG/pinprog.out 2>&1 &
echo \$! > $PB_RIG/game.pid.ns
sleep 1
runuser -u $PB_USER -- env -i $ENVS ./vidprog >> $PB_RIG/vidprog.out 2>&1 &
wait
EOF
# Detached whole (setsid -f, stdin closed): a child of runuser dies with the
# wsl.exe that started this (tools/bof_emu learned it).
setsid -f unshare -m --propagation private bash "$PB_RIG/ns.sh" \
    < /dev/null > "$PB_RIG/ns.out" 2>&1
# The app's Volume / Mute, live, as on the AP and Spooky rigs: pbvol.py
# holds this slot's stream at the level in the control file every Emulate
# tab writes.  It waits for the game, and ends with it.
if [ $AUDIO = 1 ] && [ -n "${PAD_AUDIO_CTL:-}" ] && [ -S /mnt/wslg/PulseServer ]; then
    setsid -f python3 "$PB_TOOLS/pbvol.py" --ctl "$PAD_AUDIO_CTL" --rig "$PB_RIG" \
        < /dev/null >> "$PB_RIG/pbvol.log" 2>&1
fi
for _ in $(seq 1 50); do
    p=$(pgrep -u "$PB_USER" -xf './pinprog' | while read -r q; do
        tr '\0' '\n' < /proc/$q/environ 2>/dev/null | grep -qx "PB_MARK=$PB_RIG" && echo $q; done | head -1)
    [ -n "$p" ] && { echo "$p" > "$PB_RIG/game.pid"; break; }
    sleep 0.1
done

# Up = the attract show started (raven.log) with the screen program running.
for i in $(seq 1 600); do
    grep -qE "$ATTRACT" "$G/raven.log" 2>/dev/null && break
    [ "$i" -gt 50 ] && ! pb_game_alive && break
    sleep 0.1
done
if pb_game_alive && grep -qE "$ATTRACT" "$G/raven.log" 2>/dev/null; then
    # the virtual playfield's table (pbpf.py reads it; status.sh names it)
    python3 "$PB_TOOLS/pbswitches.py" "$PB_RIG" && chmod 644 "$PB_RIG/switches.json"
    echo "Ready: $(basename "$BUILD"), slot $PB_SLOT, display $DISP"
    rigboard_post pb "$PB_SLOT" "$(pb_game_pid)" "$(basename "$BUILD")" "${PAD_TITLE:-$(tget title)}" "$VISIBLE" "$AUDIO"
    # The playfield window's keys in the game's own window too (PAD-313):
    # on the desktop (PAD_GAMEKEYS=1 forces it on a hidden run, for tests).
    # It ends with the game.
    if [ "${PAD_GAMEKEYS:-$VISIBLE}" = 1 ]; then
        setsid -f python3 -u "$PB_TOOLS/../ap_emu/gamekeys.py" --display "$DISP" \
            --mark "PB_MARK=$PB_RIG" --sock "$PB_RIG/ctl.sock" \
            --pidfile "$PB_RIG/game.pid" --table "$PB_RIG/switches.json" \
            < /dev/null > "$PB_RIG/gamekeys.log" 2>&1
    fi
else
    echo "run_game.sh: the game did not reach attract:" >&2
    # each log on its own: `tail -20 a b` is refused outright ("option used
    # in invalid context") and printed nothing at all (PAD-313)
    for f in "$G/raven.log" "$PB_RIG/pbfast.log" "$PB_RIG/pinprog.out" \
             "$PB_RIG/vidprog.out" "$PB_RIG/ns.out"; do
        [ -s "$f" ] && { echo "--- $(basename "$f")"; tail -n 20 "$f"; }
    done >&2
    exit 1
fi
