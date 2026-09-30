#!/bin/bash
# shot.sh <out.png> - capture this slot's game (hidden or visible): the
# screen area from 0,0 that covers every window the game opened on the
# display (Houdini's second display sits beside its main one).  An A/V title
# draws in apiav's windows, which the game does not open: the drawn area is
# found on the display instead (its own window is parked off-screen).
. "$(dirname "$0")/appath.sh"
OUT=${1:?usage: shot.sh <out.png>}
ap_game_alive || { echo "shot.sh: rig $AP_SLOT not running" >&2; exit 1; }
DISP=$(cat "$AP_RIG/display")
if [ -f "$AP_RIG/av" ]; then
    # Tank: a 1920x1080 screen and AP's playfield panel beside it; Hot Wheels
    # 1366x768.  Crop the whole display to what is drawn, from 0,0.
    CROP=$(ffmpeg -hide_banner -f x11grab -video_size 2560x1440 -i "$DISP+0,0" -frames:v 3 \
        -vf cropdetect=limit=0:round=2:reset=0 -f null - 2>&1 | grep -o 'crop=[0-9:]*' | tail -1)
    IFS=: read -r W H X Y <<< "${CROP#crop=}"
    SIZE=$(( ${W:-1366} + ${X:-0} ))x$(( ${H:-768} + ${Y:-0} ))
else
    SIZE=$(grep ' window: ' "$AP_RIG/rig.log" | awk '{split($3,a,/[x+]/); if (a[3] >= 2560) next;
        r=a[1]+a[3]; b=a[2]+a[4]; if (r>W) W=r; if (b>H) H=b}
        END {if (W<1366) W=1366; if (H<768) H=768; if (W>2560) W=2560; if (H>1440) H=1440; printf "%dx%d", W, H}')
fi
ffmpeg -loglevel error -y -f x11grab -video_size "${SIZE:-1366x768}" -i "$DISP+0,0" \
    -frames:v 1 "$OUT" || exit 1
echo "$OUT"
