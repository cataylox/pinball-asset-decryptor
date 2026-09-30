#!/bin/bash
# run_game.sh <build> [--visible] [--audio]
#
# Start a Pinball Brothers I/O-board title (pbiotitles.py: Alien) on this PC,
# on the rig's emulated I/O board (pbioboard.py).  <build> is a folder
# prepare.sh made (a name under $PBIO_CACHE or a path).  Run as root.
# Returns once the game reached attract mode (or it died).
#
#   --visible   draw on the WSLg desktop instead of the slot's hidden Xvfb
#   --audio     not supported yet: the game's SDL 1.2 speaks ALSA only, and
#               the rig always runs muted (SDL's dummy driver)
#
# The machine is a PC running Buildroot Linux: pinprog (the game: rules,
# lamps, sound, the I/O boards on USB serial) and vidprog (SDL2 +
# GStreamer: the 1366x768 LCD and the 800x480 "Airlock" LCD beside it, one
# X screen 2166x768) talking over TCP port 5555.  The rig runs both in a
# chroot of the machine's own root partition - its libraries, as shipped -
# with the update layers over it (overlayfs), in private mount and network
# namespaces: port 5555 is fixed, so each slot has its own loopback, and its
# hidden Xvfb runs inside that namespace.
#
#   /dev/ttyACM0, /dev/ttyUSB0   the board's two ptys (pbioboard.py)
#   /game/<title>/nvram          $PBIO_NV/<title>, kept between runs
#                                (PBIO_FRESH=1 starts over from the image's)
#   /mnt/log                     $PBIO_RIG: pinprog.log, vidprog.log
#   date -s, hwclock, reboot, the init scripts, firmware-update.sh
#                                logging no-ops ($PBIO_RIG/shell.log), and the
#                                game runs without CAP_SYS_TIME / SYS_BOOT
set -u
. "$(dirname "$0")/pbiopath.sh"
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
case "$BUILD" in /*) ;; "") ;; *) BUILD=$PBIO_CACHE/$BUILD ;; esac
[ -n "$BUILD" ] && [ -f "$BUILD/layers" ] ||
    { echo "run_game.sh: not a prepared build: ${BUILD:-<none>} (prepare.sh)" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root" >&2; exit 2; }
AUDIO=$(rigboard_audio "$VISIBLE" "$AUDIO")
[ "$AUDIO" = 1 ] && echo "run_game.sh: --audio is not supported yet; running muted" >&2

TITLE=$(cat "$BUILD/title")
tget() { python3 "$PBIO_TOOLS/pbiotitles.py" get "$TITLE" "$1"; }
DIR=$(tget dir)
[ -n "$DIR" ] || { echo "run_game.sh: unknown title $TITLE" >&2; exit 2; }

bash "$PBIO_TOOLS/killgame.sh" >/dev/null 2>&1
# a previous run's mounts live in its own namespace; only files are left
rm -rf "$PBIO_RIG"
mkdir -p "$PBIO_RIG"/{upper,work,root}
export PBIO_MARK=$PBIO_RIG

# The layers, top first; the OS image must be mounted (prepare.sh did, but
# not since WSL last restarted)
LOWER=
while read -r L; do
    [ -n "$L" ] || continue
    case "$L" in
        */mnt) [ -f "$(dirname "$L")/root.img" ] && { mkdir -p "$L"
               mountpoint -q "$L" || mount -o loop,ro "$(dirname "$L")/root.img" "$L"; } ;;
    esac
    [ -d "$L/game" ] || { echo "run_game.sh: layer missing: $L (prepare.sh again)" >&2; exit 2; }
    LOWER=${LOWER:+$LOWER:}$L
done < "$BUILD/layers"

# nvram (settings, audits, high scores): per slot and title
NV=$PBIO_NV/$TITLE
[ "${PBIO_FRESH:-0}" = 1 ] && rm -rf "$NV"
if [ ! -d "$NV" ]; then
    mkdir -p "$NV"
    IFS=: read -ra LS <<< "$LOWER"
    for L in "${LS[@]}"; do
        if [ -d "$L/game/$DIR/nvram" ]; then cp -a "$L/game/$DIR/nvram/." "$NV/"; break; fi
    done
fi

# The machine's root and power commands are no-ops (logged), shadowing the
# image's in the run's own upper layer.
U=$PBIO_RIG/upper
mkdir -p "$U/usr/bin" "$U/usr/sbin" "$U/sbin" "$U/etc/init.d"
stub() {    # <path in the root>
    cat > "$U$1" <<'EOF'
#!/bin/sh
echo "$(date '+%H:%M:%S' 2>/dev/null) $0 $*" >> /mnt/log/shell.log
exit 0
EOF
    chmod 755 "$U$1"
}
for p in /usr/sbin/hwclock /sbin/hwclock /sbin/reboot /sbin/poweroff /sbin/halt \
         /usr/bin/firmware-update.sh /etc/init.d/S03vidprog /etc/init.d/S11vidprog \
         /etc/init.d/S02pinprog /usr/bin/sysinfo.sh; do stub "$p"; done
# date: reading it is fine, setting it is not
cat > "$U/usr/bin/date" <<'EOF'
#!/bin/sh
case " $* " in *" -s "*|*" --set"*)
    echo "$(/bin/busybox date '+%H:%M:%S') date $*" >> /mnt/log/shell.log; exit 0 ;; esac
exec /bin/busybox date "$@"
EOF
chmod 755 "$U/usr/bin/date"

# The board
PBIO_TITLE=$TITLE setsid python3 "$PBIO_TOOLS/pbioboard.py" "$PBIO_RIG" \
    > "$PBIO_RIG/board.out" 2>&1 < /dev/null &
echo $! > "$PBIO_RIG/board.pid"
for _ in $(seq 1 50); do [ -f "$PBIO_RIG/usb.tty" ] && break; sleep 0.1; done
[ -f "$PBIO_RIG/usb.tty" ] || { echo "run_game.sh: the board did not start (board.out)" >&2; exit 1; }
ACM=$(cat "$PBIO_RIG/acm.tty"); USB=$(cat "$PBIO_RIG/usb.tty")
python3 "$PBIO_TOOLS/pbiotitles.py" switches "$TITLE" > "$PBIO_RIG/switches.json"

if [ "$VISIBLE" = 1 ]; then DISP=:0; else DISP=$PBIO_DISPLAY; fi
echo "$DISP" > "$PBIO_RIG/display"
echo "$VISIBLE" > "$PBIO_RIG/visible"
echo "$TITLE" > "$PBIO_RIG/title"
echo "$BUILD" > "$PBIO_RIG/build"
# the X screen: Alien's two LCDs side by side (1366x768 + the 800x480
# Airlock), ABBA's one 1920x1080 LCD
SCREEN=$(tget screen); SCREEN=${SCREEN:-2166x768}
VIDARGS=$(tget vidargs)
echo "$SCREEN" > "$PBIO_RIG/window"

R=$PBIO_RIG/root
cat > "$PBIO_RIG/inner.sh" <<EOF
# in private mount + network namespaces (run_game.sh)
set -u
python3 -c "import socket,fcntl,struct; fcntl.ioctl(socket.socket(), 0x8914, struct.pack('16sh', b'lo', 0x41))"
mount -t overlay overlay -o lowerdir=$LOWER,upperdir=$U,workdir=$PBIO_RIG/work $R || exit 1
mount -t proc proc $R/proc
mount -t tmpfs tmpfs $R/tmp
mount -t tmpfs tmpfs $R/run
mount -t tmpfs -o mode=755 tmpfs $R/dev
for d in null zero random urandom tty full; do touch $R/dev/\$d; mount --bind /dev/\$d $R/dev/\$d; done
mkdir -p $R/dev/pts $R/dev/shm $R/mnt/log $R/tmp/.X11-unix
touch $R/dev/ttyACM0 $R/dev/ttyUSB0
mount --bind $ACM $R/dev/ttyACM0
mount --bind $USB $R/dev/ttyUSB0
mount --bind $PBIO_RIG $R/mnt/log
mkdir -p $R/game/$DIR/nvram
mount --bind $NV $R/game/$DIR/nvram
if [ $VISIBLE = 1 ]; then
    mount --bind /tmp/.X11-unix $R/tmp/.X11-unix
else
    Xvfb $DISP -screen 0 ${SCREEN}x24 -nolisten tcp > $PBIO_RIG/xvfb.log 2>&1 &
    echo \$! > $PBIO_RIG/xvfb.pid
    sleep 1
fi
export DISPLAY=$DISP SDL_AUDIODRIVER=dummy HOME=/root TERM=linux
DROP=-sys_time,-sys_boot,-sys_module,-sys_rawio,-mknod
setpriv --bounding-set \$DROP chroot $R /bin/sh -c 'cd /game/$DIR && exec ./pinprog -o /mnt/log/pinprog.log' \
    > $PBIO_RIG/pinprog.out 2>&1 < /dev/null &
PIN=\$!
echo \$PIN > $PBIO_RIG/game.pid
# vidprog, restarted as the machine's init script does if it dies
(
    while kill -0 \$PIN 2>/dev/null; do
        sleep 1
        setpriv --bounding-set \$DROP chroot $R /bin/sh -c 'cd /game/$DIR && exec ./vidprog $VIDARGS -o /mnt/log/vidprog.log' \
            >> $PBIO_RIG/vidprog.out 2>&1 < /dev/null &
        echo \$! > $PBIO_RIG/vidprog.pid
        echo \$PIN \$! > $PBIO_RIG/game.pids
        wait \$!
    done
) &
wait \$PIN
kill \$(cat $PBIO_RIG/vidprog.pid 2>/dev/null) 2>/dev/null
[ -f $PBIO_RIG/xvfb.pid ] && kill \$(cat $PBIO_RIG/xvfb.pid) 2>/dev/null
EOF
setsid unshare -m -n --propagation private bash "$PBIO_RIG/inner.sh" pbio_ns \
    > "$PBIO_RIG/inner.log" 2>&1 < /dev/null &
echo $! > "$PBIO_RIG/ns.pid"

for _ in $(seq 1 60); do [ -f "$PBIO_RIG/game.pid" ] && break; sleep 0.25; done
# attract: the board handshake, the tongue calibration (Alien), self-test
for _ in $(seq 1 240); do
    pbio_attract && break
    pbio_game_alive || break
    sleep 0.5
done
if ! pbio_game_alive; then
    echo "run_game.sh: the game exited (pinprog.log, pinprog.out, inner.log)" >&2
    tail -5 "$PBIO_RIG/pinprog.log" >&2 2>/dev/null
    exit 1
fi
if pbio_attract; then
    rigboard_post pbio "$PBIO_SLOT" "$(pbio_game_pid)" "$(basename "$BUILD")" "${PAD_TITLE:-$(tget name)}" "$VISIBLE" 0
    echo "attract"
    exit 0
fi
echo "run_game.sh: no attract mode in 120 s (pinprog.log)" >&2
exit 1
