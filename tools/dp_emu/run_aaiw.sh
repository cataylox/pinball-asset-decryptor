#!/bin/bash
# run_aaiw.sh <build> [--visible] [--audio] - start Alice's Adventures in
# Wonderland (a prepare.py build of kind "aaiw") on this PC.  run_game.sh
# hands an aaiw build here; the app never calls it directly.  As root; the
# game runs as $DP_USER.
#
# AAIW is a native program on its own Buildroot root (glibc 2.37, SDL2),
# so it runs in a CHROOT of that root, never on PAD-Runtime's libraries:
#   lower  $DP_ROOT/lower/<build>   root.ext4, loop-mounted read-only once,
#                                   shared by every slot
#   rig    $DP_RIG/root             an overlay: the slot's own writable layer
#                                   ($DP_RIG/upper - settings, audits) over it
# /proc, /sys and /dev are bound in and each made rslave AT ONCE: PAD-Runtime's
# mounts are shared, and an unmount of a shared bind propagates back to the
# host's own /dev/pts (PAD-263 found that out the hard way).
#
# The game has no simulator of its own: aaiwshim.so (aaiw/aaiwshim.c) is its
# P-ROC and its input, loaded through the root's /etc/ld.so.preload (its
# busybox env and sh drop LD_PRELOAD).  AAIW_CLOSED tells the fake board
# which switches are closed at boot: every closed-at-rest switch in
# aaiw/switches.json, plus the balls in the trough.
set -u
. "$(dirname "$0")/dppath.sh"
BUILD=${1:-}; shift 2>/dev/null || true
VISIBLE=0; AUDIO=0
for a in "$@"; do
    case "$a" in
        --visible) VISIBLE=1 ;;
        --audio) AUDIO=1 ;;
        *) ;;                       # --version: an aaiw build has one
    esac
done
[ -f "$BUILD/root.ext4" ] || { echo "run_aaiw.sh: not an aaiw build: $BUILD" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_aaiw.sh: run as root" >&2; exit 2; }
AAIW=$DP_TOOLS/aaiw
SHIM=$DP_ROOT/aaiwshim.so

# The shim, rebuilt when its source is newer - and refused if this host's
# gcc bound it to a glibc newer than the game root's 2.37.
if [ ! -f "$SHIM" ] || [ "$AAIW/aaiwshim.c" -nt "$SHIM" ]; then
    mkdir -p "$DP_ROOT"
    gcc -shared -fPIC -O2 -Wall -o "$SHIM.new" "$AAIW/aaiwshim.c" -ldl -lpthread \
        || { echo "run_aaiw.sh: cannot build aaiwshim.so" >&2; exit 3; }
    if objdump -T "$SHIM.new" | grep -Eo 'GLIBC_2\.[0-9]+' | sort -uV | tail -1 \
            | awk -F. '{exit !($2 >= 38)}'; then
        echo "run_aaiw.sh: aaiwshim.so needs a glibc newer than the game's 2.37:" >&2
        objdump -T "$SHIM.new" | grep -E 'GLIBC_2\.(3[89]|[4-9][0-9])' >&2
        exit 3
    fi
    mv "$SHIM.new" "$SHIM"
fi

bash "$DP_TOOLS/killgame.sh" >/dev/null 2>&1

NAME=$(basename "$BUILD")
LOWER=$DP_ROOT/lower/$NAME
mkdir -p "$LOWER"
mountpoint -q "$LOWER" || mount -o ro,loop,noload "$BUILD/root.ext4" "$LOWER" \
    || { echo "run_aaiw.sh: cannot mount $BUILD/root.ext4" >&2; exit 3; }

dp_clear_rig || exit 3
R=$DP_RIG/root
mkdir -p "$DP_RIG/upper" "$DP_RIG/work" "$R"
mount -t overlay overlay -o "lowerdir=$LOWER,upperdir=$DP_RIG/upper,workdir=$DP_RIG/work" "$R" \
    || { echo "run_aaiw.sh: cannot build the game's root" >&2; exit 3; }
mount -t proc proc "$R/proc"
for d in sys dev; do
    mount --rbind "/$d" "$R/$d" && mount --make-rslave "$R/$d"
done
mount -t tmpfs -o mode=1777 tmpfs "$R/tmp"
mkdir -p "$R/tmp/.X11-unix"

# The game's user, and its settings folder, writable by it.
U=$(id -u "$DP_USER"); GID=$(id -g "$DP_USER")
grep -q "^$DP_USER:" "$R/etc/passwd" || echo "$DP_USER:x:$U:$GID:$DP_USER:/opt:/bin/sh" >> "$R/etc/passwd"
grep -q "^$DP_USER:" "$R/etc/group" || echo "$DP_USER:x:$GID:" >> "$R/etc/group"
chown "$U:$GID" "$R/opt"
chown -R "$U:$GID" "$R/opt/eeprom"

mkdir -p "$R/opt/.pad"
cp "$SHIM" "$R/opt/.pad/aaiwshim.so"
echo /opt/.pad/aaiwshim.so > "$R/etc/ld.so.preload"
mkfifo -m 666 "$R/tmp/pad_input"
ln -s "$R/tmp/pad_input" "$DP_RIG/input"
# The shim's log lives in the root's /opt/.pad, i.e. in the slot's own
# writable layer: it outlives the run (a log in the root's /tmp went with the
# tmpfs when the run was taken down - and with it why the game ended).
: > "$R/opt/.pad/rig.log"; chmod 666 "$R/opt/.pad/rig.log"
ln -s "$DP_RIG/upper/opt/.pad/rig.log" "$DP_RIG/rig.log"
cp "$AAIW/switches.json" "$DP_RIG/switches.json"
echo "$BUILD" > "$DP_RIG/build"
cat "$BUILD/version" > "$DP_RIG/ver" 2>/dev/null
echo "$VISIBLE" > "$DP_RIG/visible"
echo aaiw > "$DP_RIG/kind"

CLOSED=$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(",".join(str(s["proc"]) for s in d["switches"] if s["rest"] == "closed"))
' "$AAIW/switches.json")
TROUGH=${AAIW_BALLS:-5}
CLOSED="$CLOSED,$(seq -s, 2 $((TROUGH + 1)))"      # optos 2..6 = 5 balls

if [ $VISIBLE = 1 ]; then
    DISP=${DISPLAY:-:0}
    WIN_ENV="DPEMU_FRAME=1"
else
    DISP=$DP_DISPLAY
    WIN_ENV=""
    setsid -f Xvfb "$DISP" -screen 0 1920x1080x24 -nolisten tcp -noreset \
        < /dev/null > "$DP_RIG/xvfb.log" 2>&1
    dp_wait_display "$DISP" || { echo "run: the hidden display $DISP did not come up" >&2; cat "$DP_RIG/xvfb.log" >&2; exit 3; }
    pgrep -xf "Xvfb $DISP .*" | head -1 > "$DP_RIG/xvfb.pid"
fi
echo "$DISP" > "$DP_RIG/display"
# the X server's socket, inside the root
mount --bind "$(readlink -f /tmp/.X11-unix)" "$R/tmp/.X11-unix" && mount --make-rslave "$R/tmp/.X11-unix"

if [ $AUDIO = 1 ] && [ -S /mnt/wslg/PulseServer ]; then
    # The root's SDL2 has no PulseAudio driver (ALSA, OSS, disk, dummy
    # only), so the game's sound goes out through SDL's disk driver into a
    # FIFO, and a relay on this side plays it to WSLg's PulseAudio.  The
    # stream's format is whatever the game opens - aaiwshim.c logs it
    # ("audio: <rate> <SDL format> <channels>"), so the relay waits for that
    # line.  The game's open of the FIFO waits for a reader, so a format the
    # relay cannot name is still read (and dropped) rather than left to hang.
    # SDL_DISKAUDIODELAY=0: the disk driver must not keep time itself - its
    # own sleep drifted against WSLg's playback clock and the sound dropped
    # out for ~1/4 s every few seconds (PAD-263).  With no delay its writes
    # block on the FIFO, so the relay's PulseAudio stream sets the pace, as
    # a real sound card would.
    mkfifo -m 666 "$R/tmp/pad_audio"
    AUDIO_ENV="SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=/tmp/pad_audio SDL_DISKAUDIODELAY=0"
    setsid -f bash -c '
        log=$1 fifo=$2 user=$3 pidf=$4
        echo $$ > "$pidf"
        for _ in $(seq 1 600); do grep -q "^audio:" "$log" 2>/dev/null && break; sleep 0.1; done
        set -- $(grep -m1 "^audio:" "$log")
        case "$3" in
            0x8010) f=s16le ;; 0x10) f=u16le ;; 0x8008) f=s8 ;; 0x8) f=u8 ;;
            0x8020) f=s32le ;; 0x8120) f=f32le ;;
            *) echo "unknown audio format $3: dropping the sound" >&2; exec cat "$fifo" > /dev/null ;;
        esac
        exec runuser -u "$user" -- env PULSE_SERVER=unix:/mnt/wslg/PulseServer \
            ffmpeg -nostdin -loglevel error -f "$f" -ar "$2" -ac "$4" -i "$fifo" \
            -f pulse -name "PAD Dutch Pinball" "Alice"
    ' relay "$DP_RIG/rig.log" "$R/tmp/pad_audio" "$DP_USER" "$DP_RIG/audio.pid" \
        < /dev/null > "$DP_RIG/audio.log" 2>&1
else
    AUDIO_ENV="SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=/dev/null"
fi

# shellcheck disable=SC2086
setsid -f chroot --userspec="$U:$GID" "$R" /usr/bin/env -i \
    HOME=/opt PATH=/usr/bin:/bin:/usr/sbin:/sbin DISPLAY="$DISP" $AUDIO_ENV $WIN_ENV \
    DPEMU_FIFO=/tmp/pad_input DPEMU_LOG=/opt/.pad/rig.log DPEMU_LABEL="${PAD_LABEL:-PAD}" \
    AAIW_CLOSED="$CLOSED" \
    /bin/sh -c 'cd /opt && ./pinterface; echo "exit: $?" >> /opt/.pad/rig.log' \
    < /dev/null > "$DP_RIG/game.out" 2>&1

# Its windows mean it is up.
for _ in $(seq 1 300); do
    grep -q '^video:' "$DP_RIG/rig.log" 2>/dev/null && break
    sleep 0.1
done
for p in $(pgrep -x pinterface); do
    [ "$(readlink "/proc/$p/root")" = "$R" ] && echo "$p" && break
done > "$DP_RIG/game.pid"
if dp_game_alive && grep -q '^video:' "$DP_RIG/rig.log"; then
    echo "Ready: $NAME, slot $DP_SLOT, display $DISP ($(grep '^video:' "$DP_RIG/rig.log" | cut -d' ' -f2 | paste -sd' '))"
    rigboard_post dp "$DP_SLOT" "$(dp_game_pid)" "$NAME" "${PAD_TITLE:-Alice's Adventures in Wonderland}" "$VISIBLE" "$AUDIO"
else
    echo "run_aaiw.sh: the game did not come up:" >&2
    tail -20 "$DP_RIG/game.out" >&2
    exit 1
fi
