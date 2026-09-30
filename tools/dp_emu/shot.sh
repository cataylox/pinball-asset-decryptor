#!/bin/bash
# shot.sh <out.png> - capture this slot's game windows (hidden or visible):
# the box around every window the game opened, from the geometry its shim
# logged ("video: WxH" for The Big Lebowski's one window at the top left,
# "video: WxH@X,Y" for each of Alice's).
. "$(dirname "$0")/dppath.sh"
OUT=${1:?usage: shot.sh <out.png>}
dp_game_alive || { echo "shot.sh: rig $DP_SLOT not running" >&2; exit 1; }
DISP=$(cat "$DP_RIG/display")
BOX=$(grep '^video:' "$DP_RIG/rig.log" | python3 -c '
import re, sys
x1 = y1 = 0
for line in sys.stdin:
    m = re.match(r"video: (\d+)x(\d+)(?:@(\d+),(\d+))?", line)
    if m:
        w, h, x, y = (int(v or 0) for v in m.groups())
        x1, y1 = max(x1, x + w), max(y1, y + h)
print("%dx%d" % (x1 or 1366, y1 or 512))
')
ffmpeg -loglevel error -y -f x11grab -video_size "$BOX" -i "$DISP+0,0" \
    -frames:v 1 "$OUT" || exit 1
echo "$OUT"
