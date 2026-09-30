#!/bin/bash
# netns.sh - run_game.sh's inside half, run by `unshare --net --mount` as
# root: bring up the namespace's own loopback, bind the rig's copy of the
# build on /game, then start apiav and the game as $AV_USER and wait.
# Writes apiav.pid / game.pid (host pids; killgame.sh stops them).
set -u
# lo starts down in a new network namespace (no `ip` in PAD-Runtime).
python3 - <<'PY'
import fcntl, socket, struct
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
IFF_UP, IFF_LOOPBACK, IFF_RUNNING = 0x1, 0x8, 0x40
fcntl.ioctl(s, 0x8914, struct.pack("16sH14x", b"lo", IFF_UP | IFF_LOOPBACK | IFF_RUNNING))  # SIOCSIFFLAGS
PY
mount --bind "$AV_RIG/game" /game || exit 3
echo $$ > "$AV_RIG/ns.pid"
if [ "${AV_XVFB:-0}" = 1 ]; then
    # main 1920x1080 at 0,0; the HUD 800x480 at 1920,1080 (screens.json);
    # --sim's panel beside main.
    Xvfb "$DISPLAY" -screen 0 2720x1560x24 -nolisten tcp < /dev/null > "$AV_RIG/xvfb.log" 2>&1 &
    echo $! > "$AV_RIG/xvfb.pid"
    for _ in $(seq 1 50); do grep -q "@/tmp/.X11-unix/X${DISPLAY#:}\$" /proc/net/unix && break; sleep 0.1; done
fi

E=$AV_ENV
run_as() {      # <log> <cmd...>: as $AV_USER, env built from scratch
    local log=$1; shift
    runuser -u "$AV_USER" -- env -i \
        PATH="$E/bin:/usr/local/bin:/usr/bin:/bin" HOME="$AV_RIG" USER="$AV_USER" LANG=C.UTF-8 LOCPATH="$E/locale" \
        DISPLAY="$DISPLAY" SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-}" \
        SDL_DISKAUDIOFILE="${SDL_DISKAUDIOFILE:-}" SDL_DISKAUDIODELAY="${SDL_DISKAUDIODELAY:-}" \
        PULSE_SERVER="${PULSE_SERVER:-}" \
        LD_LIBRARY_PATH="$E/lib" GST_PLUGIN_SYSTEM_PATH="$E/lib/gstreamer-1.0" \
        GST_REGISTRY="$AV_RIG/gst-registry.bin" \
        PYTHONPATH="$AV_STUB:/game" PROC_EMU_FPGA="$PROC_EMU_FPGA" \
        "$@" < /dev/null > "$log" 2>&1 &
    echo $!
}
cd /game || exit 3
# apiav first: the game's AVController dials it and queues until it answers.
# (stdbuf: its log is stdio, block-buffered into a file and lost on a kill.)
run_as "$AV_RIG/apiav.out" stdbuf -oL -eL ./apiav -d "$AV_TITLE/assets" > "$AV_RIG/apiav.rpid"
cd "/game/$AV_TITLE" || exit 3
run_as "$AV_RIG/game.out" "$E/bin/python3" -u launcher.py > "$AV_RIG/game.rpid"
sleep 0.5
# runuser's child is the process that matters.
for n in apiav game; do
    r=$(cat "$AV_RIG/$n.rpid"); c=$(pgrep -P "$r" | head -1)
    echo "${c:-$r}" > "$AV_RIG/$n.pid"
done
wait
