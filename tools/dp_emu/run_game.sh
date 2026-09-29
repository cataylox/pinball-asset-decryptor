#!/bin/bash
# run_game.sh <build> [--version V] [--visible] [--audio]
#
# Start a Dutch Pinball game (The Big Lebowski) on this PC, on the game's own
# simulated P-ROC: `./start fakepinproc dev`.  <build> is a folder
# prepare.py made (a name under $DP_CACHE or a path).  Run as root; it drops
# to $DP_USER itself.  Returns once the game's window is up (or it died).
#
#   --version V  run <build>/V instead of the build's `version`
#   --visible    draw on the WSLg desktop instead of the slot's hidden Xvfb
#                display (the default: windows popping up are disruptive;
#                shot.sh shows a hidden run)
#   --audio      play sound through WSLg's PulseAudio (default: SDL's disk
#                writer into /dev/null - the game refuses to load its sounds
#                with no audio device at all)
#
# The game runs in $DP_RIG/game, a hard-linked copy of the build laid out
# as on the machine (assets/, <version>/, version, serial, temp/): it writes
# its database, run.log and restart marker there, never into the cache.
# Switches: sw.sh.  Picture: shot.sh.  Stop: killgame.sh.
set -u
. "$(dirname "$0")/dppath.sh"
BUILD=${1:-}; shift 2>/dev/null || true
VER=""; VISIBLE=0; AUDIO=0
while [ $# -gt 0 ]; do
    case "$1" in
        --version) VER=${2:-}; shift ;;
        --visible) VISIBLE=1 ;;
        --audio) AUDIO=1 ;;
        *) echo "run_game.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
case "$BUILD" in /*) ;; "") ;; *) BUILD=$DP_CACHE/$BUILD ;; esac
[ -n "$BUILD" ] && [ -d "$BUILD/assets" ] || { echo "run_game.sh: not a prepared build: ${BUILD:-<none>} (prepare.py)" >&2; exit 2; }
[ -n "$VER" ] || VER=$(cat "$BUILD/version")
[ -x "$BUILD/$VER/start" ] || { echo "run_game.sh: $BUILD has no version $VER" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to $DP_USER itself)" >&2; exit 2; }
[ -n "$DP_USER" ] || { echo "run_game.sh: no ordinary user account to run the game as" >&2; exit 2; }

# The input shim, rebuilt when its source is newer.
if [ ! -f "$DP_SHIM" ] || [ "$DP_TOOLS/dpinput.c" -nt "$DP_SHIM" ]; then
    mkdir -p "$DP_ROOT"
    gcc -shared -fPIC -O2 -Wall -o "$DP_SHIM.new" "$DP_TOOLS/dpinput.c" -ldl -lpthread \
        && mv "$DP_SHIM.new" "$DP_SHIM" || { echo "run_game.sh: cannot build dpinput.so" >&2; exit 3; }
fi

bash "$DP_TOOLS/killgame.sh" >/dev/null 2>&1

rm -rf "$DP_RIG"
G=$DP_RIG/game
mkdir -p "$G/temp"
cp -al "$(realpath "$BUILD/assets")" "$G/assets"
cp -al "$BUILD/$VER" "$G/$VER"
# A zero-byte sound stops the game at boot (pygame cannot load it); one
# fan-modded image carries one.  Stand a second of silence in for it, in
# the rig's copy only.
find "$G" -name '*.wav' -size 0 | while read -r f; do
    rm -f "$f"
    ffmpeg -loglevel error -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a pcm_s16le "$f"
    echo "$(date +%T) silenced empty ${f#$G/}" >> "$DP_RIG/rig.log"
done
: > "$G/serial"
echo "$VER" > "$G/version"
mkfifo "$DP_RIG/input"
echo "$BUILD" > "$DP_RIG/build"
echo "$VER" > "$DP_RIG/ver"
echo "$VISIBLE" > "$DP_RIG/visible"
chown -R "$DP_USER": "$DP_RIG"

if [ $VISIBLE = 1 ]; then
    DISP=${DISPLAY:-:0}
else
    DISP=$DP_DISPLAY
    setsid -f Xvfb "$DISP" -screen 0 1920x1080x24 -nolisten tcp \
        < /dev/null > "$DP_RIG/xvfb.log" 2>&1
    for _ in $(seq 1 50); do [ -e "/tmp/.X11-unix/X${DISP#:}" ] && break; sleep 0.1; done
    pgrep -xf "Xvfb $DISP .*" | head -1 > "$DP_RIG/xvfb.pid"
fi
echo "$DISP" > "$DP_RIG/display"

if [ $AUDIO = 1 ] && [ -S /mnt/wslg/PulseServer ]; then
    AUDIO_ENV="SDL_AUDIODRIVER=pulse PULSE_SERVER=unix:/mnt/wslg/PulseServer"
else
    AUDIO_ENV="SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=/dev/null SDL_DISKAUDIODELAY=0"
fi

# Detached whole (setsid -f OUTSIDE runuser, stdin closed): a child of
# runuser dies with the wsl.exe that started this (tools/bof_emu learned it).
cd "$G/$VER" || exit 3
# shellcheck disable=SC2086
setsid -f runuser -u "$DP_USER" -- env -i \
    PATH=/usr/local/bin:/usr/bin:/bin HOME="$DP_RIG" USER="$DP_USER" LANG=C.UTF-8 \
    DISPLAY="$DISP" $AUDIO_ENV \
    DPEMU_FIFO="$DP_RIG/input" DPEMU_LOG="$DP_RIG/rig.log" LD_PRELOAD="$DP_SHIM" \
    ./start fakepinproc dev < /dev/null > "$DP_RIG/game.out" 2>&1

# The PyInstaller bootloader re-executes itself: the game is the child whose
# working folder is ours.  Its first window means it is up.
for _ in $(seq 1 600); do
    grep -q '^video:' "$DP_RIG/rig.log" 2>/dev/null && break
    grep -q 'start returned' "$DP_RIG/game.out" 2>/dev/null && break   # the bootloader's exit line
    sleep 0.1
done
for p in $(pgrep -f '^\./start fakepinproc'); do
    [ "$(readlink "/proc/$p/cwd")" = "$G/$VER" ] && echo "$p" && break
done > "$DP_RIG/game.pid"
if dp_game_alive && grep -q '^video:' "$DP_RIG/rig.log"; then
    echo "Ready: $(basename "$BUILD") $VER, slot $DP_SLOT, display $DISP ($(grep '^video:' "$DP_RIG/rig.log" | tail -1 | cut -d' ' -f2))"
else
    echo "run_game.sh: the game did not come up:" >&2
    tail -20 "$DP_RIG/game.out" >&2
    exit 1
fi
