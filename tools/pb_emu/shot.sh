#!/bin/bash
# shot.sh <out.png> - capture this slot's game screen (hidden or visible).
# vidprog draws one 1920x1080 window at 0,0.
. "$(dirname "$0")/pbpath.sh"
OUT=${1:?usage: shot.sh <out.png>}
pb_game_alive || { echo "shot.sh: rig $PB_SLOT not running" >&2; exit 1; }
ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size 1920x1080 \
    -i "$(cat "$PB_RIG/display")+0,0" -frames:v 1 "$OUT" || exit 1
echo "$OUT"
