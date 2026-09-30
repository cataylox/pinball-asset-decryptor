#!/bin/bash
# run_game.sh <build> [--visible] [--audio] [--sim]
#
# Start an apiav-era American Pinball game on this PC: the title's own
# `apiav` (every screen and sound) and its Python 3.12 game code, on
# tools/proc_emu's emulated P3-ROC (pinproc = proc_emu's pure-Python stub,
# the board seeded from the title's machine yaml: trough full).  <build> is
# a folder prepare.py made (a name under $AV_CACHE or a path).  Run as root;
# the game and apiav run as $AV_USER.  Returns once the game is in attract
# (or died).
#
#   --visible    draw on the WSLg desktop instead of the slot's hidden Xvfb
#                display (the default: windows popping up are disruptive;
#                shot.sh shows a hidden run)
#   --audio      play sound through WSLg's PulseAudio (default: SDL's disk
#                writer into /dev/null - apiav still opens its mixer)
#   --sim        also draw AP's own playfield simulator panel (lamps and
#                switches) right of the main screen: /game/.sim
#
# Both processes run in a network + mount namespace of the rig's own (see
# avpath.sh): localhost:16726 is private to the slot, and the rig's copy of
# the build is bind-mounted on /game, where the code expects it
# (/game/local_config, /game/.sim).  The copy is hard-linked from the cache;
# the game writes only new files (local_config/, /tmp/log-*).
# Switches: sw.sh.  Picture: shot.sh.  Stop: killgame.sh.
set -u
. "$(dirname "$0")/avpath.sh"
BUILD=${1:-}; shift 2>/dev/null || true
VISIBLE=0; AUDIO=0; SIM=0
while [ $# -gt 0 ]; do
    case "$1" in
        --visible) VISIBLE=1 ;;
        --audio) AUDIO=1 ;;
        --sim) SIM=1 ;;
        *) echo "run_game.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
case "$BUILD" in /*) ;; "") ;; *) BUILD=$AV_CACHE/$BUILD ;; esac
[ -n "$BUILD" ] && [ -f "$BUILD/title" ] || { echo "run_game.sh: not a prepared build: ${BUILD:-<none>} (prepare.py)" >&2; exit 2; }
[ -f "$AV_ENV/.ready" ] || { echo "run_game.sh: no $AV_ENV (setup.sh)" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to $AV_USER itself)" >&2; exit 2; }
[ -n "$AV_USER" ] || { echo "run_game.sh: no ordinary user account to run the game as" >&2; exit 2; }

bash "$AV_TOOLS/killgame.sh" >/dev/null 2>&1

TITLE=$(cat "$BUILD/title")
rm -rf "$AV_RIG"
G=$AV_RIG/game
mkdir -p "$AV_RIG"
cp -al "$(realpath "$BUILD")" "$G"
mkdir -p "$G/local_config"
# procgame reads ../local_config/config.yaml from the folder the game starts
# in (/game/<title>).  The machine's own comes with AP's OS image, which AP
# does not publish; this is the rig's: proc_emu's pinproc.PinPROC (the
# default pinproc_class) and the key map shim apiav's keyEvents look up.
cat > "$G/local_config/config.yaml" <<YAML
pinproc_class: pinproc.PinPROC
use_desktop: true
use_virtual_dmd_only: true
YAML
[ $SIM = 1 ] && touch "$G/.sim"
echo "$BUILD" > "$AV_RIG/build"
echo "$VISIBLE" > "$AV_RIG/visible"
# The game may create files anywhere in its tree (local_config/ audits and
# settings), so it owns every directory; the files stay root's - they are the
# cache's own inodes (hard links), and the game must not rewrite them.
chown "$AV_USER": "$AV_RIG"
find "$G" -type d -exec chown "$AV_USER": {} +
chown -R "$AV_USER": "$G/local_config"
: > "$AV_RIG/rig.log"

# The board, seeded from the machine yaml (a full trough is open NC optos);
# prochw.py needs PyYAML, which PAD-Runtime's python lacks and the env has.
# AP's coinDoor switch is ACTIVE when the door is shut (coinDoorUI puts up
# "Coin Door is Open" when it goes inactive), so a closed cabinet seeds it
# active.
PATH=$AV_ENV/bin:$PATH PAD_SLOT=$AV_SLOT bash "$AV_PROC/hw.sh" --yaml "$G/$TITLE/config/$TITLE.yaml" \
    --active coinDoor >> "$AV_RIG/rig.log" \
    || { echo "run_game.sh: the board did not come up" >&2; exit 3; }
chmod 666 "$(. "$AV_PROC/procpath.sh"; echo "$PROC_FPGA")"

# A hidden run's Xvfb starts inside the namespace (netns.sh): WSLg mounts
# /tmp/.X11-unix read-only, so Xvfb can only listen on its abstract socket,
# and an abstract socket belongs to one network namespace.
if [ $VISIBLE = 1 ]; then DISP=${DISPLAY:-:0}; XVFB=0; else DISP=$AV_DISPLAY; XVFB=1; fi
echo "$DISP" > "$AV_RIG/display"

if [ $AUDIO = 1 ] && [ -S /mnt/wslg/PulseServer ]; then
    AUDIO_ENV="SDL_AUDIODRIVER=pulse PULSE_SERVER=unix:/mnt/wslg/PulseServer"
else
    AUDIO_ENV="SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=/dev/null SDL_DISKAUDIODELAY=0"
fi
mkdir -p /game     # the mount point only; nothing is ever written to it

# Detached whole (setsid -f, stdin closed): a child of the wsl.exe that
# started this dies with it (tools/bof_emu learned it).
# shellcheck disable=SC2086
setsid -f unshare --net --mount --propagation private \
    env AV_TOOLS="$AV_TOOLS" AV_RIG="$AV_RIG" AV_ENV="$AV_ENV" AV_USER="$AV_USER" \
        AV_TITLE="$TITLE" AV_STUB="$AV_PROC/pystub" DISPLAY="$DISP" AV_XVFB=$XVFB $AUDIO_ENV \
        PROC_EMU_FPGA="$(. "$AV_PROC/procpath.sh"; echo "$PROC_FPGA")" \
    bash "$AV_TOOLS/netns.sh" < /dev/null >> "$AV_RIG/rig.log" 2>&1

# Up = the game is in attract and talking to apiav: AVController logged
# "Connected to A/V Controller" (apiav answered with its version) and the
# attract mode is running its pages ("Attract: Playing next lightshow").
# A cold cache reads ~2 GB of assets first.
UP='Attract: Playing next lightshow'
up() {
    grep -q 'Connected to A/V Controller' "$AV_RIG/game.out" 2>/dev/null \
        && grep -q "$UP" "$AV_RIG/game.out" 2>/dev/null
}
for i in $(seq 1 1800); do
    up && break
    [ "$i" -gt 50 ] && ! av_alive game && break
    sleep 0.1
done
if av_alive game && av_alive apiav && up; then
    echo "Ready: $(basename "$BUILD"), slot $AV_SLOT, display $DISP"
else
    echo "run_game.sh: the game did not come up:" >&2
    tail -20 "$AV_RIG/game.out" >&2
    exit 1
fi
