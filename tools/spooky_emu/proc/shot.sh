#!/bin/bash
# shot.sh <out.png> - capture this slot's screen (hidden or visible).  A
# hidden display lives in the rig's network namespace, so the grab runs
# there.
. "$(dirname "$0")/sppath.sh"
OUT=${1:?usage: shot.sh <out.png>}
spp_alive game || { echo "shot.sh: rig $SPP_SLOT's game is not running" >&2; exit 1; }
NS=
[ "$(cat "$SPP_RIG/visible" 2>/dev/null)" = 1 ] || NS="nsenter -t $(spp_pid ns) -n"
$NS ffmpeg -loglevel error -y -f x11grab -video_size "$(cat "$SPP_RIG/screen")" \
    -i "$(cat "$SPP_RIG/display")+0,0" -frames:v 1 "$OUT" || exit 1
echo "$OUT"
