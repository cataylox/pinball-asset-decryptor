#!/bin/bash
# run_game.sh [<build>] - start CGC's Pulp Fiction on this PC, on the rig's
# emulated BeagleBone I/O (pfshim.so), and return once it is in attract mode.
#
# <build> is a folder prepare.py made (a name under $CGCPF_CACHE or a path;
# default: the newest there).  Run as root; the game runs as the machine's user (uid 1000).
# Always hidden and muted: the game's only picture is its HDMI output, kept
# in a file (shot.sh); SDL plays sound into the dummy driver.
#
# The machine's own Ubuntu 12.10 (the carved rootfs.img, read-only) is the
# game's root, under an overlay whose upper layer is this run's; its /tmp is
# $CGCPF_RIG/tmp, where the game writes z4.log (ours to read).  qemu-arm runs it (the
# kernel's binfmt entry); LD_PRELOAD=pfshim.so stands in for the display,
# the PRU and its playfield board, the FRAM, the cabinet's GPIO bus and
# /dev/mem.  pfball.py moves the balls.  The game's argument is its log
# level: CGCPF_LOGLEVEL (default 5, every proc and ball move in z4.log).
# Switches: sw.py.  Picture: shot.sh.  Stop: killgame.sh.
set -u
. "$(dirname "$0")/cgcpfpath.sh"
BUILD=${1:-}
[ -z "$BUILD" ] && BUILD=$(ls -1td "$CGCPF_CACHE"/*/ 2>/dev/null | head -1)
case "$BUILD" in /*) ;; "") ;; *) BUILD=$CGCPF_CACHE/$BUILD ;; esac
BUILD=${BUILD%/}
[ -n "$BUILD" ] && [ -f "$BUILD/.ready" ] && [ -f "$BUILD/rootfs.img" ] ||
    { echo "run_game.sh: not a prepared build: ${BUILD:-<none>} (prepare.py)" >&2; exit 2; }
[ -f "$CGCPF_SHIM" ] || { echo "run_game.sh: no $CGCPF_SHIM (build.sh)" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to the machine's user itself)" >&2; exit 2; }
grep -q enabled /proc/sys/fs/binfmt_misc/qemu-arm 2>/dev/null ||
    { echo "run_game.sh: no qemu-arm binfmt entry (qemu-user-static)" >&2; exit 2; }
NAME=$(basename "$BUILD")
# The machine's own account: ubuntu, uid 1000, gid 1001, the owner of
# /home/ubuntu/pin (mode 770) in the image.
UID_=1000; GID_=1001

bash "$CGCPF_TOOLS/killgame.sh" >/dev/null 2>&1

rm -rf "$CGCPF_RIG"
mkdir -p "$CGCPF_RIG"/{upper,work,root,io,lower,tmp}
NV=$CGCPF_ROOT/nv$CGCPF_SLOT/$NAME
[ "${CGCPF_FRESH:-0}" = 1 ] && rm -rf "$NV"
mkdir -p "$NV"
cp "$CGCPF_SHIM" "$CGCPF_RIG/io/pfshim.so"
python3 "$CGCPF_TOOLS/sw.py" home               # balls home, the coin door shut
chown -R "$UID_:$GID_" "$CGCPF_RIG/io" "$CGCPF_RIG/tmp" "$NV"
echo "$BUILD" > "$CGCPF_RIG/build"

ENVS="PATH=/usr/bin:/bin HOME=/home/ubuntu PF_RIG=/pfrig/io PF_NV=/pfnv PF_MODES=${CGCPF_MODES:-} \
PF_SHIMLOG=/pfrig/io/shim.log LD_PRELOAD=/pfrig/io/pfshim.so \
SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=dummy CGCPF_MARK=$CGCPF_RIG"
R=$CGCPF_RIG/root
# ns.sh: the private mounts, then the game.  It records itself for
# killgame.sh.  The loop mount lives in this namespace only and goes (with
# its loop device) when the namespace does.
cat > "$CGCPF_RIG/ns.sh" <<EOF
echo \$\$ > $CGCPF_RIG/ns.pid
set -e
mount -o loop,ro "$BUILD/rootfs.img" $CGCPF_RIG/lower
mount -t overlay overlay -o lowerdir=$CGCPF_RIG/lower,upperdir=$CGCPF_RIG/upper,workdir=$CGCPF_RIG/work $R
mount -t tmpfs -o mode=755 tmpfs $R/dev
for d in null:1:3 zero:1:5 random:1:8 urandom:1:9 tty:5:0; do
    IFS=: read -r n a b <<< "\$d"; mknod -m 666 $R/dev/\$n c \$a \$b
done
mkdir -p $R/dev/shm $R/pfrig $R/pfnv
mount -t tmpfs tmpfs $R/dev/shm
mount -t proc proc $R/proc
mount --bind $CGCPF_RIG $R/pfrig
mount --bind $NV $R/pfnv
# the game's logs (z4.log, score.log): the image's /tmp holds the machine's
# last ones, root's, which the game could not reopen
mount --bind $CGCPF_RIG/tmp $R/tmp
set +e
cd /
chroot --userspec=$UID_:$GID_ $R /usr/bin/env -i $ENVS /bin/sh -c \
    'cd /home/ubuntu/pin && exec ./pin ${CGCPF_LOGLEVEL:-5}' > $CGCPF_RIG/pin.out 2>&1
EOF
# Detached whole (setsid -f, stdin closed): a child of the wsl.exe that
# started this dies with it (tools/bof_emu learned it).  A private mount,
# pid, network, UTS and IPC namespace: the game sees no network (it only
# shows its IP) and cannot touch this PC's processes.
setsid -f env CGCPF_MARK="$CGCPF_RIG" unshare -m -n -u -i -p --fork --propagation private \
    bash "$CGCPF_RIG/ns.sh" < /dev/null > "$CGCPF_RIG/ns.out" 2>&1
setsid -f env CGCPF_MARK="$CGCPF_RIG" python3 -u "$CGCPF_TOOLS/pfball.py" \
    < /dev/null > "$CGCPF_RIG/ball.log" 2>&1

for _ in $(seq 1 100); do
    p=$(cgcpf_find_game) && { echo "$p" > "$CGCPF_RIG/game.pid"; break; }
    sleep 0.1
done
cgcpf_game_alive || { echo "run_game.sh: the game did not start:" >&2
    cat "$CGCPF_RIG/ns.out" "$CGCPF_RIG/pin.out" >&2 2>/dev/null; exit 1; }

# Up = the game loop runs and its state word says attract.  The first boot
# of a build reads ~600 MB of sound banks (a couple of minutes from C:).
LOG=$(cgcpf_log)
for i in $(seq 1 ${CGCPF_BOOT_S:-600}); do
    if grep -q "Starting pin_gameloop" "$LOG" 2>/dev/null && [ "$(cgcpf_peek $CGCPF_STATE_ADDR)" = 1 ]; then
        echo "Ready: $NAME, slot $CGCPF_SLOT (attract)"
        rigboard_post cgcpf "$CGCPF_SLOT" "$(cgcpf_game_pid)" "$NAME" "Pulp Fiction" 0 0
        exit 0
    fi
    cgcpf_game_alive || break
    sleep 1
done
echo "run_game.sh: the game did not reach attract:" >&2
tail -20 "$LOG" "$CGCPF_RIG/pin.out" "$CGCPF_RIG/ns.out" "$CGCPF_RIG/io/shim.log" >&2 2>/dev/null
exit 1
