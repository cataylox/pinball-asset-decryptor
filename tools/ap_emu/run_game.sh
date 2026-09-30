#!/bin/bash
# run_game.sh <build> [--visible] [--audio]
#
# Start an American Pinball game on this PC, on the game's own FakePinPROC
# and pySDL2 desktop display (py/aprun.py).  <build> is a folder prepare.py
# made (a name under $AP_CACHE or a path).  Run as root; it drops to
# $AP_USER itself.  Returns once the game's run loop is going (or it died).
#
#   --visible    draw on the WSLg desktop instead of the slot's hidden Xvfb
#                display (the default: windows popping up are disruptive;
#                shot.sh shows a hidden run)
#   --audio      play sound through WSLg's PulseAudio (default: SDL's disk
#                writer into /dev/null - the game still opens its mixer)
#
# The game runs in $AP_RIG/game, a hard-linked copy of the build (it writes
# its audits, settings and logs there, never into the cache), seen by the
# game at its machine path /game/<machine_dir> in a private mount namespace
# (the code reaches for /game/houdini/assets/..., /game/local_config/), so
# several slots can each have their own /game.
# Switches: sw.py.  Picture: shot.sh.  Stop: killgame.sh.
set -u
. "$(dirname "$0")/appath.sh"
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
case "$BUILD" in /*) ;; "") ;; *) BUILD=$AP_CACHE/$BUILD ;; esac
[ -n "$BUILD" ] && [ -f "$BUILD/launcher" ] || { echo "run_game.sh: not a prepared build: ${BUILD:-<none>} (prepare.py)" >&2; exit 2; }
[ -x "$AP_PY/bin/python2" ] || { echo "run_game.sh: no $AP_PY (setup.sh)" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to $AP_USER itself)" >&2; exit 2; }
[ -n "$AP_USER" ] || { echo "run_game.sh: no ordinary user account to run the game as" >&2; exit 2; }

bash "$AP_TOOLS/killgame.sh" >/dev/null 2>&1

rm -rf "$AP_RIG"
G=$AP_RIG/game
mkdir -p "$AP_RIG/local_config"
cp -al "$(realpath "$BUILD")" "$G"
LAUNCHER=$(cat "$BUILD/launcher")
# Which Python: the bytecode says (2.7's magic is 03f3; Galactic Tank
# Force's 2026 build is 3.14, 2b0e, and ships its sources too).
GPY=$AP_PY/bin/python2
if [ "$(find "$BUILD" -maxdepth 3 -name '*.pyc' -print -quit | xargs head -c 2 | od -An -tx1 | tr -d ' ')" != 03f3 ]; then
    GPY=$AP_PY3/bin/python3
fi
[ -x "$GPY" ] || { echo "run_game.sh: no $GPY (setup.sh)" >&2; exit 2; }
MDIR=$(cat "$BUILD/machine_dir" 2>/dev/null || "$AP_PY/bin/python2" "$AP_TOOLS/py/machinedir.py" "$BUILD")
LSUB=$(dirname "$LAUNCHER")                 # "." or the game folder (oktoberfest)
# Houdini's launcher installs `codeupdate`/`dumplogs` into /usr/bin and
# writes /etc/osversion when both sit beside it (a one-time OS update);
# the rig's copy goes without them.
rm -f "$G/$LSUB/codeupdate" "$G/$LSUB/dumplogs"
# procgame reads ../local_config/config.yaml first (from the folder it runs
# in); on the machine that is /game/local_config, the settings folder.
# The game RUNS in the folder that holds its assets/ (asset paths are
# relative to it), which is not always the launcher's: Galactic Tank Force's
# launcher.py sits above tank/, which has assets/ and a copy of config/.
ADIR=$G/$LSUB
if [ ! -d "$ADIR/assets" ]; then
    for d in "$G"/*/; do [ -d "$d/assets" ] && { ADIR=${d%/}; break; }; done
fi
AVC=0; grep -q USING_AVCONTROLLER "$G/$LAUNCHER" && AVC=1
AP_AVC=$AVC "$AP_PY/bin/python2" "$AP_TOOLS/py/mkconfig.py" "$G/$LSUB" "$ADIR/../local_config/config.yaml" \
    "$AP_PY/lib" "$ADIR" > "$AP_RIG/rig.log"
mkfifo "$AP_RIG/input"
echo "$BUILD" > "$AP_RIG/build"
echo "$VISIBLE" > "$AP_RIG/visible"
chown -R "$AP_USER": "$AP_RIG"

if [ $VISIBLE = 1 ]; then
    DISP=${DISPLAY:-:0}
else
    DISP=$AP_DISPLAY
    setsid -f Xvfb "$DISP" -screen 0 2560x1440x24 -nolisten tcp \
        < /dev/null > "$AP_RIG/xvfb.log" 2>&1
    for _ in $(seq 1 50); do [ -e "/tmp/.X11-unix/X${DISP#:}" ] && break; sleep 0.1; done
    pgrep -xf "Xvfb $DISP .*" | head -1 > "$AP_RIG/xvfb.pid"
fi
echo "$DISP" > "$AP_RIG/display"

if [ $AUDIO = 1 ] && [ -S /mnt/wslg/PulseServer ]; then
    AUDIO_ENV="SDL_AUDIODRIVER=pulse PULSE_SERVER=unix:/mnt/wslg/PulseServer"
else
    AUDIO_ENV="SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=/dev/null SDL_DISKAUDIODELAY=0"
fi

# /game as the machine has it, private to this run: the build at
# /game/<machine_dir>, the rig's settings folder at /game/local_config, and
# procgame's fallback font folder (/game/houdini/assets/dmd/fonts, in every
# title's framework) from the title's own fonts when it is not Houdini.
# The empty /game on the host is only a mount point.
mkdir -p /game
GM=/game/$MDIR
PYP=$AP_TOOLS/py:$GM/$LSUB:$GM
[ -d "$G/ApiLib" ] && PYP=$PYP:$GM/ApiLib
FONTS=""
if [ "$MDIR" != houdini ]; then
    # Every AP machine's OS image was made on a Houdini, so that folder is
    # there whatever the title; its fonts are not in the other titles'
    # packages.  The title's own Courier/Impact when it has them, else
    # DejaVu Sans (setup.sh) standing in - it only draws fallback text.
    FONTS=$AP_RIG/fonts
    mkdir -p "$FONTS"
    for f in Courier.ttf Impact.ttf; do
        src=$(find "$G" -maxdepth 5 -type f -name "$f" -path '*assets*' | head -1)
        if [ -n "$src" ]; then cp "$src" "$FONTS/$f"; else cp "$AP_PY/fonts/DejaVuSans.ttf" "$FONTS/$f"; fi
        # ...and the framework's first try is assets/dmd/fonts/ in the folder
        # it runs in (Hot Wheels' launcher moves into hotWheels/): the rig's
        # copy gets them in every game folder that has assets/.
        for d in "$G/$LSUB" "$G"/*/; do
            [ -d "$d/assets" ] || continue
            mkdir -p "$d/assets/dmd/fonts"
            [ -e "$d/assets/dmd/fonts/$f" ] || { cp "$FONTS/$f" "$d/assets/dmd/fonts/$f"; chown -R "$AP_USER": "$d/assets/dmd/fonts"; }
        done
    done
    chown -R "$AP_USER": "$FONTS"
fi
# The A/V-controller titles (Hot Wheels on): the launcher sets
# USING_AVCONTROLLER and the game draws and plays nothing itself - it sends
# commands over localhost TCP to AP's native `apiav`, which the machine's
# xinitrc starts first: `apiav -d <game>/assets -x &` in the game folder.
# apiav's GStreamer/SDL2 come from their own env ($AP_AV, setup.sh).
AV=""
if [ $AVC = 1 ] && [ -x "$G/apiav" ]; then
    AV="$GM/apiav -d $GM${ADIR#$G}/assets -x"
    echo 1 > "$AP_RIG/av"
    # The game reaches it at localhost:16726, fixed: one A/V title at a time
    # across all slots.  (A network namespace per slot would lift that, but
    # PAD-Runtime's /tmp/.X11-unix is WSLg's read-only mount, so Xvfb serves
    # only on its abstract socket, which a network namespace cannot see.)
    if awk '$4 == "0A" && $2 ~ /:4156$/ {f=1} END {exit !f}' /proc/net/tcp; then
        echo "run_game.sh: another slot's apiav holds port 16726 (one A/V title at a time)" >&2
        exit 2
    fi
fi
cat > "$AP_RIG/ns.sh" <<EOF
mount -t tmpfs -o mode=755 tmpfs /game || exit 1
mkdir -p "$GM" /game/local_config
mount --bind "$G" "$GM"
mount --bind "$AP_RIG/local_config" /game/local_config
if [ -n "$FONTS" ]; then
    mkdir -p /game/houdini/assets/dmd/fonts
    mount --bind "$FONTS" /game/houdini/assets/dmd/fonts
fi
RUN="runuser -u $AP_USER -- env -i PATH=$(dirname "$GPY"):/usr/local/bin:/usr/bin:/bin HOME=$AP_RIG USER=$AP_USER LANG=C.UTF-8 DISPLAY=$DISP $AUDIO_ENV AP_LOG=$AP_RIG/rig.log"
if [ -n "$AV" ]; then
    cd "$GM${ADIR#$G}" || exit 1
    \$RUN LD_LIBRARY_PATH=$AP_AV/lib GST_PLUGIN_SYSTEM_PATH=$AP_AV/lib/gstreamer-1.0 \\
        GST_REGISTRY=$AP_RIG/gst-registry.bin $AV > "$AP_RIG/apiav.out" 2>&1 &
    sleep 2
fi
cd "$GM${ADIR#$G}" || exit 1
exec \$RUN PYTHONPATH="$PYP" PYSDL2_DLL_PATH="$AP_PY/lib" \\
    AP_FIFO="$AP_RIG/input" AP_PIDFILE="$AP_RIG/game.pid" \\
    "$GPY" -u "$AP_TOOLS/py/aprun.py" "$(realpath --relative-to="$ADIR" "$G/$LAUNCHER")"
EOF
# Detached whole (setsid -f, stdin closed): a child of runuser dies with the
# wsl.exe that started this (tools/bof_emu learned it).
setsid -f unshare -m --propagation private bash "$AP_RIG/ns.sh" \
    < /dev/null > "$AP_RIG/game.out" 2>&1

# Up = its run loop started (aprun.py logs it; the window comes first).  A
# big title loads its assets for a minute or more before that.
for i in $(seq 1 3000); do
    grep -q '^[0-9:]* run_loop' "$AP_RIG/rig.log" && break
    [ "$i" -gt 50 ] && ! ap_game_alive && break
    sleep 0.1
done
if ap_game_alive && grep -q '^[0-9:]* run_loop' "$AP_RIG/rig.log"; then
    echo "Ready: $(basename "$BUILD") (/game/$MDIR), slot $AP_SLOT, display $DISP$([ -n "$AV" ] && echo ", apiav")"
else
    echo "run_game.sh: the game did not come up:" >&2
    tail -20 "$AP_RIG/game.out" >&2
    exit 1
fi
