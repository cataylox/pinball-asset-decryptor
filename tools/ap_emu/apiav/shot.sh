#!/bin/bash
# shot.sh <out.png> [main|hud|all] - capture this slot's screens (hidden or
# visible): main = the 1920x1080 main screen (default), hud = the 800x480
# HUD at 1920,1080, all = both (and --sim's panel).  A hidden display lives
# in the rig's network namespace, so the grab runs there.
. "$(dirname "$0")/avpath.sh"
OUT=${1:?usage: shot.sh <out.png> [main|hud|all]}
av_alive apiav || { echo "shot.sh: rig $AV_SLOT's apiav is not running" >&2; exit 1; }
case "${2:-main}" in
    main) SIZE=1920x1080; AT=+0,0 ;;
    hud) SIZE=800x480; AT=+1920,1080 ;;
    all) SIZE=2720x1560; AT=+0,0 ;;
    *) echo "shot.sh: main, hud or all" >&2; exit 2 ;;
esac
NS=
[ "$(cat "$AV_RIG/visible" 2>/dev/null)" = 1 ] || NS="nsenter -t $(av_pid ns) -n"
$NS ffmpeg -loglevel error -y -f x11grab -video_size $SIZE -i "$(cat "$AV_RIG/display")$AT" \
    -frames:v 1 "$OUT" || exit 1
echo "$OUT"
