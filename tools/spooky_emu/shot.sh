#!/bin/bash
# shot.sh <out.png> - capture this slot's game screen (hidden or visible).
# Beetlejuice draws one 1920x1080 window at 0,0.
. "$(dirname "$0")/spkpath.sh"
OUT=${1:?usage: shot.sh <out.png>}
spk_game_alive || { echo "shot.sh: rig $SPK_SLOT not running" >&2; exit 1; }
ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size 1920x1080 \
    -i "$(cat "$SPK_RIG/display")+0,0" -frames:v 1 "$OUT" || exit 1
echo "$OUT"
