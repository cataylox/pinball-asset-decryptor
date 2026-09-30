#!/bin/bash
# run_game.sh <build> [--visible] [--audio]
#
# Start a Spooky Unity game (Beetlejuice) on this PC, on the rig's emulated
# Warden board (spkwarden.py).  <build> is a folder prepare.sh made (a name
# under $SPK_CACHE or a path).  Run as root; it drops to $SPK_USER itself.
# Returns once the game reached attract mode (or it died).
#
#   --visible    draw on the WSLg desktop instead of the slot's hidden Xvfb
#                display (the default: windows popping up are disruptive;
#                shot.sh shows a hidden run)
#   --audio      play sound through WSLg's PulseAudio (default: no audio
#                device - Unity runs silent)
#
# The game sees the machine's /game in a private mount namespace:
#   /game/code/uptest   the build, hard-linked into $SPK_RIG/game (the game
#                       writes marker files beside itself, never the cache)
#   /game/code/config   settings, audits, scores  ($SPK_RIG/config)
#   /game/logs, /game/tmp, /game/media, /game/backup, /game/update
# and its own hostname ("pad-rig-<slot>"): the game is in its built-in
# VIRTUAL mode unless the hostname says "haunted-mansion", and virtual mode
# is what keeps its sudo/reboot/firmware-flash shell calls from running.
# Switches: sw.py.  Picture: shot.sh.  Stop: killgame.sh.
set -u
. "$(dirname "$0")/spkpath.sh"
BUILD=${1:-}; shift 2>/dev/null || true
VISIBLE=0; AUDIO=0
while [ $# -gt 0 ]; do
    case "$1" in
        --visible) VISIBLE=1 ;;
        --audio) AUDIO=1 ;;
        *) echo "run_game.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
case "$BUILD" in /*) ;; "") ;; *) BUILD=$SPK_CACHE/$BUILD ;; esac
[ -n "$BUILD" ] && [ -x "$BUILD/main.x86_64" ] || { echo "run_game.sh: not a prepared build: ${BUILD:-<none>} (prepare.sh)" >&2; exit 2; }
[ -f "$SPK_SHIM" ] || { echo "run_game.sh: no $SPK_SHIM (build.sh)" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to $SPK_USER itself)" >&2; exit 2; }
[ -n "$SPK_USER" ] || { echo "run_game.sh: no ordinary user account to run the game as" >&2; exit 2; }

bash "$SPK_TOOLS/killgame.sh" >/dev/null 2>&1

rm -rf "$SPK_RIG"
G=$SPK_RIG/game
mkdir -p "$SPK_RIG"/{config,logs,tmp,media,backup,update,home}
cp -al "$(realpath "$BUILD")" "$G"
# A machine leaves the factory with its defaults saved (service menu); a
# fresh settings folder without them stops attract behind a "FACTORY DEFAULT
# SETTINGS HAVE NOT BEEN SAVED" dialog.  An empty set = the build's own.
echo '{}' > "$SPK_RIG/config/beetlejuice_factory_defaults.json"
echo "$BUILD" > "$SPK_RIG/build"
echo "$VISIBLE" > "$SPK_RIG/visible"
chown -R "$SPK_USER": "$SPK_RIG"

# The board first: the game opens /dev/WARDEN once at start, then retries
# every half second until it answers.
setsid -f env SPK_MARK="$SPK_RIG" runuser -u "$SPK_USER" -- \
    python3 -u "$SPK_TOOLS/spkwarden.py" "$SPK_RIG" < /dev/null > "$SPK_RIG/warden.out" 2>&1
for _ in $(seq 1 50); do [ -s "$SPK_RIG/warden.tty" ] && break; sleep 0.1; done
TTY=$(cat "$SPK_RIG/warden.tty" 2>/dev/null)
[ -n "$TTY" ] || { echo "run_game.sh: the board did not come up:" >&2; cat "$SPK_RIG/warden.out" >&2; exit 1; }

if [ $VISIBLE = 1 ]; then
    DISP=${DISPLAY:-:0}
else
    DISP=$SPK_DISPLAY
    setsid -f Xvfb "$DISP" -screen 0 1920x1080x24 -nolisten tcp \
        < /dev/null > "$SPK_RIG/xvfb.log" 2>&1
    for _ in $(seq 1 50); do [ -e "/tmp/.X11-unix/X${DISP#:}" ] && break; sleep 0.1; done
    pgrep -xf "Xvfb $DISP .*" | head -1 > "$SPK_RIG/xvfb.pid"
fi
echo "$DISP" > "$SPK_RIG/display"

if [ $AUDIO = 1 ] && [ -S /mnt/wslg/PulseServer ]; then
    AUDIO_ENV="PULSE_SERVER=unix:/mnt/wslg/PulseServer"
else
    AUDIO_ENV="PULSE_SERVER=unix:/nonexistent SDL_AUDIODRIVER=dummy"
fi

cat > "$SPK_RIG/ns.sh" <<EOF
hostname pad-rig-$SPK_SLOT
mount -t tmpfs -o mode=755 tmpfs /game || exit 1
mkdir -p /game/code/uptest /game/code/config /game/logs /game/tmp /game/media /game/backup /game/update /game/vosk
mount --bind "$G" /game/code/uptest
for d in config; do mount --bind "$SPK_RIG/\$d" /game/code/\$d; done
for d in logs tmp media backup update; do mount --bind "$SPK_RIG/\$d" /game/\$d; done
chown "$SPK_USER": /game /game/code /game/vosk
cd /game/code/uptest || exit 1
exec runuser -u $SPK_USER -- env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=$SPK_RIG/home \\
    USER=$SPK_USER LANG=C.UTF-8 DISPLAY=$DISP $AUDIO_ENV SPK_MARK=$SPK_RIG \\
    LP_NUM_THREADS=${SPK_LP_THREADS:-4} \\
    SPK_WARDEN=$TTY LD_PRELOAD=$SPK_SHIM \\
    ./main.x86_64 -logFile $SPK_RIG/player.log -screen-fullscreen 0 \\
    -screen-width 1920 -screen-height 1080 -force-glcore
EOF
# Detached whole (setsid -f, stdin closed): a child of runuser dies with the
# wsl.exe that started this (tools/bof_emu learned it).
setsid -f unshare -m -u --propagation private bash "$SPK_RIG/ns.sh" \
    < /dev/null > "$SPK_RIG/game.out" 2>&1
for _ in $(seq 1 50); do
    p=$(spk_slot_pids | while read -r q; do grep -q main.x86_64 /proc/$q/cmdline 2>/dev/null && echo $q; done | head -1)
    [ -n "$p" ] && { echo "$p" > "$SPK_RIG/game.pid"; break; }
    sleep 0.1
done

# Up = attract mode started (the game logs every mode it starts).  Loading
# ~4 GB of media takes a while on a spinning disk.
for i in $(seq 1 3000); do
    grep -q 'Attract_mode started' "$SPK_RIG/player.log" 2>/dev/null && break
    [ "$i" -gt 100 ] && ! spk_game_alive && break
    sleep 0.1
done
if spk_game_alive && grep -q 'Attract_mode started' "$SPK_RIG/player.log" 2>/dev/null; then
    echo "Ready: $(basename "$BUILD"), slot $SPK_SLOT, display $DISP"
else
    echo "run_game.sh: the game did not reach attract:" >&2
    tail -20 "$SPK_RIG/player.log" "$SPK_RIG/game.out" >&2 2>/dev/null
    exit 1
fi
