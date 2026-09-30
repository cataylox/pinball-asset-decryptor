#!/bin/bash
# shot.sh <out.png> [main|airlock] - capture this slot's screens: both LCDs
# side by side (2166x768), or just the 1366x768 main one or the 800x480
# Airlock one.  A hidden run's display lives in the slot's own network
# namespace, so the capture runs there.
. "$(dirname "$0")/pbiopath.sh"
OUT=${1:?usage: shot.sh <out.png> [main|airlock]}
pbio_game_alive || { echo "shot.sh: rig $PBIO_SLOT not running" >&2; exit 1; }
case "${2:-both}" in
    main) G=1366x768; O=+0,0 ;;
    airlock) G=800x480; O=+1366,0 ;;
    *) G=$(cat "$PBIO_RIG/window" 2>/dev/null || echo 2166x768); O=+0,0 ;;
esac
pbio_in_net ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size "$G" \
    -i "$(cat "$PBIO_RIG/display")$O" -frames:v 1 "$OUT" || exit 1
echo "$OUT"
