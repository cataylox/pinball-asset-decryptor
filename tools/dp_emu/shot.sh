#!/bin/bash
# shot.sh <out.png> - capture this slot's game window (hidden or visible).
# The game draws its colour DMD in one borderless window at the top left;
# its size is the video mode dpinput.so logged.
. "$(dirname "$0")/dppath.sh"
OUT=${1:?usage: shot.sh <out.png>}
dp_game_alive || { echo "shot.sh: rig $DP_SLOT not running" >&2; exit 1; }
DISP=$(cat "$DP_RIG/display")
SIZE=$(grep '^video:' "$DP_RIG/rig.log" | tail -1 | cut -d' ' -f2)
ffmpeg -loglevel error -y -f x11grab -video_size "${SIZE:-1366x512}" -i "$DISP+0,0" \
    -frames:v 1 "$OUT" || exit 1
echo "$OUT"
